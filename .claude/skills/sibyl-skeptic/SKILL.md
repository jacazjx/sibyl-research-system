---
name: sibyl-skeptic
description: Sibyl 怀疑论者 agent - 以最大怀疑态度审视实验结果
context: fork
agent: sibyl-light
user-invocable: false
allowed-tools: Read, Write, Glob, Grep, Bash
---

!`SIBYL_WORKSPACE="$ARGUMENTS[0]" .venv/bin/python3 -c "from sibyl.orchestrate import load_prompt, load_common_prompt; import os; ws = os.environ.get('SIBYL_WORKSPACE', ''); print(load_common_prompt(ws)); print('---'); print(load_prompt('skeptic', workspace_path=ws))"`

AGENT_NAME: sibyl-skeptic
AGENT_TIER: sibyl-light
SIBYL_ROOT: /Users/cwan0785/sibyl-system

Workspace path: $ARGUMENTS[0]
