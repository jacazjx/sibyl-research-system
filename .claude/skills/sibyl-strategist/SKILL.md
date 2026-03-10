---
name: sibyl-strategist
description: Sibyl 战略顾问 agent - 从战略角度分析结果并建议下一步
context: fork
agent: sibyl-light
user-invocable: false
allowed-tools: Read, Write, Glob, Grep, Bash
---

!`SIBYL_WORKSPACE="$ARGUMENTS[0]" .venv/bin/python3 -c "from sibyl.orchestrate import load_prompt, load_common_prompt; import os; ws = os.environ.get('SIBYL_WORKSPACE', ''); print(load_common_prompt(ws)); print('---'); print(load_prompt('strategist', workspace_path=ws))"`

AGENT_NAME: sibyl-strategist
AGENT_TIER: sibyl-light
SIBYL_ROOT: /Users/cwan0785/sibyl-system

Workspace path: $ARGUMENTS[0]
