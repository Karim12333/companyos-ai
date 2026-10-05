from collections.abc import Callable
from typing import Any

from companyos.workflows.activities.approvals import (
    decided_approvals,
    notify_approvals,
    resolve_task_approvals,
)
from companyos.workflows.activities.execution import complete_task, execute_task, mark_task_failed
from companyos.workflows.activities.lifecycle import get_ready_tasks, start_objective
from companyos.workflows.activities.planning import plan_objective
from companyos.workflows.activities.reporting import finalize_objective, notify_objective_outcome
from companyos.workflows.activities.review import review_task

ALL_ACTIVITIES: list[Callable[..., Any]] = [
    start_objective,
    plan_objective,
    get_ready_tasks,
    execute_task,
    mark_task_failed,
    complete_task,
    review_task,
    notify_approvals,
    decided_approvals,
    resolve_task_approvals,
    finalize_objective,
    notify_objective_outcome,
]
