---
name: sibyl-planner
description: Sibyl 实验规划 agent - 设计严谨可复现的实验方案
context: fork
agent: sibyl-standard
user-invocable: false
allowed-tools: Read, Write, Glob, Grep, Bash, WebSearch, WebFetch
---

!`SIBYL_WORKSPACE="$ARGUMENTS[0]" .venv/bin/python3 -c "from sibyl.orchestrate import load_prompt, load_common_prompt; import os; ws = os.environ.get('SIBYL_WORKSPACE', ''); print(load_common_prompt(ws)); print('---'); print(load_prompt('planner', workspace_path=ws))"`

AGENT_NAME: sibyl-planner
AGENT_TIER: sibyl-standard
SIBYL_ROOT: /Users/cwan0785/sibyl-system

Workspace path: $ARGUMENTS[0]
Mode: $ARGUMENTS[1] (`plan` | `fix-gpu`)
Planning detail: $ARGUMENTS[2] (only for `plan` mode; e.g. pilot config summary)
