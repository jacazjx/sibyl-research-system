---
name: sibyl-final-critic
description: Sibyl 终审 agent - NeurIPS/ICML 级别的论文终审
context: fork
agent: sibyl-heavy
user-invocable: false
allowed-tools: Read, Write, Glob, Grep, Bash
---

!`SIBYL_WORKSPACE="$ARGUMENTS[0]" .venv/bin/python3 -c "from sibyl.orchestrate import load_prompt, load_common_prompt; import os; ws = os.environ.get('SIBYL_WORKSPACE', ''); print(load_common_prompt(ws)); print('---'); print(load_prompt('final_critic', workspace_path=ws))"`

AGENT_NAME: sibyl-final-critic
AGENT_TIER: sibyl-heavy
SIBYL_ROOT: /Users/cwan0785/sibyl-system

Workspace path: $ARGUMENTS[0]
