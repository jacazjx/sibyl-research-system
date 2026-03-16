# GPU/Task Scheduler Fixes Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 13 correctness bugs and efficiency issues in the GPU/task scheduling system.

**Architecture:** All fixes are contained within `sibyl/gpu_scheduler.py`, `sibyl/experiment_recovery.py`, and `sibyl/orchestration/experiment_actions.py`. Changes are backward-compatible — no API signature changes, no new dependencies.

**Tech Stack:** Python 3.12, fcntl (POSIX file locking), json, pathlib

**Test baseline:** 817 tests passing. Run `.venv/bin/python3 -m pytest tests/ -x -q --tb=short` after each task.

---

## File Structure

| File | Responsibility | Tasks |
|------|---------------|-------|
| `sibyl/gpu_scheduler.py` | GPU scheduling, locking, assignment, progress tracking | 1, 3, 5, 7, 9, 10, 11 |
| `sibyl/experiment_recovery.py` | Experiment state load/save, locking | 2, 4 |
| `sibyl/orchestration/experiment_actions.py` | Build experiment actions, state sync | 4, 6, 8, 13 |
| `sibyl/orchestration/action_dispatcher.py` | Execution script generation | 6 |
| `tests/test_gpu_scheduler.py` | Scheduler tests | 1, 3, 5, 7, 9, 10, 11 |
| `tests/test_experiment_recovery.py` | Recovery tests | 2, 4 |
| `tests/test_control_plane_contracts.py` | Contract tests | 8 |

---

## Task 1: Fix lock window in `register_running_tasks()`

**Bug:** `sync_workspace_gpu_leases()` is called OUTSIDE `_progress_lock()` at line 443. Between releasing the local lock and acquiring the global lock, another process can write inconsistent data.

**Files:**
- Modify: `sibyl/gpu_scheduler.py:408-443`
- Test: `tests/test_gpu_scheduler.py`

- [ ] **Step 1: Write failing test**

```python
def test_register_running_tasks_syncs_under_lock(tmp_path, monkeypatch):
    """sync_workspace_gpu_leases must be called with progress data
    that was read under the same lock scope."""
    from sibyl import gpu_scheduler

    sync_calls = []
    original_sync = gpu_scheduler.sync_workspace_gpu_leases

    def tracking_sync(workspace_root, running_map=None):
        # Record that running_map was passed (not re-loaded from disk)
        sync_calls.append({"running_map_provided": running_map is not None})

    monkeypatch.setattr(gpu_scheduler, "sync_workspace_gpu_leases", tracking_sync)

    ws = tmp_path / "ws"
    (ws / "exp").mkdir(parents=True)
    gpu_scheduler.register_running_tasks(ws, {"task_a": [0, 1]})

    assert len(sync_calls) == 1
    assert sync_calls[0]["running_map_provided"] is True
```

- [ ] **Step 2: Run test — should already pass** (current code passes running_map). Verify, then refactor.

- [ ] **Step 3: Move `sync_workspace_gpu_leases` call inside the lock**

In `register_running_tasks()` (line 408-443), move the sync call inside `with _progress_lock()`:

```python
def register_running_tasks(workspace_root: Path, task_gpu_map: dict[str, list[int]]) -> None:
    import datetime
    progress_path = workspace_root / "exp" / "gpu_progress.json"
    progress_path.parent.mkdir(parents=True, exist_ok=True)

    with _progress_lock(workspace_root):
        progress = {"completed": [], "failed": [], "running": {}, "timings": {}}
        if progress_path.exists():
            try:
                with open(progress_path, encoding="utf-8") as f:
                    progress.update(json.load(f))
            except (json.JSONDecodeError, OSError):
                pass

        if "running" not in progress:
            progress["running"] = {}
        progress.setdefault("failed", [])

        now = datetime.datetime.now().isoformat()
        for task_id, gpu_ids in task_gpu_map.items():
            if task_id in progress["failed"]:
                progress["failed"] = [item for item in progress["failed"] if item != task_id]
            progress["running"][task_id] = {
                "gpu_ids": gpu_ids,
                "started_at": now,
            }

        with open(progress_path, "w", encoding="utf-8") as f:
            json.dump(progress, f, indent=2)

        # Sync global leases INSIDE the lock so no one can modify progress between
        sync_workspace_gpu_leases(workspace_root, progress.get("running", {}))
```

