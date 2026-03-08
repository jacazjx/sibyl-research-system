"""Tests for sibyl.gpu_scheduler module."""
import json
from pathlib import Path

import pytest

from sibyl.gpu_scheduler import topo_sort_layers, assign_gpus, get_next_batch


# ══════════════════════════════════════════════
# Topological sort
# ══════════════════════════════════════════════

class TestTopoSortLayers:
    def test_empty(self):
        assert topo_sort_layers([]) == []

    def test_single_task(self):
        tasks = [{"id": "a", "depends_on": []}]
        layers = topo_sort_layers(tasks)
        assert len(layers) == 1
        assert layers[0][0]["id"] == "a"

    def test_independent_tasks(self):
        tasks = [
            {"id": "a", "depends_on": []},
            {"id": "b", "depends_on": []},
            {"id": "c", "depends_on": []},
        ]
        layers = topo_sort_layers(tasks)
        assert len(layers) == 1
        assert len(layers[0]) == 3

    def test_linear_chain(self):
        tasks = [
            {"id": "a", "depends_on": []},
            {"id": "b", "depends_on": ["a"]},
            {"id": "c", "depends_on": ["b"]},
        ]
        layers = topo_sort_layers(tasks)
        assert len(layers) == 3
        assert layers[0][0]["id"] == "a"
        assert layers[1][0]["id"] == "b"
        assert layers[2][0]["id"] == "c"

    def test_diamond_dag(self):
        tasks = [
            {"id": "a", "depends_on": []},
            {"id": "b", "depends_on": ["a"]},
            {"id": "c", "depends_on": ["a"]},
            {"id": "d", "depends_on": ["b", "c"]},
        ]
        layers = topo_sort_layers(tasks)
        assert len(layers) == 3
        assert layers[0][0]["id"] == "a"
        ids_1 = {t["id"] for t in layers[1]}
        assert ids_1 == {"b", "c"}
        assert layers[2][0]["id"] == "d"

    def test_missing_dep_ignored(self):
        """Dependencies referencing non-existent tasks should be ignored."""
        tasks = [
            {"id": "a", "depends_on": ["nonexistent"]},
        ]
        layers = topo_sort_layers(tasks)
        assert len(layers) == 1

    def test_no_depends_on_key(self):
        tasks = [{"id": "a"}, {"id": "b"}]
        layers = topo_sort_layers(tasks)
        assert len(layers) == 1
        assert len(layers[0]) == 2


# ══════════════════════════════════════════════
# GPU assignment
# ══════════════════════════════════════════════

class TestAssignGpus:
    def test_basic_assignment(self):
        tasks = [{"id": "a"}, {"id": "b"}]
        result = assign_gpus(tasks, [0, 1, 2, 3], gpus_per_task=1)
        assert len(result) == 2
        assert result[0]["task_ids"] == ["a"]
        assert result[0]["gpu_ids"] == [0]
        assert result[1]["task_ids"] == ["b"]
        assert result[1]["gpu_ids"] == [1]

    def test_multi_gpu_per_task(self):
        tasks = [{"id": "a"}, {"id": "b"}]
        result = assign_gpus(tasks, [0, 1, 2, 3], gpus_per_task=2)
        assert len(result) == 2
        assert result[0]["gpu_ids"] == [0, 1]
        assert result[1]["gpu_ids"] == [2, 3]

    def test_more_tasks_than_gpus(self):
        tasks = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        result = assign_gpus(tasks, [0, 1], gpus_per_task=1)
        assert len(result) == 2  # only 2 GPUs available

    def test_insufficient_gpus(self):
        """When gpus_per_task > total GPUs, give all GPUs to first task."""
        tasks = [{"id": "a"}, {"id": "b"}]
        result = assign_gpus(tasks, [0], gpus_per_task=2)
        assert len(result) == 1
        assert result[0]["gpu_ids"] == [0]

    def test_empty_inputs(self):
        assert assign_gpus([], [0, 1]) == []
        assert assign_gpus([{"id": "a"}], []) == []


# ══════════════════════════════════════════════
# Batch scheduling (get_next_batch)
# ══════════════════════════════════════════════

