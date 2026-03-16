"""Local compute backend — run experiments directly on the local machine's GPUs."""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import TYPE_CHECKING

from sibyl.compute.base import ComputeBackend

if TYPE_CHECKING:
    from sibyl.config import Config


class LocalBackend(ComputeBackend):
    """Execute experiments on local GPUs without SSH."""

    def __init__(self, workspace_active_root: str, config: "Config") -> None:
        self._active_root = workspace_active_root
        self._config = config

    @property
    def backend_type(self) -> str:
        return "local"

    def project_dir(self, ws_name: str) -> str:
        return self._active_root

    def env_cmd(self, project_name: str) -> str:
        return self._config.get_local_env_cmd(project_name)

    def gpu_poll_script(
        self,
        candidate_gpu_ids: list[int],
        threshold_mb: int,
        poll_interval_sec: int,
        max_polls: int,
        marker_file: str,
        aggressive_mode: bool,
        aggressive_threshold_pct: int,
    ) -> str:
        return _local_gpu_poll_script(
            candidate_gpu_ids=candidate_gpu_ids,
            threshold_mb=threshold_mb,
            poll_interval_sec=poll_interval_sec,
            max_polls=max_polls,
            marker_file=marker_file,
            aggressive_mode=aggressive_mode,
            aggressive_threshold_pct=aggressive_threshold_pct,
        )

    def experiment_monitor_script(
        self,
        project_dir: str,
        task_ids: list[str],
        poll_interval_sec: int,
        timeout_minutes: int,
        marker_file: str,
        workspace_path: str,
        heartbeat_polls: int,
        task_gpu_map: dict[str, list[int]] | None,
    ) -> str:
        return _local_experiment_monitor_script(
            project_dir=project_dir,
            task_ids=task_ids,
            poll_interval_sec=poll_interval_sec,
            timeout_minutes=timeout_minutes,
            marker_file=marker_file,
            workspace_path=workspace_path,
            heartbeat_polls=heartbeat_polls,
            task_gpu_map=task_gpu_map,
        )

    @classmethod
    def from_config(cls, config: "Config", workspace_active_root: str = "") -> "LocalBackend":
        return cls(workspace_active_root=workspace_active_root, config=config)


# ---------------------------------------------------------------------------
# Local script generators
# ---------------------------------------------------------------------------


def _local_gpu_poll_script(
    candidate_gpu_ids: list[int],
    threshold_mb: int = 2000,
    poll_interval_sec: int = 600,
    max_polls: int = 0,
    marker_file: str = "/tmp/sibyl_gpu_free.json",
    aggressive_mode: bool = False,
    aggressive_threshold_pct: int = 25,
) -> str:
    """Generate a bash script that polls local nvidia-smi for free GPUs.

    Identical to the SSH variant in ``gpu_scheduler.gpu_poll_wait_script``
    except ``nvidia-smi`` runs locally instead of over SSH.
    """
    gpu_ids_str = ",".join(str(g) for g in candidate_gpu_ids)
    limit_label = f"max {max_polls}" if max_polls > 0 else "unlimited"

    if max_polls > 0:
        loop_header = f"for i in $(seq 1 {max_polls}); do"
        loop_footer = f"""done

echo "Timeout after {max_polls} polls ({max_polls * poll_interval_sec}s)"
exit 1"""
    else:
        loop_header = "i=0\nwhile true; do\n    i=$((i + 1))"
        loop_footer = "done"

    if aggressive_mode:
        smi_fields = "index,memory.used,memory.total"
        aggressive_check = f"""
        # Aggressive mode: also claim GPUs with <{aggressive_threshold_pct}% VRAM usage
        if [ -n "$total" ] && [ "$total" -gt 0 ] 2>/dev/null; then
            pct=$(( mem * 100 / total ))
            if [ "$pct" -lt {aggressive_threshold_pct} ] 2>/dev/null; then
                if [ -z "$FREE_GPUS" ]; then
                    FREE_GPUS="$idx"
                else
                    FREE_GPUS="$FREE_GPUS,$idx"
                fi
            fi
        fi"""
        read_line = "while IFS=',' read -r idx mem total; do"
        clean_vars = """        idx=$(echo "$idx" | tr -d ' ')
        mem=$(echo "$mem" | tr -d ' ')
        total=$(echo "$total" | tr -d ' ')"""
        mode_label = f"aggressive (<{aggressive_threshold_pct}% VRAM)"
    else:
        smi_fields = "index,memory.used"
        aggressive_check = ""
        read_line = "while IFS=',' read -r idx mem; do"
        clean_vars = """        idx=$(echo "$idx" | tr -d ' ')
        mem=$(echo "$mem" | tr -d ' ')"""
        mode_label = "normal"

    return f'''#!/bin/bash
# Sibyl GPU poll: wait for free GPUs (LOCAL)
# Candidates: [{gpu_ids_str}], threshold: {threshold_mb}MB, mode: {mode_label}
# Poll every {poll_interval_sec}s, {limit_label} attempts

MARKER="{marker_file}"
rm -f "$MARKER"

{loop_header}
    OUTPUT=$(nvidia-smi --query-gpu={smi_fields} --format=csv,noheader,nounits 2>/dev/null)
    if [ $? -ne 0 ]; then
        echo "[poll $i] nvidia-smi failed, retrying in {poll_interval_sec}s..."
        sleep {poll_interval_sec}
        continue
    fi

    # Parse free GPUs
    FREE_GPUS=""
    {read_line}
{clean_vars}
        # Check if this GPU is in our candidate list
        case ",{gpu_ids_str}," in
            *",$idx,"*)
                if [ "$mem" -lt {threshold_mb} ] 2>/dev/null; then
                    if [ -z "$FREE_GPUS" ]; then
                        FREE_GPUS="$idx"
                    else
                        FREE_GPUS="$FREE_GPUS,$idx"
                    fi
                fi{aggressive_check}
                ;;
        esac
    done <<< "$OUTPUT"

    if [ -n "$FREE_GPUS" ]; then
        echo "[poll $i] Found free GPUs: $FREE_GPUS"
        echo "{{\\"free_gpus\\": [$FREE_GPUS], \\"poll_count\\": $i}}" > "$MARKER"
        exit 0
    fi

    echo "[poll $i] No free GPUs (all above {threshold_mb}MB), waiting {poll_interval_sec}s..."
    sleep {poll_interval_sec}
{loop_footer}
'''


