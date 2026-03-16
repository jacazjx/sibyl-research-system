These protocols are mandatory for all experiment-executing agents (experimenter, server_experimenter).

### Remote File Isolation (CRITICAL)

1. All experiment files (code, logs, results) must reside in `{remote_base}/projects/{project}/`
2. Activate the environment using the `Remote env command` from Skill arguments (do not hardcode conda commands)
3. Shared resource workflow: check `{remote_base}/shared/registry.json` first — if found, create symlink; if not, download then register
4. Never access other projects' directories (`{remote_base}/projects/other_project/`)
5. Always `cd {remote_base}/projects/{project}` before any operation
6. Datasets intended for cross-project sharing go into `{remote_base}/shared/datasets/` — update `registry.json` after adding

### Orchestra Skill Auto-Trigger (CRITICAL)

If `Available Technical Skills` lists skills matching the current task, you MUST proactively invoke the 1-2 most relevant skills before implementation or restarting an experiment. Do not wait for user prompting.

Default trigger scenarios:
- Fine-tuning / LoRA / QLoRA / SFT → `peft`, `axolotl`, `llama-factory`, `unsloth`
- Multi-GPU / DDP / FSDP / ZeRO / throughput scaling → `accelerate`, `deepspeed`, `pytorch-fsdp2`, `megatron-core`, `ray-train`
- Inference throughput / serving / eval batch / benchmark → `vllm`, `sglang`, `tensorrt-llm`, `lm-evaluation-harness`, `nemo-evaluator`
- OOM / low VRAM utilization / small batch / long context → `flash-attention`, `bitsandbytes`, `awq`, `gptq`, `hqq`

After invoking a skill, you MUST materialize its recommendations into actual execution:
- Adjust batch size / eval batch / gradient accumulation / sequence length / dataloader prefetch
- Switch `multi_gpu_strategy`, enable DDP/DataParallel, or adopt a more suitable serving/evaluation framework as needed
- If skill recommendations conflict with current code, make targeted fixes before re-running — do not conservatively keep a low-utilization configuration

### Process Identification and Progress Reporting (CRITICAL)

Every training task MUST write a PID file at launch for system recovery detection:

```python
import os
from pathlib import Path

# Write immediately at training process start
pid_file = Path(results_dir) / f"{task_id}.pid"
pid_file.write_text(str(os.getpid()))
```

Training loops MUST write a progress file every epoch:

```python
import json
from datetime import datetime
from pathlib import Path

def report_progress(task_id, results_dir, epoch, total_epochs, step=0,
                    total_steps=0, loss=None, metric=None):
    """Write progress file for system monitor to track."""
    progress = Path(results_dir) / f"{task_id}_PROGRESS.json"
    progress.write_text(json.dumps({
        "task_id": task_id,
        "epoch": epoch, "total_epochs": total_epochs,
        "step": step, "total_steps": total_steps,
        "loss": loss, "metric": metric or {},
        "updated_at": datetime.now().isoformat(),
    }))
```

- PID file path: `{remote_base}/projects/{project}/exp/results/{task_id}.pid`
- Progress file path: `{remote_base}/projects/{project}/exp/results/{task_id}_PROGRESS.json`
- **Tasks without a PID file cannot be detected during system recovery**
- Progress file is overwritten each epoch (not appended); the monitor reads the latest state

### Completion Marker (CRITICAL)

Every task MUST write a DONE marker file upon completion, for the system monitor to detect:

```python
import json
from pathlib import Path

def mark_task_done(task_id, results_dir, status="success", summary=""):
    """Write DONE marker file for system monitor to detect."""
    # Clean up PID file
    pid_file = Path(results_dir) / f"{task_id}.pid"
    if pid_file.exists():
        pid_file.unlink()
    # Merge final progress if available
    progress_file = Path(results_dir) / f"{task_id}_PROGRESS.json"
    final_progress = {}
    if progress_file.exists():
        try:
            final_progress = json.loads(progress_file.read_text())
        except (json.JSONDecodeError, ValueError):
            pass
    # Write DONE marker
    marker = Path(results_dir) / f"{task_id}_DONE"
    marker.write_text(json.dumps({
        "task_id": task_id,
        "status": status,
        "summary": summary,
        "final_progress": final_progress,
        "timestamp": __import__("datetime").datetime.now().isoformat(),
    }))
```

