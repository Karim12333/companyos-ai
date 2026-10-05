import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { layoutTasks, TaskGraph } from "@/components/task-graph";
import type { Task } from "@/lib/types";

function task(id: string, dependsOn: string[] = [], status: Task["status"] = "QUEUED"): Task {
  return {
    id, objective_id: "o", parent_task_id: null, assigned_agent_id: null, department_id: null, plan_key: id,
    role_key: "role", title: `Task ${id}`, instructions: "", priority: "normal", status, sequence: 0,
    started_at: null, completed_at: null, retry_count: 0, max_retries: 2, revision_count: 0,
    expected_output_type: "document", acceptance_criteria: [], requires_review: true, output_summary: "",
    review_feedback: "", error_category: null, error_message: null, recoverable: null, result: null,
    execution_metadata: {}, depends_on: dependsOn,
  };
}

describe("layoutTasks", () => {
  it("places parallel tasks in the same column after their shared dependency", () => {
    const positions = layoutTasks([task("a"), task("b", ["a"]), task("c", ["b"]), task("d", ["b"])]);
    expect(positions.get("a")!.x).toBe(0);
    expect(positions.get("c")!.x).toBe(positions.get("d")!.x);
    expect(positions.get("c")!.y).not.toBe(positions.get("d")!.y);
    expect(positions.get("c")!.x).toBeGreaterThan(positions.get("b")!.x);
  });

  it("uses the longest dependency chain for depth", () => {
    const positions = layoutTasks([task("a"), task("b", ["a"]), task("c", ["a", "b"])]);
    expect(positions.get("c")!.x).toBeGreaterThan(positions.get("b")!.x);
  });
});

describe("TaskGraph", () => {
  it("renders each task with its status", () => {
    render(<TaskGraph tasks={[task("a", [], "COMPLETED"), task("b", ["a"], "RUNNING")]} agents={new Map()} />);
    expect(screen.getByText("Task a")).toBeInTheDocument();
    expect(screen.getByText("Completed")).toBeInTheDocument();
    expect(screen.getByText("Running")).toBeInTheDocument();
  });
});