class TestGetNextBatch:
    def test_no_task_plan(self, tmp_path):
        """No task_plan.json → returns None (fallback)."""
        result = get_next_batch(tmp_path, [0, 1])
        assert result is None

    def test_empty_tasks(self, tmp_path):
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        (plan_dir / "task_plan.json").write_text(json.dumps({"tasks": []}))
        result = get_next_batch(tmp_path, [0, 1])
        assert result is None

    def test_no_tasks_key(self, tmp_path):
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        (plan_dir / "task_plan.json").write_text(json.dumps({"description": "test"}))
        result = get_next_batch(tmp_path, [0, 1])
        assert result is None

    def test_first_batch(self, tmp_path):
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        tasks = [
            {"id": "a", "depends_on": []},
            {"id": "b", "depends_on": []},
            {"id": "c", "depends_on": ["a", "b"]},
        ]
        (plan_dir / "task_plan.json").write_text(json.dumps({"tasks": tasks}))

        result = get_next_batch(tmp_path, [0, 1, 2, 3])
        assert result is not None
        assert len(result) == 2  # a and b are ready
        ids = [r["task_ids"][0] for r in result]
        assert set(ids) == {"a", "b"}

    def test_second_batch_after_progress(self, tmp_path):
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        tasks = [
            {"id": "a", "depends_on": []},
            {"id": "b", "depends_on": []},
            {"id": "c", "depends_on": ["a", "b"]},
        ]
        (plan_dir / "task_plan.json").write_text(json.dumps({"tasks": tasks}))

        # Mark a and b complete
        exp_dir = tmp_path / "exp"
        exp_dir.mkdir()
        (exp_dir / "gpu_progress.json").write_text(json.dumps({
            "completed": ["a", "b"], "failed": []
        }))

        result = get_next_batch(tmp_path, [0, 1, 2, 3])
        assert result is not None
        assert len(result) == 1
        assert result[0]["task_ids"] == ["c"]

    def test_all_complete(self, tmp_path):
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        tasks = [{"id": "a", "depends_on": []}]
        (plan_dir / "task_plan.json").write_text(json.dumps({"tasks": tasks}))

        exp_dir = tmp_path / "exp"
        exp_dir.mkdir()
        (exp_dir / "gpu_progress.json").write_text(json.dumps({
            "completed": ["a"], "failed": []
        }))

        result = get_next_batch(tmp_path, [0, 1])
        assert result is None  # all done

    def test_blocked_tasks(self, tmp_path):
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        tasks = [
            {"id": "a", "depends_on": []},
            {"id": "b", "depends_on": ["a"]},
        ]
        (plan_dir / "task_plan.json").write_text(json.dumps({"tasks": tasks}))

        # a is not yet complete but not in remaining ready either
        # actually a IS ready (no deps), b is blocked on a
        # Let's make a different scenario: only b remains, a not done
        # Wait - if a is in the tasks list and not completed, it IS remaining
        # and it has no deps so it IS ready. For blocked, we need all remaining
        # to have unmet deps.
        # Simpler: make "a" completed but "b" depends on "a" AND "c" which is not done
        tasks2 = [
            {"id": "a", "depends_on": []},
            {"id": "c", "depends_on": []},
            {"id": "b", "depends_on": ["a", "c"]},
        ]
        (plan_dir / "task_plan.json").write_text(json.dumps({"tasks": tasks2}))
        exp_dir = tmp_path / "exp"
        exp_dir.mkdir(exist_ok=True)
        (exp_dir / "gpu_progress.json").write_text(json.dumps({
            "completed": ["a"], "failed": []
        }))

        result = get_next_batch(tmp_path, [0, 1])
        # c is ready (no deps, not completed), b is blocked on c
        assert result is not None
        assert len(result) == 1
        assert result[0]["task_ids"] == ["c"]

    def test_gpus_per_task(self, tmp_path):
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        tasks = [
            {"id": "a", "depends_on": []},
            {"id": "b", "depends_on": []},
        ]
        (plan_dir / "task_plan.json").write_text(json.dumps({"tasks": tasks}))

        result = get_next_batch(tmp_path, [0, 1, 2, 3], gpus_per_task=2)
        assert len(result) == 2
        assert result[0]["gpu_ids"] == [0, 1]
        assert result[1]["gpu_ids"] == [2, 3]

    def test_corrupt_json(self, tmp_path):
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        (plan_dir / "task_plan.json").write_text("not valid json {{{")
        result = get_next_batch(tmp_path, [0, 1])
        assert result is None
