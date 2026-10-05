# ADR-0002: Temporal for durability, LangGraph for agent reasoning

**Status:** Accepted

## Decision
- **Temporal** owns the objective lifecycle: planning → DAG scheduling → parallel task execution →
  review loops → waiting for approvals (signals) → report → notification. Workflow state survives
  API/worker restarts and browser closure.
- **LangGraph** owns reasoning *inside* an activity: the Chief of Staff planning graph
  (draft → validate → repair) and the agent execution graph (think → tool gateway → think … → finalize)
  with hard iteration limits.
- **PostgreSQL is the source of truth** for plans and task state. The workflow loop asks the DB which
  tasks are ready, so a restarted or re-run workflow resumes from persisted state.

## Why not only LangGraph?
LangGraph checkpointing does not give us timers, signals, retries with backoff, visibility,
and multi-hour/multi-day durability across process restarts the way Temporal does.

## Why not only Temporal?
Temporal is deterministic orchestration; LLM tool loops are non-deterministic and fit better in
activities with a graph runtime that we can test in isolation.
