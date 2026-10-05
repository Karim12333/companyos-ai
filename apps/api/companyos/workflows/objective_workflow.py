import asyncio
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from companyos.workflows.types import (
        ApprovalCheck,
        ApprovalResolution,
        EscalationCheck,
        EscalationOutcome,
        EscalationRef,
        ExecuteResult,
        FinalizeInput,
        ObjectiveInput,
        ReadySnapshot,
        ReviewResult,
        TaskFailure,
        TaskRef,
    )

SHORT = timedelta(minutes=2)
AGENT_RUN = timedelta(minutes=20)
APPROVAL_POLL = timedelta(minutes=10)
# Safety cap on execute/review rounds for one task; CEO-guided rounds are included
MAX_TASK_ROUNDS = 25
DB_RETRY = RetryPolicy(maximum_attempts=5, initial_interval=timedelta(seconds=2))
AGENT_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=3,
    non_retryable_error_types=["NonRetryableTaskError"],
)


@workflow.defn(name="ObjectiveWorkflow")
class ObjectiveWorkflow:
    """Durable objective lifecycle: plan → run DAG in parallel → review → approvals → report → notify."""

    def __init__(self) -> None:
        self._paused = False
        self._cancelled = False
        self._wake = False
        self._decided: set[str] = set()
        self._resolved_escalations: set[str] = set()
        self._retry_requests: list[str] = []
        self._running: dict[str, asyncio.Task[None]] = {}
        self._stage = "starting"

    @workflow.signal
    def approval_decided(self, approval_id: str) -> None:
        self._decided.add(approval_id)

    @workflow.signal
    def escalation_resolved(self, escalation_id: str) -> None:
        self._resolved_escalations.add(escalation_id)

    @workflow.signal
    def pause(self) -> None:
        self._paused = True

    @workflow.signal
    def resume(self) -> None:
        self._paused = False
        self._wake = True

    @workflow.signal
    def cancel(self) -> None:
        self._cancelled = True

    @workflow.signal
    def wake(self) -> None:
        self._wake = True

    @workflow.signal
    def retry_task(self, task_id: str) -> None:
        # Handled by this run even if it is already finalizing; requeued in the DB by an activity
        if task_id not in self._retry_requests:
            self._retry_requests.append(task_id)
        self._wake = True

    @workflow.query
    def state(self) -> dict[str, Any]:
        return {
            "stage": self._stage,
            "paused": self._paused,
            "cancelled": self._cancelled,
            "running_tasks": list(self._running),
        }

    @workflow.run
    async def run(self, objective: ObjectiveInput) -> str:
        await workflow.execute_activity(
            "start_objective", objective, start_to_close_timeout=SHORT, retry_policy=DB_RETRY
        )
        self._stage = "planning"
        try:
            await workflow.execute_activity(
                "plan_objective", objective, start_to_close_timeout=AGENT_RUN, retry_policy=AGENT_RETRY
            )
        except ActivityError as error:
            return await self._finalize(objective, planning_error=str(error.cause or error))

        while True:
            await self._execute(objective)
            status = await self._finalize(objective, cancelled=self._cancelled)
            if self._cancelled or not self._retry_requests:
                return status
            # A retry arrived while finishing: reopen the objective in this same run (never two runs at once)
            await workflow.execute_activity(
                "start_objective",
                ObjectiveInput(objective.organization_id, objective.objective_id, resume=True),
                start_to_close_timeout=SHORT,
                retry_policy=DB_RETRY,
            )

    async def _execute(self, objective: ObjectiveInput) -> None:
        self._stage = "executing"
        while not self._cancelled:
            await workflow.wait_condition(lambda: not self._paused or self._cancelled)
            if self._cancelled:
                break
            await self._process_retries(objective)
            snapshot: ReadySnapshot = await workflow.execute_activity(
                "get_ready_tasks",
                objective,
                result_type=ReadySnapshot,
                start_to_close_timeout=SHORT,
                retry_policy=DB_RETRY,
            )
            for task_id in snapshot.ready_task_ids:
                if task_id in self._running or len(self._running) >= snapshot.max_parallel:
                    continue
                ref = TaskRef(objective.organization_id, objective.objective_id, task_id)
                self._running[task_id] = asyncio.create_task(self._run_task(ref, snapshot.max_review_rounds))
            if not self._running:
                if self._retry_requests:
                    continue
                break
            self._wake = False
            await workflow.wait_condition(
                lambda: any(task.done() for task in self._running.values()) or self._cancelled or self._wake
            )
            for task_id, task in list(self._running.items()):
                if task.done():
                    del self._running[task_id]
        if self._cancelled:
            for task in self._running.values():
                task.cancel()

    async def _process_retries(self, objective: ObjectiveInput) -> None:
        while self._retry_requests:
            task_id = self._retry_requests.pop(0)
            await workflow.execute_activity(
                "requeue_task",
                TaskRef(objective.organization_id, objective.objective_id, task_id),
                start_to_close_timeout=SHORT,
                retry_policy=DB_RETRY,
            )

    async def _run_task(self, ref: TaskRef, max_review_rounds: int) -> None:
        """Explicit task state machine; every exit leaves the task in a visible state."""
        mode = "execute"
        try:
            for _ in range(MAX_TASK_ROUNDS):
                if self._cancelled:
                    return
                if mode == "execute":
                    result: ExecuteResult = await workflow.execute_activity(
                        "execute_task",
                        ref,
                        result_type=ExecuteResult,
                        start_to_close_timeout=AGENT_RUN,
                        retry_policy=AGENT_RETRY,
                    )
                    if result.status in ("failed", "skipped"):
                        return
                    if (
                        result.status == "completed"
                        and not result.requires_review
                        and not result.approval_ids
                    ):
                        await self._complete(ref)
                        return
                    if result.approval_ids:
                        await self._await_approvals(ref, result.approval_ids)
                        if self._cancelled or not await self._resolve_approvals(ref):
                            return
                    if result.escalation_ids:
                        mode = await self._await_escalations(ref, result.escalation_ids)
                        continue
                    if not result.requires_review:
                        await self._complete(ref)
                        return
                    mode = "review"
                elif mode == "review":
                    review: ReviewResult = await workflow.execute_activity(
                        "review_task",
                        ref,
                        result_type=ReviewResult,
                        start_to_close_timeout=AGENT_RUN,
                        retry_policy=AGENT_RETRY,
                    )
                    if review.verdict == "accept":
                        return
                    if review.verdict == "escalated" and review.escalation_id:
                        mode = await self._await_escalations(ref, [review.escalation_id])
                        continue
                    mode = "execute"
                else:
                    return
            # Never fall out silently: the safety cap is a visible failure
            await self._mark_failed(ref, f"Task exceeded {MAX_TASK_ROUNDS} execution rounds")
        except ActivityError as error:
            await self._mark_failed(ref, str(error.cause or error))

    async def _resolve_approvals(self, ref: TaskRef) -> bool:
        """Executes approved actions; returns False if the task must stop."""
        while not self._cancelled:
            resolution: ApprovalResolution = await workflow.execute_activity(
                "resolve_task_approvals",
                ref,
                result_type=ApprovalResolution,
                start_to_close_timeout=SHORT,
                retry_policy=DB_RETRY,
            )
            if not resolution.escalation_ids:
                return True
            # Outcome unknown after a crash: the CEO verifies before anything is repeated
            next_mode = await self._await_escalations(ref, resolution.escalation_ids)
            if next_mode == "stop":
                return False
            if next_mode != "retry_action":
                return True
        return False

    async def _complete(self, ref: TaskRef) -> None:
        await workflow.execute_activity(
            "complete_task", ref, start_to_close_timeout=SHORT, retry_policy=DB_RETRY
        )

    async def _mark_failed(self, ref: TaskRef, message: str) -> None:
        await workflow.execute_activity(
            "mark_task_failed",
            TaskFailure(ref.organization_id, ref.objective_id, ref.task_id, message),
            start_to_close_timeout=SHORT,
            retry_policy=DB_RETRY,
        )

    async def _await_escalations(self, ref: TaskRef, escalation_ids: list[str]) -> str:
        """Waits for the CEO and returns the next mode: execute, done or stop."""
        while not self._cancelled and not all(item in self._resolved_escalations for item in escalation_ids):
            try:
                await workflow.wait_condition(
                    lambda: (
                        self._cancelled or all(item in self._resolved_escalations for item in escalation_ids)
                    ),
                    timeout=APPROVAL_POLL,
                )
            except TimeoutError:
                resolved: list[str] = await workflow.execute_activity(
                    "resolved_escalations",
                    EscalationCheck(ref.organization_id, escalation_ids),
                    result_type=list[str],
                    start_to_close_timeout=SHORT,
                    retry_policy=DB_RETRY,
                )
                self._resolved_escalations.update(resolved)
        if self._cancelled:
            return "stop"
        next_mode = "done"
        priority = {"done": 0, "continue": 1, "execute": 2, "retry_action": 3}
        for escalation_id in escalation_ids:
            outcome: EscalationOutcome = await workflow.execute_activity(
                "apply_escalation_resolution",
                EscalationRef(ref.organization_id, ref.objective_id, ref.task_id, escalation_id),
                result_type=EscalationOutcome,
                start_to_close_timeout=SHORT,
                retry_policy=DB_RETRY,
            )
            if outcome.action == "stopped":
                return "stop"
            mode = "execute" if outcome.action == "rerun" else outcome.action
            if priority.get(mode, 0) > priority[next_mode]:
                next_mode = mode
        return next_mode

    async def _await_approvals(self, ref: TaskRef, approval_ids: list[str]) -> None:
        await workflow.execute_activity(
            "notify_approvals",
            ApprovalCheck(ref.organization_id, approval_ids),
            start_to_close_timeout=SHORT,
            retry_policy=DB_RETRY,
        )
        while not self._cancelled and not all(item in self._decided for item in approval_ids):
            try:
                await workflow.wait_condition(
                    lambda: self._cancelled or all(item in self._decided for item in approval_ids),
                    timeout=APPROVAL_POLL,
                )
            except TimeoutError:
                # Safety net: reconcile with the database in case a signal was never sent
                decided: list[str] = await workflow.execute_activity(
                    "decided_approvals",
                    ApprovalCheck(ref.organization_id, approval_ids),
                    result_type=list[str],
                    start_to_close_timeout=SHORT,
                    retry_policy=DB_RETRY,
                )
                self._decided.update(decided)

    async def _finalize(
        self, objective: ObjectiveInput, cancelled: bool = False, planning_error: str | None = None
    ) -> str:
        self._stage = "reporting"
        final = FinalizeInput(objective.organization_id, objective.objective_id, cancelled, planning_error)
        status: str = await workflow.execute_activity(
            "finalize_objective", final, start_to_close_timeout=AGENT_RUN, retry_policy=DB_RETRY
        )
        await workflow.execute_activity(
            "notify_objective_outcome", objective, start_to_close_timeout=SHORT, retry_policy=DB_RETRY
        )
        self._stage = "done"
        return status
