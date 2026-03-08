"""GPU-aware task scheduler for experiment parallelization.

Reads task_plan.json for task definitions and depends_on graph,
tracks progress in exp/gpu_progress.json, and assigns GPU subsets
to independent tasks for parallel execution.
"""
import json
from collections import deque
from pathlib import Path


def topo_sort_layers(tasks: list[dict]) -> list[list[dict]]:
    """BFS topological sort, grouping tasks by dependency layer.

    Each layer contains tasks whose dependencies are all in earlier layers.
    Returns list of layers, each layer is a list of task dicts.
    """
    if not tasks:
        return []

    task_map = {t["id"]: t for t in tasks}
    in_degree = {t["id"]: 0 for t in tasks}
    children = {t["id"]: [] for t in tasks}

    for t in tasks:
        for dep in t.get("depends_on", []):
            if dep in task_map:
                in_degree[t["id"]] += 1
                children[dep].append(t["id"])

    layers = []
    queue = deque([tid for tid, deg in in_degree.items() if deg == 0])

    while queue:
        layer = list(queue)
        queue.clear()
        layers.append([task_map[tid] for tid in layer])
        for tid in layer:
            for child in children[tid]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

    return layers


def assign_gpus(ready_tasks: list[dict], gpu_ids: list[int],
                gpus_per_task: int = 1) -> list[dict]:
    """Assign GPU subsets to ready tasks.

    Returns list of assignments:
        [{"task_ids": ["task_0a"], "gpu_ids": [0]}, ...]

    Total parallel tasks = min(len(ready_tasks), len(gpu_ids) // gpus_per_task).
    """
    if not ready_tasks or not gpu_ids or gpus_per_task < 1:
        return []

    max_parallel = len(gpu_ids) // gpus_per_task
    if max_parallel == 0:
        # Not enough GPUs even for one task — give all GPUs to first task
        return [{"task_ids": [ready_tasks[0]["id"]], "gpu_ids": list(gpu_ids)}]

    assignments = []
    for i, task in enumerate(ready_tasks[:max_parallel]):
        start = i * gpus_per_task
        assigned = gpu_ids[start:start + gpus_per_task]
        assignments.append({
            "task_ids": [task["id"]],
            "gpu_ids": assigned,
        })

    return assignments


def get_next_batch(workspace_root: Path, gpu_ids: list[int], mode: str = "PILOT",
                   gpus_per_task: int = 1) -> list[dict] | None:
    """Get the next batch of experiment tasks to execute.

    Args:
        workspace_root: Path to workspace directory
        gpu_ids: Available GPU IDs
        mode: "PILOT" or "FULL"
        gpus_per_task: Number of GPUs per task

    Returns:
        None: No task_plan.json or no tasks array → fallback to single-agent
        []: Tasks exist but all blocked by dependencies
        [assignments]: Next batch of task-GPU assignments
    """
    task_plan_path = workspace_root / "plan" / "task_plan.json"
    if not task_plan_path.exists():
        return None

    try:
        with open(task_plan_path, encoding="utf-8") as f:
            plan = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    tasks = plan.get("tasks")
    if not tasks or not isinstance(tasks, list):
        return None

    # Load progress
    progress_path = workspace_root / "exp" / "gpu_progress.json"
    completed = set()
    if progress_path.exists():
        try:
            with open(progress_path, encoding="utf-8") as f:
                progress = json.load(f)
            completed = set(progress.get("completed", []))
        except (json.JSONDecodeError, OSError):
            pass

    # Filter out completed tasks
    remaining = [t for t in tasks if t["id"] not in completed]
    if not remaining:
        return None  # All done

    # Find ready tasks (all deps completed)
    ready = [
        t for t in remaining
        if all(dep in completed for dep in t.get("depends_on", []))
    ]

    if not ready:
        return []  # Blocked

    return assign_gpus(ready, gpu_ids, gpus_per_task)