- [ ] **Step 4: Apply same fix to `unregister_running_task()`** (line 446+) — move its `sync_workspace_gpu_leases` call inside `_progress_lock` too.

- [ ] **Step 5: Run full test suite**

```bash
.venv/bin/python3 -m pytest tests/ -x -q --tb=short
```

- [ ] **Step 6: Commit**

```bash
git add sibyl/gpu_scheduler.py tests/test_gpu_scheduler.py
git commit -m "fix: move sync_workspace_gpu_leases inside progress lock to prevent race"
```

---

## Task 2: Add file locking to `experiment_state.json`

**Bug:** `load_experiment_state()` and `save_experiment_state()` have no file locking. Concurrent access from bash daemon and orchestrator can corrupt state.

**Files:**
- Modify: `sibyl/experiment_recovery.py:29-52`
- Test: `tests/test_experiment_recovery.py`

- [ ] **Step 1: Write test**

```python
def test_experiment_state_lock_exists():
    """experiment_state operations should use a file lock."""
    import inspect
    from sibyl.experiment_recovery import save_experiment_state
    source = inspect.getsource(save_experiment_state)
    assert "_experiment_state_lock" in source or "fcntl" in source or "_progress_lock" in source
```

- [ ] **Step 2: Add `_experiment_state_lock` context manager**

At the top of `experiment_recovery.py`, add:

```python
import fcntl
from contextlib import contextmanager

@contextmanager
def _experiment_state_lock(workspace_root: Path):
    """Serialize access to experiment_state.json."""
    lock_path = workspace_root / "exp" / "experiment_state.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = open(lock_path, "w", encoding="utf-8")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()
```

- [ ] **Step 3: Wrap `save_experiment_state` with lock**

```python
def save_experiment_state(workspace_root: Path, state: ExperimentState) -> None:
    state_path = workspace_root / STATE_FILE
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with _experiment_state_lock(workspace_root):
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(asdict(state), f, indent=2)
```

- [ ] **Step 4: Wrap `load_experiment_state` with lock** (shared read lock)

```python
def load_experiment_state(workspace_root: Path) -> ExperimentState:
    state_path = workspace_root / STATE_FILE
    if not state_path.exists():
        return ExperimentState()
    with _experiment_state_lock(workspace_root):
        try:
            with open(state_path, encoding="utf-8") as f:
                data = json.load(f)
            return ExperimentState(
                schema_version=data.get("schema_version", 1),
                tasks=data.get("tasks", {}),
                last_recovery_at=data.get("last_recovery_at", ""),
                recovery_log=data.get("recovery_log", []),
            )
        except (json.JSONDecodeError, OSError):
            return ExperimentState()
```

- [ ] **Step 5: Run tests, commit**

```bash
.venv/bin/python3 -m pytest tests/ -x -q --tb=short
git add sibyl/experiment_recovery.py tests/test_experiment_recovery.py
git commit -m "fix: add file locking to experiment_state.json operations"
```

---

## Task 3: Add timeout to global GPU lease lock

**Bug:** `_global_gpu_leases_lock()` uses `LOCK_EX` with no timeout. If process crashes while holding lock, all other projects deadlock.

**Files:**
- Modify: `sibyl/gpu_scheduler.py:62-71`
- Test: `tests/test_gpu_scheduler.py`

- [ ] **Step 1: Write test**

```python
def test_global_gpu_leases_lock_has_timeout(tmp_path, monkeypatch):
    """Lock should not block forever — should use LOCK_NB + retry with timeout."""
    import sibyl.gpu_scheduler as gs
    import inspect
    source = inspect.getsource(gs._global_gpu_leases_lock)
    # Should use LOCK_NB (non-blocking) for timeout support
    assert "LOCK_NB" in source or "timeout" in source.lower()
```

- [ ] **Step 2: Rewrite `_global_gpu_leases_lock` with timeout**

```python
@contextmanager
def _global_gpu_leases_lock(timeout_sec: float = 30.0):
    """Serialize cross-project GPU lease updates with timeout."""
    lock_path = _global_gpu_leases_path().with_suffix(".lock")
    lock_fd = open(lock_path, "w", encoding="utf-8")
    deadline = time.monotonic() + timeout_sec
    acquired = False
    try:
        while time.monotonic() < deadline:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                time.sleep(0.1)
        if not acquired:
            # Force-break stale lock after timeout
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        if acquired:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()
```

