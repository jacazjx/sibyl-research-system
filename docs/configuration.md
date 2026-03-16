# Configuration Reference

> Source of truth: `sibyl/config.py` — `Config` dataclass

## Config Loading Order

Sibyl loads configuration in layers, with later layers overriding earlier ones:

1. **Code defaults** — Built-in defaults from `Config` dataclass (`language: "zh"`, etc.)
2. **Root `config.yaml`** — Optional file at the project root directory. Use this for machine-level defaults shared across all research projects (e.g., `language: zh`, `ssh_server`). This file is in `.gitignore` and not committed.
3. **Project `config.yaml`** — Per-project overrides at `workspaces/<project>/config.yaml`. Settings here take priority over root config.

```
Code defaults  <--  config.yaml (root)  <--  workspaces/<project>/config.yaml
```

**Example root config** (for setting local defaults):

```yaml
# config.yaml (project root, git-ignored)
language: zh
ssh_server: default
remote_base: /home/user/sibyl_system
```

**Example project config** (for project-specific overrides):

```yaml
# workspaces/my-project/config.yaml
gpu_aggressive_mode: true
iteration_dirs: true
remote_conda_path: /home/user/miniforge3/bin/conda
```

## Example

See [config.example.yaml](../config.example.yaml) for a minimal example.

## Compute Backend

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `compute_backend` | string | `"local"` | Where to run experiments: `local` (local GPUs) or `ssh` (remote server) |
| `max_gpus` | int | `4` | Maximum GPUs to use (picks any free ones dynamically) |
| `gpus_per_task` | int | `1` | GPUs allocated per experiment task |

### Local GPU (`compute_backend: local`)

Run experiments directly on the local machine's GPUs. This is the default.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `local_env_type` | string | `"conda"` | Python environment type: `conda` \| `venv` |
| `local_conda_path` | string | `""` | Custom conda path (empty = system `conda`) |
| `local_conda_env_name` | string | `""` | Conda env name (empty = auto `sibyl_<project>`) |

```yaml
compute_backend: local
local_env_type: conda
local_conda_env_name: my_ml_env  # reuse an existing conda env
```

### Remote GPU (`compute_backend: ssh`)

Run experiments on a remote GPU server via SSH MCP.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `ssh_server` | string | `"default"` | SSH MCP connection name used for remote execution |
| `remote_base` | string | `"/home/user/sibyl_system"` | Base directory on remote server |

`ssh_server` depends on how your SSH MCP server is configured:
- Use `default` when `ssh-mcp-server` is launched with explicit `--host/--port/--username` arguments.
- Use a named host such as `my-gpu-box` only when your MCP setup resolves that connection name via your SSH configuration.

```yaml
compute_backend: ssh
ssh_server: my-gpu-box
remote_base: /data/sibyl
```

### Adding New Backends

The backend system is pluggable. To add a new backend (e.g., SLURM, Kubernetes):

1. Create `sibyl/compute/<backend>_backend.py` implementing `ComputeBackend` ABC
2. Register it in `sibyl/compute/registry.py`
3. Add the backend name to `valid_compute_backends` in `sibyl/config.py`

## GPU Polling (Shared Servers)

For shared GPU servers where other users may be running jobs.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `gpu_poll_enabled` | bool | `true` | Enable GPU availability polling before experiments |
| `gpu_free_threshold_mb` | int | `2000` | GPU memory threshold (MB) — below this = "free" |
| `gpu_poll_interval_sec` | int | `600` | Seconds between polls (default 10 min) |
| `gpu_poll_max_attempts` | int | `0` | Max poll attempts; `0` = infinite (wait forever) |

## GPU Aggressive Mode

Treat GPUs with low VRAM usage as available, even if allocated.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `gpu_aggressive_mode` | bool | `true` | Enable aggressive GPU detection |
| `gpu_aggressive_threshold_pct` | int | `25` | VRAM usage % below which GPU is treated as available |

## Pilot Experiments

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `pilot_samples` | int | `100` | Number of samples for pilot validation |
| `pilot_timeout` | int | `600` | Pilot experiment timeout in seconds |
| `pilot_seeds` | list[int] | `[42]` | Random seeds for pilot runs |

## Full Experiments

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `full_seeds` | list[int] | `[42, 123, 456]` | Random seeds for full experiment runs |

## Research Focus

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `research_focus` | int | `3` | Controls how readily the system pivots vs persists (1–5) |

How focused the system stays on a given research direction across iterations:

