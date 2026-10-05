"use client";

import { StatusBadge } from "@/components/ui/badge";
import { cn } from "@/lib/format";
import type { Agent, Task } from "@/lib/types";

const NODE_WIDTH = 228;
const NODE_HEIGHT = 84;
const COLUMN_GAP = 64;
const ROW_GAP = 20;

const EDGE_COLORS: Record<string, string> = {
  COMPLETED: "var(--success)",
  FAILED: "var(--danger)",
  BLOCKED: "var(--danger)",
};

// Depth = longest dependency chain, so parallel work shares a column
export function layoutTasks(tasks: Task[]): Map<string, { x: number; y: number }> {
  const byId = new Map(tasks.map((task) => [task.id, task]));
  const depth = new Map<string, number>();
  const resolve = (task: Task, trail: Set<string>): number => {
    if (depth.has(task.id)) return depth.get(task.id)!;
    if (trail.has(task.id)) return 0;
    trail.add(task.id);
    const parents = [...task.depends_on, ...(task.parent_task_id ? [task.parent_task_id] : [])]
      .map((id) => byId.get(id))
      .filter((item): item is Task => Boolean(item));
    const value = parents.length ? Math.max(...parents.map((parent) => resolve(parent, trail) + 1)) : 0;
    depth.set(task.id, value);
    return value;
  };
  tasks.forEach((task) => resolve(task, new Set()));
  const rows = new Map<number, number>();
  const positions = new Map<string, { x: number; y: number }>();
  [...tasks]
    .sort((a, b) => a.sequence - b.sequence)
    .forEach((task) => {
      const column = depth.get(task.id) ?? 0;
      const row = rows.get(column) ?? 0;
      rows.set(column, row + 1);
      positions.set(task.id, { x: column * (NODE_WIDTH + COLUMN_GAP), y: row * (NODE_HEIGHT + ROW_GAP) });
    });
  return positions;
}

export function TaskGraph({
  tasks,
  agents,
  selectedId,
  onSelect,
}: {
  tasks: Task[];
  agents: Map<string, Agent>;
  selectedId?: string | null;
  onSelect?: (task: Task) => void;
}) {
  const positions = layoutTasks(tasks);
  const width = Math.max(...[...positions.values()].map((p) => p.x), 0) + NODE_WIDTH;
  const height = Math.max(...[...positions.values()].map((p) => p.y), 0) + NODE_HEIGHT;
  const edges = tasks.flatMap((task) =>
    [...task.depends_on, ...(task.parent_task_id ? [task.parent_task_id] : [])]
      .filter((id) => positions.has(id))
      .map((from) => ({ from, to: task.id, delegated: from === task.parent_task_id })),
  );
  const statusById = new Map(tasks.map((task) => [task.id, task.status]));

  return (
    <div className="overflow-x-auto pb-2">
      <div className="relative" style={{ width, height }} role="list" aria-label="Task dependency graph">
        <svg className="pointer-events-none absolute inset-0" width={width} height={height} aria-hidden>
          {edges.map((edge) => {
            const start = positions.get(edge.from)!;
            const end = positions.get(edge.to)!;
            const x1 = start.x + NODE_WIDTH;
            const y1 = start.y + NODE_HEIGHT / 2;
            const x2 = end.x;
            const y2 = end.y + NODE_HEIGHT / 2;
            const mid = (x1 + x2) / 2;
            return (
              <path
                key={`${edge.from}-${edge.to}`}
                d={`M ${x1} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${x2} ${y2}`}
                fill="none"
                stroke={EDGE_COLORS[statusById.get(edge.from) ?? ""] ?? "var(--border-strong)"}
                strokeWidth={1.5}
                strokeDasharray={edge.delegated ? "4 4" : undefined}
              />
            );
          })}
        </svg>
        {tasks.map((task) => {
          const position = positions.get(task.id)!;
          const agent = task.assigned_agent_id ? agents.get(task.assigned_agent_id) : undefined;
          return (
            <button
              key={task.id}
              type="button"
              role="listitem"
              onClick={() => onSelect?.(task)}
              className={cn(
                "absolute flex flex-col justify-between rounded-xl border bg-surface px-3 py-2.5 text-left shadow-card transition-colors hover:border-border-strong",
                selectedId === task.id ? "border-accent ring-3 ring-[var(--ring)]" : "border-border",
                task.status === "RUNNING" && "border-info/50",
              )}
              style={{ left: position.x, top: position.y, width: NODE_WIDTH, height: NODE_HEIGHT }}
            >
              <span className="line-clamp-2 text-[13px] leading-snug font-medium text-ink">{task.title}</span>
              <span className="flex items-center justify-between gap-2">
                <span className="truncate text-xs text-muted">{agent?.name ?? task.role_key}</span>
                <StatusBadge status={task.status} />
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