- File path: `{remote_base}/projects/{project}/exp/results/{task_id}_DONE`
- Write for BOTH success and failure (differentiate via the `status` field)
- The system background monitor checks these files every 5 minutes
- **Tasks without a DONE file are treated as still running and may trigger timeout alerts**
- Upon task completion, the system auto-assigns freed GPUs to queued tasks (dynamic dispatch)

### VRAM Probing and Batch Size Optimization (CRITICAL)

**Before every training or inference task, run VRAM probing to determine the maximum batch size for the current GPU.**

### Probing procedure

Include this probing function in experiment scripts or as a standalone preprocessing step:

```python
def find_max_batch_size(model, sample_input_fn, device, start=128, min_bs=1):
    """Binary search for the maximum batch size the current GPU can sustain."""
    import torch, gc
    high, best = start, min_bs
    while min_bs <= high:
        mid = (min_bs + high) // 2
        try:
            torch.cuda.empty_cache(); gc.collect()
            batch = sample_input_fn(mid)
            batch = {k: v.to(device) for k, v in batch.items()}
            with torch.no_grad():
                model(**batch)
            best = mid
            min_bs = mid + 1
        except torch.cuda.OutOfMemoryError:
            high = mid - 1
            torch.cuda.empty_cache(); gc.collect()
    return best
```

### Usage rules
1. Probing is mandatory by default; skip only if the task explicitly requires a fixed batch size
2. Write probing results to `{workspace}/exp/results/{task_id}_gpu_profile.json`:
   ```json
   {"gpu_name": "RTX 4090", "vram_total_mb": 24564, "max_batch_size": 64,
    "vram_used_mb": 21200, "utilization_pct": 86.3}
   ```
3. Use the probed maximum stable batch size for training/inference, keeping only a small VRAM margin for random fluctuations
4. If VRAM utilization < 70%, keep increasing batch size, sequence length, generation batch, prefetch, gradient accumulation, or multi-GPU parallelism until near capacity
5. If the first formal run still OOMs, make a minimal fallback and retry immediately — do not over-reduce conservatively
6. For evaluation/inference benchmarks, also probe `eval_batch_size` or generation batch — do not default to single-sample serial execution

### Multi-GPU strategy
Based on the `multi_gpu_strategy` field in task_plan.json:
- `"single"`: Single GPU, set `CUDA_VISIBLE_DEVICES` to 1 GPU
- `"DataParallel"`: Wrap model with `torch.nn.DataParallel`, scale batch size linearly with GPU count
- `"DDP"`: Launch with `torchrun --nproc_per_node=N` for distributed training, independent batch size per GPU

### GPU Progress Tracking (CRITICAL)

After completing each assigned task, update `{workspace}/exp/gpu_progress.json`:
1. Read existing file (or create `{"completed": [], "failed": [], "running": {}, "timings": {}}`)
2. Append completed task IDs to `completed` array
3. Remove completed task IDs from `running` map (if present)
4. Append failed task IDs to `failed` array, also remove from `running`
5. Record timing for each task in `timings`:
   ```json
   "timings": {
     "task_1a": {
       "planned_min": 30,
       "actual_min": 22,
       "start_time": "2026-03-09T12:00:00",
       "end_time": "2026-03-09T12:22:00"
     }
   }
   ```
   - `planned_min`: from task_plan.json `estimated_minutes`
   - `actual_min`: wall-clock time from start to finish (rounded to integer)
   - Record timing even for failed tasks (helps calibrate future estimates)
6. Write back atomically (read → modify → write)

**Why timing matters**: The orchestrator uses actual/planned ratios from completed tasks to calibrate time estimates for future batches. Accurate timing data leads to better scheduling and more realistic progress reporting.

**Why removing from `running` matters**: The orchestrator uses the `running` map to track which GPUs are occupied. Removing a completed task from `running` frees its GPUs for dynamic dispatch of queued tasks.

7. Record experiment configuration summary in `config_snapshot`:
   ```json
   "timings": {
     "task_1a": {
       "planned_min": 30,
       "actual_min": 22,
       "start_time": "...", "end_time": "...",
       "config_snapshot": {
         "model": "bert-base-uncased",
         "batch_size": 64,
         "seq_len": 512,
         "dataset_size": 10000,
         "gpu_model": "RTX 4090",
         "gpu_count": 1
       }
     }
   }
   ```
   The orchestrator uses config snapshots to intelligently adjust time predictions when experiment configurations change between iterations. Record whatever config fields are relevant to execution time.