| Level | Name | Behavior |
|-------|------|----------|
| 1 | `explore` | Pivot early at modest negative signals. Broad candidate pool (3-4 ideas). |
| 2 | `open` | Lean toward pivoting when results are below baseline. Pool: 2-3 ideas. |
| 3 | `balanced` | Default (current behavior). Fair evidence-based decisions. Pool: 2-3 ideas. |
| 4 | `focused` | Persist longer; only pivot when core hypotheses are clearly refuted. Pool: 1-2 ideas. |
| 5 | `deep_focus` | Exhaust optimization before pivoting. Focus on 1 front-runner. |

This parameter influences three decision points:
- **Supervisor decision** (`experiment_decision`): PIVOT vs PROCEED threshold
- **Idea validation** (`idea_validation_decision`): ADVANCE / REFINE / PIVOT tendency
- **Synthesizer** (`idea_debate`): Candidate pool size and convergence strategy

Hard limits (`idea_exp_cycles`, `idea_validation_rounds`) are not affected — `research_focus` biases decisions within those limits.

```yaml
# Deep investigation of a promising idea
research_focus: 5

# Rapid exploration of many ideas
research_focus: 1
```

## Pipeline Control

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_parallel_tasks` | int | `4` | Maximum parallel experiment tasks |
| `experiment_timeout` | int | `300` | Experiment timeout in seconds |
| `review_enabled` | bool | `true` | Enable the `review` stage after `writing_latex`; when `false`, pipeline jumps directly to `reflection` |
| `idea_exp_cycles` | int | `6` | Maximum PIVOT count before forcing PROCEED |
| `idea_validation_rounds` | int | `4` | Maximum pilot-guided idea refinement rounds before full experiments |
| `max_iterations` | int | `10` | Default end-to-end project iteration budget used by the quality gate |
| `max_iterations_cap` | int | `100` | Upper bound for `reflection/action_plan.json` → `suggested_max_iterations`; set `0` to remove the cap |
| `debate_rounds` | int | `2` | Number of rounds in multi-agent debates |
| `writing_revision_rounds` | int | `2` | Maximum writing revision rounds after final review |

## Language

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `language` | string | `"zh"` | 控制面与非论文类产物语言：`en` (English) 或 `zh` (Chinese) |

Controls the language for:
- **Console output**: Status messages, progress logs, skill invocation summaries
- **Non-paper research artifacts**: Proposals, experiment reports, research diary, reflection notes, intermediate analysis
- **Log files**: Stage summaries, error messages, status updates

**Always in English regardless of this setting**:
- Code and code comments
- JSON keys
- References and citations
- Paper-writing artifacts: `writing/outline.md`, `writing/sections/*`, `writing/critique/*`, `writing/paper.md`, `writing/review.md`
- LaTeX sources

```yaml
# Chinese (default)
language: zh

# English
language: en
```

## Writing Mode

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `writing_mode` | string | `"parallel"` | Writing strategy: `sequential` \| `parallel` \| `codex` |
| `codex_writing_model` | string | `""` | Optional model override passed only to `sibyl-codex-writer` (empty = use Codex MCP default) |

- **`sequential`**: Single agent writes all sections in order. Best consistency.
- **`parallel`**: 6 agents write sections simultaneously. Faster, but may have style inconsistencies.
- **`codex`**: GPT-5.4 writes the paper. Requires `codex_enabled: true`; otherwise Sibyl falls back to `parallel`.

## Experiment Execution

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `experiment_mode` | string | `"ssh_mcp"` | Execution mode: `ssh_mcp` \| `server_codex` \| `server_claude` |
| `server_codex_path` | string | `"codex"` | Codex CLI path on remote server |
| `server_claude_path` | string | `"claude"` | Claude CLI path on remote server |

- **`ssh_mcp`**: Execute commands interactively via SSH MCP (default, recommended).
- **`server_codex`**: Upload experiment prompt, launch Codex CLI on server to execute locally.
- **`server_claude`**: Upload experiment prompt, launch Claude CLI on server to execute locally.

## Remote Environment (SSH Backend)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `remote_env_type` | string | `"conda"` | Python environment type on server: `conda` \| `venv` |
| `remote_conda_path` | string | `""` | Custom conda path (empty = auto `{remote_base}/miniconda3/bin/conda`) |
| `remote_conda_env_name` | string | `""` | Optional conda env override; empty = auto `sibyl_<project>`, set e.g. `base` to reuse an existing env |
| `iteration_dirs` | bool | `false` | Enable iteration subdirectory mode (`iter_NNN/` + `current` symlink) |

## Codex Integration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `codex_enabled` | bool | `false` | Enable GPT-5.4 independent cross-review after Codex MCP is installed |
| `codex_model` | string | `""` | Optional model override for Codex review calls (empty = use Codex MCP default) |
| `codex_idea_rounds` | int | `2` | Max Codex-guided idea refinement rounds; `0` = skip Codex iteration |

When `codex_enabled: true` and `codex_idea_rounds > 0`, the system iterates on ideas based on Codex feedback:
1. After the idea debate (6 agents + synthesizer + novelty checker), Codex reviews the proposal
2. If Codex outputs `VERDICT: REVISE`, the system loops back to a full idea debate round with feedback as context
3. This repeats up to `codex_idea_rounds` times, then advances regardless

See [Codex Integration](codex-integration.md) for full setup instructions.

## Integrations

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `lark_enabled` | bool | `true` | Enable Feishu/Lark cloud document sync |
| `evolution_enabled` | bool | `true` | Enable cross-project self-evolution engine |

## Orchestra External Skills

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `orchestra_skills_enabled` | bool | `true` | Enable external skill index injection into agent prompts |
| `orchestra_skills_dir` | string | `"~/.orchestra/skills"` | Directory containing Orchestra skill packs |
| `orchestra_skills_max` | int | `15` | Maximum skills shown per agent prompt (filtered by topic relevance) |

When enabled and `@orchestra-research/ai-research-skills` is installed, Sibyl agents automatically receive a compact table of relevant ML skills (fine-tuning, inference, evaluation, etc.) in their prompts. Agents can invoke these skills on demand via the `Skill` tool for expert guidance.

See [setup guide](setup-guide.md#step-10-ai-research-skills-optional) for installation instructions.

## Model Routing

Advanced: control which Claude model each agent tier uses.

```yaml
model_tiers:
  heavy: "claude-opus-4-6"      # Synthesis, supervision, editing, review
  standard: "claude-opus-4-6"   # Literature, planning, experiments, writing
  light: "claude-sonnet-4-6"    # Debate, cross-review, section critique
```

### Agent-to-Tier Mapping

Override which tier specific agents use:

```yaml
agent_tier_map:
  synthesizer: heavy
  supervisor: heavy
  supervisor_decision: heavy
  editor: heavy
  final_critic: heavy
  critic: heavy
  reflection: heavy
  literature_researcher: standard
  optimist: light
  skeptic: light
  strategist: light
  section_critic: light
  idea_critique: light
  # All other agents default to "standard"
```

## Reserved Compatibility Blocks

The nested `ideation`, `planning`, `experiment`, and `writing` blocks are still
parsed from YAML so older configs continue to load, but the current Claude Code
runtime does **not** use them as the primary model-routing surface.

Today, runtime model selection is controlled by:

- `.claude/agents/sibyl-{heavy,standard,light}.md`
- `model_tiers`
- `agent_tier_map`

If you include the legacy nested blocks, treat them as compatibility data rather
than the authoritative runtime switchboard.

## Full Example (Local GPU)

```yaml
# Local GPU execution (default)
compute_backend: local
max_gpus: 2
local_env_type: conda
local_conda_env_name: ml_env

# Pipeline
writing_mode: parallel
codex_enabled: false
lark_enabled: false
debate_rounds: 3
idea_exp_cycles: 4

# GPU polling (shared workstation)
gpu_poll_enabled: true
gpu_free_threshold_mb: 4000
gpu_poll_interval_sec: 300

# Experiments
pilot_samples: 32
pilot_timeout: 900
full_seeds: [42, 123, 456, 789]
experiment_timeout: 600
```

## Full Example (Remote SSH)

```yaml
# Remote GPU via SSH
compute_backend: ssh
ssh_server: "default"
remote_base: "/data/sibyl"
max_gpus: 8
gpus_per_task: 2
remote_env_type: "conda"
experiment_mode: ssh_mcp

# Pipeline
writing_mode: parallel
codex_enabled: false
lark_enabled: false
debate_rounds: 3
idea_exp_cycles: 4

# GPU polling (shared server)
gpu_poll_enabled: true
gpu_free_threshold_mb: 4000
gpu_poll_interval_sec: 300

# Experiments
pilot_samples: 32
pilot_timeout: 900
full_seeds: [42, 123, 456, 789]
experiment_timeout: 600
```