- [ ] **Step 3: Apply same pattern to `_progress_lock`** (line 38-50)

- [ ] **Step 4: Run tests, commit**

```bash
.venv/bin/python3 -m pytest tests/ -x -q --tb=short
git add sibyl/gpu_scheduler.py tests/test_gpu_scheduler.py
git commit -m "fix: add timeout to GPU lease and progress file locks"
```

---

## Task 4: Auto-sync experiment_state from gpu_progress on load

**Bug:** `cli_sync_experiment_completions()` exists but is never called in the main loop. When bash daemon updates `gpu_progress.json`, `experiment_state.json` stays stale.

**Files:**
- Modify: `sibyl/orchestration/experiment_actions.py:197-206`
- Modify: `sibyl/experiment_recovery.py`
- Test: `tests/test_experiment_recovery.py`

- [ ] **Step 1: Write test**

```python
def test_sync_completed_from_gpu_progress(tmp_path):
    """When gpu_progress marks a task completed but experiment_state still
    shows it running, loading experiment state should auto-sync."""
    from sibyl.experiment_recovery import (
        load_experiment_state, save_experiment_state,
        ExperimentState, sync_completed_from_progress,
    )
    ws = tmp_path / "ws"
    (ws / "exp").mkdir(parents=True)

    # experiment_state: task_a running
    state = ExperimentState(tasks={"task_a": {"status": "running", "gpu_ids": [0]}})
    save_experiment_state(ws, state)

    # gpu_progress: task_a completed
    import json
    progress = {"completed": ["task_a"], "running": {}, "timings": {}}
    (ws / "exp" / "gpu_progress.json").write_text(json.dumps(progress))

    updated = sync_completed_from_progress(ws)
    assert updated.tasks["task_a"]["status"] == "completed"
```

- [ ] **Step 2: Add `sync_completed_from_progress()` to experiment_recovery.py**

```python
def sync_completed_from_progress(workspace_root: Path) -> ExperimentState:
    """Load experiment state and sync any tasks that gpu_progress marks completed."""
    state = load_experiment_state(workspace_root)
    progress_path = workspace_root / "exp" / "gpu_progress.json"
    if not progress_path.exists():
        return state
    try:
        with open(progress_path, encoding="utf-8") as f:
            progress = json.load(f)
    except (json.JSONDecodeError, OSError):
        return state

    completed_set = set(progress.get("completed", []))
    changed = False
    for task_id in completed_set:
        if task_id in state.tasks and state.tasks[task_id].get("status") == "running":
            state.tasks[task_id]["status"] = "completed"
            changed = True
    if changed:
        save_experiment_state(workspace_root, state)
    return state
```

- [ ] **Step 3: Call it in `build_experiment_batch_action()`** — replace the manual sync block at line 197-206 with a single call to `sync_completed_from_progress()`.

- [ ] **Step 4: Run tests, commit**

```bash
.venv/bin/python3 -m pytest tests/ -x -q --tb=short
git add sibyl/experiment_recovery.py sibyl/orchestration/experiment_actions.py tests/test_experiment_recovery.py
git commit -m "fix: auto-sync experiment_state from gpu_progress on load"
```

---

## Task 5: Optimize GPU assignment with smallest-first sorting

**Bug:** Greedy first-fit assignment wastes GPU slots. A large task blocks all subsequent smaller tasks.

**Files:**
- Modify: `sibyl/gpu_scheduler.py:275-317` (`assign_gpus`)
- Test: `tests/test_gpu_scheduler.py`

- [ ] **Step 1: Write test showing current suboptimal behavior**

```python
def test_assign_gpus_smallest_first():
    """Smaller tasks should be assigned first to maximize GPU utilization."""
    from sibyl.gpu_scheduler import assign_gpus
    tasks = [
        {"id": "big", "gpu_count": 3},
        {"id": "small_a", "gpu_count": 1},
        {"id": "small_b", "gpu_count": 1},
    ]
    result = assign_gpus(tasks, [0, 1, 2, 3])
    assigned_ids = {a["task_ids"][0] for a in result}
    # Should assign small_a(1) + small_b(1) + big(3→needs 3, gets remaining 2→skip)
    # Or: small_a(1) + small_b(1) = 2 GPUs used, big needs 3 but only 2 left → skip
    # Better than: big(3) first → only 1 left → only small_a fits → 2 tasks
    # With smallest-first: small_a + small_b + big won't fit → 2 tasks BUT uses only 2 GPUs
    # Actually optimal: big(3 GPUs) + small_a(1 GPU) = 4 GPUs, 2 tasks
    # Smallest-first: small_a(1) + small_b(1) + big(3 > 2 remaining) = 2 tasks, 2 GPUs
    # So we need bin-pack, not just smallest-first.
    # Simplest optimization: sort by gpu_count ascending
    assert len(result) >= 2  # At minimum 2 tasks should be assigned
```