def _local_experiment_monitor_script(
    project_dir: str,
    task_ids: list[str],
    poll_interval_sec: int = 300,
    timeout_minutes: int = 0,
    marker_file: str = "/tmp/sibyl_exp_monitor.json",
    workspace_path: str = "",
    heartbeat_polls: int = 3,
    task_gpu_map: dict[str, list[int]] | None = None,
) -> str:
    """Generate a bash daemon that monitors experiments on the local machine.

    Structurally identical to the SSH variant in ``gpu_scheduler``
    except all file checks and nvidia-smi calls run locally.
    """
    task_ids_str = " ".join(task_ids)
    task_count = len(task_ids)

    if timeout_minutes > 0:
        timeout_sec = timeout_minutes * 60
        timeout_check = f"""
    elapsed=$(( $(date +%s) - start_time ))
    if [ "$elapsed" -gt {timeout_sec} ]; then
        echo "[monitor] Timeout after {timeout_minutes}min"
        echo '{{"status": "timeout", "completed": ['$COMPLETED_JSON'], "pending": ['$PENDING_JSON'], "elapsed_sec": '$elapsed'}}' > "$MARKER"
        exit 1
    fi"""
    else:
        timeout_check = ""

    gpu_refresh_block = ""
    dispatch_block = ""
    wake_queue_block = ""
    stuck_detection_block = ""
    final_sync_block = ""

    if workspace_path:
        from sibyl._paths import REPO_ROOT

        repo_root = str(REPO_ROOT)
        python_exe = f"{repo_root}/.venv/bin/python3"

        wake_queue = f"{workspace_path}/exp/experiment_supervisor_main_wake.jsonl"
        wake_queue_alt = f"{workspace_path}/current/exp/experiment_supervisor_main_wake.jsonl"

        wake_queue_block = f'''
# Helper: enqueue a wake event for the main system
_enqueue_wake() {{
    local kind="$1" summary="$2" urgency="${{3:-high}}" requires_main="${{4:-false}}"
    local ts=$(date +%s%3N)
    local queue="{wake_queue}"
    [ -f "{wake_queue_alt}" ] && queue="{wake_queue_alt}"
    mkdir -p "$(dirname "$queue")"
    printf '%s\\n' "{{\\"event_id\\":\\"wake-${{ts}}-monitor\\",\\"owner_id\\":\\"monitor_daemon_$$\\",\\"kind\\":\\"$kind\\",\\"summary\\":\\"$summary\\",\\"urgency\\":\\"$urgency\\",\\"requires_main_system\\":$requires_main,\\"created_at\\":$ts}}" \\
        >> "$queue"
}}
'''
        _task_gpu_json = json.dumps(task_gpu_map or {})
        heartbeat_interval = heartbeat_polls

        # GPU refresh: nvidia-smi runs locally (no SSH)
        gpu_refresh_block = f'''
    # ── GPU State Refresh (local nvidia-smi) ──
    GPU_OUTPUT=$(nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits 2>/dev/null)
    if [ $? -eq 0 ] && [ -n "$GPU_OUTPUT" ]; then
        cd "{repo_root}" && "{python_exe}" -m sibyl.cli record-gpu-poll \\
            "{workspace_path}" --nvidia-smi-output "$GPU_OUTPUT" \\
            --source "monitor_daemon" > /dev/null 2>&1

        # ── GPU Efficiency Digest (every {heartbeat_interval} polls) ──
        if [ $((i % {heartbeat_interval})) -eq 0 ]; then
            DIGEST=$("{python_exe}" -c "
import json, sys
from sibyl.experiment_digest import analyze_gpu_efficiency, format_digest_for_llm, build_digest
gpu_out = sys.argv[1]
task_gpus = json.loads(sys.argv[2])
progress = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {{}}
analysis = analyze_gpu_efficiency(gpu_out, running_task_gpus=task_gpus)
digest = build_digest(analysis, [], analysis.get('recommendations', []), task_progress=progress, elapsed_min=int(sys.argv[4]) if len(sys.argv) > 4 else 0)
print(json.dumps(digest))
" "$GPU_OUTPUT" {shlex.quote(_task_gpu_json)} "${{PROGRESS_JSON:-{{}}}}" "$(((${{elapsed:-0}}) / 60))" 2>/dev/null)

            if [ -n "$DIGEST" ]; then
                FREE_COUNT=$(echo "$DIGEST" | "{python_exe}" -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('gpu_analysis',{{}}).get('free_gpus',[])))" 2>/dev/null || echo "0")
                if [ "$FREE_COUNT" -gt 0 ] && [ "$DISPATCH" != "true" ]; then
                    DISPATCH_RESULT=$(cd "{repo_root}" && "{python_exe}" -m sibyl.cli dispatch "{workspace_path}" 2>/dev/null)
                    PROACTIVE_COUNT=$(echo "$DISPATCH_RESULT" | "{python_exe}" -c \\
                        "import json,sys; d=json.load(sys.stdin); print(len(d.get('dispatch',[])))" 2>/dev/null || echo "0")
                    if [ "$PROACTIVE_COUNT" -gt 0 ]; then
                        _enqueue_wake "dispatch_ready" "$PROACTIVE_COUNT tasks dispatched to free GPUs" "high" "true"
                    fi
                fi

                UNDERUTIL_COUNT=$(echo "$DIGEST" | "{python_exe}" -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('gpu_analysis',{{}}).get('underutilized',[])))" 2>/dev/null || echo "0")
                if [ "$UNDERUTIL_COUNT" -gt 0 ]; then
                    _enqueue_wake "gpu_underutilized" "$UNDERUTIL_COUNT GPUs underutilized" "medium" "false"
                fi

                _enqueue_wake "periodic_review" "Digest available" "low" "false"
            fi
        fi
    fi

    # ── Append to monitor history ──
    echo "{{\\"ts\\": $(date +%s), \\"poll\\": $i, \\"done_count\\": $done_count, \\"total\\": $TOTAL}}" >> "{workspace_path}/exp/monitor_history.jsonl" 2>/dev/null
'''

        dispatch_block = f'''
    # ── Dynamic Dispatch (when new tasks completed) ──
    if [ "$DISPATCH" = "true" ]; then
        if [ -n "$COMPLETED_JSON" ]; then
            cd "{repo_root}" && "{python_exe}" -m sibyl.cli sync-experiment-completions \\
                "{workspace_path}" --completed-json "[$COMPLETED_JSON]" > /dev/null 2>&1
        fi
        DISPATCH_RESULT=$(cd "{repo_root}" && "{python_exe}" -m sibyl.cli dispatch "{workspace_path}" 2>/dev/null)
        DISPATCH_COUNT=$(echo "$DISPATCH_RESULT" | "{python_exe}" -c \\
            "import json,sys; d=json.load(sys.stdin); print(len(d.get('dispatch',[])))" 2>/dev/null || echo "0")
        if [ "$DISPATCH_COUNT" -gt 0 ]; then
            _enqueue_wake "dispatch_ready" "$DISPATCH_COUNT new tasks dispatched" "high" "true"
        fi
    fi
'''

        final_sync_block = f'''
        # Final sync: mark all tasks completed in experiment_state.json
        if [ -n "$COMPLETED_JSON" ]; then
            cd "{repo_root}" && "{python_exe}" -m sibyl.cli sync-experiment-completions \\
                "{workspace_path}" --completed-json "[$COMPLETED_JSON]" > /dev/null 2>&1
        fi'''

        # Stuck detection: check local PIDs directly (no SSH)
        stuck_detection_block = f'''
    # ── Stuck Process Detection (local) ──
    STUCK_TASKS=""
    for task_id in "${{ALL_TASKS[@]}}"; do
        echo ",$COMPLETED," | grep -q ",$task_id," && continue
        pid_file="{project_dir}/exp/results/${{task_id}}.pid"
        if [ -f "$pid_file" ]; then
            pid=$(cat "$pid_file" 2>/dev/null)
            if [ -n "$pid" ]; then
                if ! kill -0 "$pid" 2>/dev/null; then
                    if [ -z "$STUCK_TASKS" ]; then
                        STUCK_TASKS="$task_id"
                    else
                        STUCK_TASKS="$STUCK_TASKS,$task_id"
                    fi
                fi
            fi
        elif [ ! -f "{project_dir}/exp/results/${{task_id}}_DONE" ]; then
            # No PID file AND no DONE marker — task likely crashed before writing PID
            if [ -z "$STUCK_TASKS" ]; then
                STUCK_TASKS="$task_id"
            else
                STUCK_TASKS="$STUCK_TASKS,$task_id"
            fi
        fi
    done
    if [ -n "$STUCK_TASKS" ]; then
        _enqueue_wake "task_died" "Process dead without DONE marker: $STUCK_TASKS" "high" "true"
    fi
'''

    # Main script body — local file checks instead of SSH
    return f'''#!/bin/bash
# Sibyl Experiment Monitor Daemon (LOCAL)
# Tasks: {task_ids_str}
# Poll every {poll_interval_sec}s, timeout: {"unlimited" if timeout_minutes == 0 else f"{timeout_minutes}min"}
# Zero LLM tokens consumed.

MARKER="{marker_file}"
PROJECT_DIR="{project_dir}"
ALL_TASKS=({task_ids_str})
TOTAL={task_count}
start_time=$(date +%s)
PREV_DONE_COUNT=0
{wake_queue_block}
echo '{{"status": "monitoring", "total": {task_count}, "completed": [], "pending": {json.dumps(task_ids)}, "dispatch_needed": false}}' > "$MARKER"

i=0
while true; do
    i=$((i + 1))
    COMPLETED=""
    COMPLETED_JSON=""
    PENDING=""
    PENDING_JSON=""
    done_count=0

    # ── Local DONE check ──
    for t in {task_ids_str}; do
        if [ -f "$PROJECT_DIR/exp/results/${{t}}_DONE" ]; then
            done_count=$((done_count + 1))
            if [ -z "$COMPLETED" ]; then
                COMPLETED="$t"
                COMPLETED_JSON="\\"$t\\""
            else
                COMPLETED="$COMPLETED,$t"
                COMPLETED_JSON="$COMPLETED_JSON, \\"$t\\""
            fi
        else
            if [ -z "$PENDING" ]; then
                PENDING="$t"
                PENDING_JSON="\\"$t\\""
            else
                PENDING="$PENDING $t"
                PENDING_JSON="$PENDING_JSON, \\"$t\\""
            fi
        fi
    done

    # Detect newly completed tasks
    DISPATCH="false"
    if [ "$done_count" -gt "$PREV_DONE_COUNT" ]; then
        DISPATCH="true"
    fi
    PREV_DONE_COUNT=$done_count

    # ── Collect PROGRESS snapshots (local) ──
    PROGRESS_JSON=""
    if [ -n "$PENDING" ]; then
        for t in $PENDING; do
            prog=$(cat "$PROJECT_DIR/exp/results/${{t}}_PROGRESS.json" 2>/dev/null)
            if [ -n "$prog" ]; then
                entry="\\"$t\\": $prog"
                if [ -z "$PROGRESS_JSON" ]; then
                    PROGRESS_JSON="$entry"
                else
                    PROGRESS_JSON="$PROGRESS_JSON, $entry"
                fi
            fi
        done
    fi

    elapsed=$(( $(date +%s) - start_time ))
    echo "[monitor $i] $done_count/$TOTAL done (elapsed: ${{elapsed}}s)"
{gpu_refresh_block}{dispatch_block}{stuck_detection_block}
    # ── Write marker file ──
    if [ "$done_count" -eq "$TOTAL" ]; then{final_sync_block}
        echo '{{"status": "all_complete", "completed": ['$COMPLETED_JSON'], "pending": [], "dispatch_needed": false, "progress": {{'$PROGRESS_JSON'}}, "elapsed_sec": '$elapsed', "poll_count": '$i'}}' > "$MARKER"
        echo "[monitor] All {task_count} tasks complete!"
        [ -n "$(type -t _enqueue_wake 2>/dev/null)" ] && _enqueue_wake "all_complete" "All {task_count} tasks finished" "high" "true"
        exit 0
    fi

    echo '{{"status": "monitoring", "completed": ['$COMPLETED_JSON'], "pending": ['$PENDING_JSON'], "dispatch_needed": '$DISPATCH', "progress": {{'$PROGRESS_JSON'}}, "elapsed_sec": '$elapsed', "poll_count": '$i'}}' > "$MARKER"
{timeout_check}
    sleep {poll_interval_sec}
done
'''
