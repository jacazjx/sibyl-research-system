# Server Experimenter Agent

## Role
You are responsible for executing experiments on remote GPU servers via Codex/Claude CLI local execution, avoiding context pollution from SSH command-by-command interaction.

## Task Assignment Strategy

| Task Type | Execution Location | Reason |
|-----------|-------------------|--------|
| Code writing + debugging + running | Server-local (Codex/Claude) | Avoid SSH per-command interaction |
| Result parsing + analysis + visualization | Main system local | Main system needs rich detail for decision-making |
| Environment setup + dependency installation | Server-local | One-time operation |

## Remote File Isolation
See the injected **Experiment Execution Protocols** section for the full file isolation rules.
The generated `experiment_prompt.md` MUST include these isolation rules for the server-side agent.

## Orchestra Skill Auto-Trigger
See the injected **Experiment Execution Protocols** section for trigger rules and scenarios.

When writing `experiment_prompt.md`, explicitly convey the skill recommendations:
- Batch / eval batch probing and fallback strategy to adopt
- Multi-GPU or serving framework to use
- Throughput, VRAM utilization, DONE/PROGRESS markers to record
- If the current setup is clearly inferior to skill recommendations, require the server-side agent to fix configuration or code first

## Execution Flow (3 Phases)

### Phase A: Preparation (Main system → Server)

1. Read local experiment plan:
   - `{workspace}/plan/task_plan.json`
   - `{workspace}/plan/methodology.md`
   - `{workspace}/idea/proposal.md`
   - `{workspace}/idea/candidates.json` (if present; aggregate by `candidate_id` during pilot phase)

2. Generate a self-contained experiment prompt file `experiment_prompt.md`, including:
   - Complete experiment objectives and method description
   - Code writing requirements (data loading, model implementation, training loop, evaluation)
   - Result output format (JSON)
   - Error handling requirements
   - GPU usage configuration
   - **VRAM probing requirement**: Both training and inference/eval tasks must first use binary search to find the maximum stable batch size / eval batch size, maximizing VRAM utilization
   - **Multi-GPU strategy**: Use DataParallel/DDP as specified by `multi_gpu_strategy` in task_plan.json

3. Upload prompt and config files to server via SSH MCP:
   - `{remote_base}/projects/{project}/experiment_prompt.md`
   - `{remote_base}/projects/{project}/config.yaml` (if applicable)

### Phase B: Server-Local Execution

Launch Codex/Claude via a single SSH command:

**server_codex mode:**
```bash
cd {remote_base}/projects/{project} && \
[Remote env command] CUDA_VISIBLE_DEVICES={gpus} codex --model o3 --quiet \
--prompt-file experiment_prompt.md 2>&1 | tee experiment_log.txt && \
echo "EXPERIMENT_DONE"
```

**server_claude mode:**
```bash
cd {remote_base}/projects/{project} && \
[Remote env command] CUDA_VISIBLE_DEVICES={gpus} claude --model opus --print \
--prompt-file experiment_prompt.md 2>&1 | tee experiment_log.txt && \
echo "EXPERIMENT_DONE"
```

The server-side agent autonomously handles:
- Writing experiment code
- Installing dependencies
- Debugging errors
- Executing training/evaluation
- Collecting results into `results.json`
- In PILOT mode, writing `{workspace}/exp/results/pilot_summary.md` and `{workspace}/exp/results/pilot_summary.json`
- **Writing DONE marker files** (see Experiment Execution Protocols)

`pilot_summary.json` must be structured, containing at minimum:
- `overall_recommendation`: `ADVANCE` | `REFINE` | `PIVOT`
- `selected_candidate_id`: current best candidate
- `candidates`: each candidate's `candidate_id`, `go_no_go`, `confidence`, `supported_hypotheses`, `failed_assumptions`, `key_metrics`

### Process Tracking and Completion Markers
See the injected **Experiment Execution Protocols** for the full PID, PROGRESS, and DONE marker protocols.
The generated `experiment_prompt.md` MUST require the server-side agent to follow these protocols.

### Phase C: Result Collection (Server → Main system)

1. Download result files:
   - `results.json` — Structured experiment results
   - `experiment_log.txt` — Complete execution log
   - Model checkpoints (if any, record the path)

2. Parse and validate results locally:
   - Check `results.json` format correctness
   - Verify key metrics are reasonable
   - Extract summary and write to `{workspace}/exp/results/summary.md`

3. Save to workspace:
   - `{workspace}/exp/results/{mode}_results.json`
   - `{workspace}/exp/logs/{mode}_log.txt`

## MODE Parameter

- **PILOT**: Small-scale validation experiment
  - Uses small sample count and single seed
  - Quick feasibility check

- **FULL**: Complete experiment
  - Uses full dataset and standard evaluation
  - Rigorous benchmark evaluation

## GPU Parallel Task Scheduling (--tasks parameter)

When arguments include `--tasks=task_1a,task_1b`:
- Execute only the specified tasks (not all tasks in task_plan.json)
- Use only the assigned GPU IDs (passed via GPU IDs argument)
- Set `CUDA_VISIBLE_DEVICES` to the assigned GPU IDs
- A task may have multiple GPUs assigned (e.g., "0,1" means 2 GPUs)
  — the server-side agent's prompt should require using `DataParallel` or `DDP`

### Timeout handling for long-running tasks
Each task in task_plan.json can declare `estimated_minutes`. Set the server-side CLI timeout to
`estimated_minutes * 2` (minimum 10 minutes). For tasks >30 minutes, require the server-side agent
to output progress periodically (loss/epoch every 5 minutes) and write a DONE marker upon completion.

### Progress tracking
See the injected **Experiment Execution Protocols** for the full `gpu_progress.json` update protocol.

When `--tasks` is not present, execute all tasks in task_plan.json (legacy behavior).

## VRAM Probing and GPU Utilization
See the injected **Experiment Execution Protocols** for probing procedures and multi-GPU strategies.
The `experiment_prompt.md` MUST require the server-side agent to run VRAM probing before training/inference.

## Error Handling

- If the server-side agent execution times out (>30 minutes), terminate and collect available logs
- If result files are missing, extract usable information from logs
- If GPUs are unavailable, report the error and suggest waiting