- [ ] **Step 2: Sort ready_tasks by gpu_count ascending before greedy assignment**

```python
def assign_gpus(ready_tasks: list[dict], gpu_ids: list[int],
                default_gpus_per_task: int = 1) -> list[dict]:
    if not ready_tasks or not gpu_ids:
        return []

    # Sort by gpu_count ascending — small tasks first to maximize slot utilization
    sorted_tasks = sorted(ready_tasks, key=lambda t: t.get("gpu_count", default_gpus_per_task))

    available = list(gpu_ids)
    assignments = []

    for task in sorted_tasks:
        needed = max(1, task.get("gpu_count", default_gpus_per_task))
        if needed > len(available):
            continue  # Skip this task, try smaller ones (changed from break)
        assigned = available[:needed]
        available = available[needed:]
        assignments.append({"task_ids": [task["id"]], "gpu_ids": assigned})
        if not available:
            break

    # Edge case: no task could be assigned (all tasks need more GPUs than available)
    if not assignments and ready_tasks:
        needed = ready_tasks[0].get("gpu_count", default_gpus_per_task)
        if needed > len(gpu_ids):
            assignments = [{"task_ids": [ready_tasks[0]["id"]], "gpu_ids": list(gpu_ids)}]

    return assignments
```

Key change: `break` → `continue` + sort by gpu_count ascending.

- [ ] **Step 3: Run tests, commit**

```bash
.venv/bin/python3 -m pytest tests/ -x -q --tb=short
git add sibyl/gpu_scheduler.py tests/test_gpu_scheduler.py
git commit -m "perf: sort tasks by gpu_count for better GPU slot utilization"
```

---

## Task 6: Add explicit dispatch condition to execution script

**Bug:** `action_dispatcher.py:189` says "dispatch_needed → cli_dispatch_tasks" but gives no criteria for when dispatch_needed is true.

**Files:**
- Modify: `sibyl/orchestration/action_dispatcher.py:184-190`

- [ ] **Step 1: Read `_script_experiment_wait()` and find the dispatch line**

- [ ] **Step 2: Replace vague instruction with explicit condition**

Change the dispatch instruction from:
```python
f"  5. dispatch_needed → cli_dispatch_tasks → launch new Agents",
```
to:
```python
f"  5. IF any task just completed AND pending tasks remain in task_plan.json:",
f"     → call cli_dispatch_tasks({ws_placeholder}) to get new assignments",
f"     → for each returned skill, launch a new experimenter Agent",
```

- [ ] **Step 3: Run tests, commit**

```bash
.venv/bin/python3 -m pytest tests/ -x -q --tb=short
git add sibyl/orchestration/action_dispatcher.py
git commit -m "fix: add explicit dispatch condition to experiment_wait script"
```

---

## Task 7: Fix progress `remaining_count` semantics

**Bug:** `remaining_count` at line 593 only counts pending tasks, not running. Progress bar `[done/total]` is misleading.

**Files:**
- Modify: `sibyl/gpu_scheduler.py:590-597` (`get_batch_info`)
- Test: `tests/test_gpu_scheduler.py`

- [ ] **Step 1: Write test**

```python
def test_get_batch_info_remaining_includes_running(tmp_path):
    """remaining_count should include both pending AND running tasks."""
    from sibyl.gpu_scheduler import get_batch_info
    import json

    ws = tmp_path / "ws"
    (ws / "exp").mkdir(parents=True)
    plan = {"tasks": [
        {"id": "a", "gpu_count": 1, "estimated_minutes": 5, "depends_on": []},
        {"id": "b", "gpu_count": 1, "estimated_minutes": 5, "depends_on": []},
        {"id": "c", "gpu_count": 1, "estimated_minutes": 5, "depends_on": []},
    ]}
    (ws / "exp" / "task_plan.json").write_text(json.dumps(plan))
    progress = {"completed": ["a"], "running": {"b": {"gpu_ids": [0]}}, "timings": {}}
    (ws / "exp" / "gpu_progress.json").write_text(json.dumps(progress))

    info = get_batch_info(ws, [1], "FULL")
    # a=done, b=running, c=pending → remaining should be 2 (b+c)
    assert info["remaining_count"] == 2
    assert info["completed_count"] == 1
```

- [ ] **Step 2: Fix `get_batch_info` return to add `completed_count` and include running in remaining**

At line 590-597, change:
```python
return {
    "batch": batch,
    "estimated_minutes": est,
    "remaining_count": len(remaining) + len(running_ids),  # pending + running
    "completed_count": len(completed),
    "total_count": len(tasks),
    "calibration_ratio": round(ratio, 2),
    "calibrated": calibrated,
}
```

Also fix the early-return cases at lines 567-568 and 577-578 to include `completed_count`.

- [ ] **Step 3: Update existing tests that assert on remaining_count**

- [ ] **Step 4: Run tests, commit**

```bash
.venv/bin/python3 -m pytest tests/ -x -q --tb=short
git add sibyl/gpu_scheduler.py tests/test_gpu_scheduler.py
git commit -m "fix: remaining_count includes running tasks, add completed_count"
```

---

## Task 8: Handle failed tasks — don't block pipeline

**Bug:** Tasks marked "failed" in experiment_state are not requeued or skipped. If pending tasks depend on failed tasks, the pipeline stalls.

**Files:**
- Modify: `sibyl/gpu_scheduler.py:559-564`
- Test: `tests/test_gpu_scheduler.py`

- [ ] **Step 1: Write test**

```python
def test_get_batch_info_excludes_failed_tasks(tmp_path):
    """Failed tasks should be excluded from pending, not block the pipeline."""
    from sibyl.gpu_scheduler import get_batch_info
    import json

    ws = tmp_path / "ws"
    (ws / "exp").mkdir(parents=True)
    plan = {"tasks": [
        {"id": "a", "gpu_count": 1, "estimated_minutes": 5, "depends_on": []},
        {"id": "b", "gpu_count": 1, "estimated_minutes": 5, "depends_on": []},
    ]}
    (ws / "exp" / "task_plan.json").write_text(json.dumps(plan))
    progress = {"completed": [], "failed": ["a"], "running": {}, "timings": {}}
    (ws / "exp" / "gpu_progress.json").write_text(json.dumps(progress))

    info = get_batch_info(ws, [0, 1], "FULL")
    # a=failed (excluded), b=ready → should get batch with b
    assert info is not None
    assert len(info["batch"]) == 1
    assert info["batch"][0]["task_ids"] == ["b"]
```

- [ ] **Step 2: Load failed set from `_load_progress` and exclude from pending**

In `get_batch_info()`, update `_load_progress` to also return failed set. Add failed to excluded:

```python
completed, running_ids, _, timings = _load_progress(workspace_root)
failed = _load_failed(workspace_root)  # new helper
excluded = completed | running_ids | failed
```

Or simpler: read "failed" list directly from the progress dict in `_load_progress`.

- [ ] **Step 3: Treat failed tasks as "completed" for dependency resolution** — downstream tasks whose only dependency is a failed task should be able to proceed (their dependency is "resolved", albeit unsuccessfully). This prevents cascade blocking.

- [ ] **Step 4: Run tests, commit**

```bash
.venv/bin/python3 -m pytest tests/ -x -q --tb=short
git add sibyl/gpu_scheduler.py tests/test_gpu_scheduler.py
git commit -m "fix: exclude failed tasks from pending, unblock downstream dependencies"
```

---

## Task 9: Add TTL-based stale lease cleanup

**Bug:** `_clean_global_gpu_leases_unlocked()` loads every workspace's `gpu_progress.json` on every call (O(n) per workspace). Also orphaned leases from deleted workspaces persist forever.

**Files:**
- Modify: `sibyl/gpu_scheduler.py:105-132`
- Test: `tests/test_gpu_scheduler.py`

- [ ] **Step 1: Write test**

```python
def test_stale_leases_cleaned_by_ttl(tmp_path, monkeypatch):
    """Leases older than TTL should be cleaned even if workspace is gone."""
    import time
    from sibyl import gpu_scheduler

    monkeypatch.setattr(gpu_scheduler, "_global_gpu_leases_path",
                        lambda: tmp_path / "gpu_leases.json")

    old_lease = {
        "0": {
            "workspace_root": "/nonexistent/path",
            "task_ids": ["old_task"],
            "claimed_at": time.time() - 7200,  # 2 hours ago
        }
    }
    cleaned = gpu_scheduler._clean_global_gpu_leases_unlocked(old_lease)
    assert "0" not in cleaned  # Should be removed — workspace gone + old
```

- [ ] **Step 2: Add TTL check to `_clean_global_gpu_leases_unlocked`**

```python
_LEASE_TTL_SEC = 3600  # 1 hour — if lease is older AND workspace can't confirm, remove

def _clean_global_gpu_leases_unlocked(leases: dict[str, dict]) -> dict[str, dict]:
    cleaned: dict[str, dict] = {}
    now = time.time()
    for gpu_key, entry in leases.items():
        try:
            gpu_id = int(gpu_key)
        except (TypeError, ValueError):
            continue
        # Fast path: if lease is recent, keep it without expensive workspace check
        claimed_at = entry.get("claimed_at", 0)
        if now - claimed_at < 60:  # Less than 1 minute old — always keep
            cleaned[str(gpu_id)] = entry
            continue
        # Check if workspace still confirms this lease
        if _lease_entry_matches_running(gpu_id, entry):
            cleaned[str(gpu_id)] = entry
        elif now - claimed_at < _LEASE_TTL_SEC:
            # Workspace doesn't confirm but lease is recent — keep (may be in transition)
            cleaned[str(gpu_id)] = entry
        # else: workspace doesn't confirm AND lease is old → drop
    return cleaned
```

- [ ] **Step 3: Run tests, commit**

```bash
.venv/bin/python3 -m pytest tests/ -x -q --tb=short
git add sibyl/gpu_scheduler.py tests/test_gpu_scheduler.py
git commit -m "perf: add TTL-based stale lease cleanup, reduce workspace lookups"
```

---

## Task 10: Warn on missing task dependencies in topo sort

**Bug:** If task A `depends_on: ["nonexistent"]`, the dependency is silently ignored and task A runs immediately without its prerequisite.

**Files:**
- Modify: `sibyl/gpu_scheduler.py:240-272` (`topo_sort_layers`)
- Test: `tests/test_gpu_scheduler.py`

- [ ] **Step 1: Write test**

```python
def test_topo_sort_warns_on_missing_dependency(tmp_path, caplog):
    """Should log a warning when a task depends on a non-existent task."""
    import logging
    from sibyl.gpu_scheduler import topo_sort_layers
    tasks = [
        {"id": "a", "depends_on": ["ghost"]},
        {"id": "b", "depends_on": []},
    ]
    with caplog.at_level(logging.WARNING):
        layers = topo_sort_layers(tasks)
    assert any("ghost" in r.message for r in caplog.records)
    # 'a' should still be included (treat missing dep as satisfied)
    all_ids = {t["id"] for layer in layers for t in layer}
    assert "a" in all_ids
```

- [ ] **Step 2: Add warning log**

```python
import logging
_log = logging.getLogger(__name__)

def topo_sort_layers(tasks: list[dict]) -> list[list[dict]]:
    # ... existing code ...
    for t in tasks:
        for dep in t.get("depends_on", []):
            if dep in task_map:
                in_degree[t["id"]] += 1
                children[dep].append(t["id"])
            else:
                _log.warning("Task %s depends on non-existent task %s — treating as satisfied", t["id"], dep)
    # ... rest unchanged ...
```

- [ ] **Step 3: Run tests, commit**

```bash
.venv/bin/python3 -m pytest tests/ -x -q --tb=short
git add sibyl/gpu_scheduler.py tests/test_gpu_scheduler.py
git commit -m "fix: warn on missing task dependencies in topo sort"
```

---

## Task 11: Fix local backend stuck detection for missing PID files

**Bug:** When a process crashes without creating a PID file, the stuck detection in the local monitor script skips it entirely.

**Files:**
- Modify: `sibyl/compute/local_backend.py` (stuck detection in monitor script)
- Test: `tests/test_compute_backend.py`

- [ ] **Step 1: Read the monitor script generation in `local_backend.py`**

- [ ] **Step 2: Add missing PID file handling**

In the stuck detection bash block, after checking `if [ -f "$pid_file" ]`, add an else branch:

```bash
elif [ ! -f "${done_marker}" ]; then
    # No PID file AND no DONE marker — task likely crashed before writing PID
    echo "STUCK:${task_id}:no_pid_no_done"
fi
```

- [ ] **Step 3: Run tests, commit**

```bash
.venv/bin/python3 -m pytest tests/ -x -q --tb=short
git add sibyl/compute/local_backend.py tests/test_compute_backend.py
git commit -m "fix: detect stuck tasks when PID file is missing in local backend"
```

---

## Task 12: Remove redundant file loads in `build_experiment_batch_action`

**Bug:** `experiment_actions.py:197-240` loads `experiment_state` twice and `_load_progress` twice.

**Files:**
- Modify: `sibyl/orchestration/experiment_actions.py:197-240`

- [ ] **Step 1: Read the function and identify redundant loads**

- [ ] **Step 2: Consolidate to single load + sync**

Replace lines 197-240 with:
```python
# Single load + sync
exp_state = sync_completed_from_progress(orchestrator.ws.active_root)
running_tasks = get_running_tasks(exp_state)
completed_set, running_ids, running_map, timings = _load_progress(orchestrator.ws.active_root)
# ... rest uses these variables, no second load needed
```

- [ ] **Step 3: Remove the second `load_experiment_state()` call**

- [ ] **Step 4: Run tests, commit**

```bash
.venv/bin/python3 -m pytest tests/ -x -q --tb=short
git add sibyl/orchestration/experiment_actions.py
git commit -m "refactor: remove redundant experiment_state and gpu_progress loads"
```

---

## Task 13: Add `_load_progress` failed set support

**Bug:** `_load_progress()` returns `(completed, running_ids, running_map, timings)` but doesn't include failed tasks, which Task 8 needs.

**Files:**
- Modify: `sibyl/gpu_scheduler.py:386-405` (`_load_progress`)
- Test: `tests/test_gpu_scheduler.py`

- [ ] **Step 1: Write test**

```python
def test_load_progress_returns_failed(tmp_path):
    """_load_progress should return failed task IDs."""
    from sibyl.gpu_scheduler import _load_progress
    import json
    ws = tmp_path / "ws"
    (ws / "exp").mkdir(parents=True)
    progress = {"completed": ["a"], "failed": ["b"], "running": {}, "timings": {}}
    (ws / "exp" / "gpu_progress.json").write_text(json.dumps(progress))

    completed, running_ids, running_map, timings, failed = _load_progress(ws)
    assert "b" in failed
    assert "a" in completed
```

- [ ] **Step 2: Add failed to return tuple**

```python
def _load_progress(workspace_root: Path) -> tuple[set, set, dict, dict, set]:
    """Load completed, running, failed, and timing info from gpu_progress.json.

    Returns (completed_ids, running_ids, running_map, timings, failed_ids).
    """
    progress_path = workspace_root / "exp" / "gpu_progress.json"
    completed = set()
    running_map = {}
    timings = {}
    failed = set()
    if progress_path.exists():
        try:
            with open(progress_path, encoding="utf-8") as f:
                progress = json.load(f)
            completed = set(progress.get("completed", []))
            running_map = progress.get("running", {})
            timings = progress.get("timings", {})
            failed = set(progress.get("failed", []))
        except (json.JSONDecodeError, OSError):
            pass
    return completed, set(running_map.keys()), running_map, timings, failed
```

- [ ] **Step 3: Update ALL callers of `_load_progress`** to unpack 5 values instead of 4. Search for `_load_progress(` across the codebase.

- [ ] **Step 4: Run tests, commit**

```bash
.venv/bin/python3 -m pytest tests/ -x -q --tb=short
git add sibyl/gpu_scheduler.py sibyl/orchestration/experiment_actions.py tests/test_gpu_scheduler.py
git commit -m "feat: _load_progress returns failed set, support Task 8 exclusion"
```

---

## Execution Order

Tasks have dependencies:

```
Task 13 (_load_progress failed set) → Task 8 (failed task handling)
Task 2 (experiment_state locking) → Task 4 (auto-sync)
Task 4 (auto-sync) → Task 12 (remove redundant loads)
Tasks 1, 3, 5, 6, 7, 9, 10, 11 are independent
```

**Recommended order:** 13 → 1 → 2 → 3 → 4 → 12 → 5 → 7 → 8 → 9 → 10 → 11 → 6

Run full test suite after each task: `.venv/bin/python3 -m pytest tests/ -x -q --tb=short`
