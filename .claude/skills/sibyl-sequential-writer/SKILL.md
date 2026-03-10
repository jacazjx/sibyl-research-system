---
name: sibyl-sequential-writer
description: Sibyl 顺序写作 agent - 按章节顺序写作，确保整体行文一致性
context: fork
agent: sibyl-standard
user-invocable: false
allowed-tools: Read, Write, Glob, Grep, Bash
---

!`SIBYL_WORKSPACE="$ARGUMENTS[0]" .venv/bin/python3 -c "from sibyl.orchestrate import load_prompt, load_common_prompt; import os; ws = os.environ.get('SIBYL_WORKSPACE', ''); print(load_common_prompt(ws)); print('---'); print(load_prompt('sequential_writer', workspace_path=ws))"`

AGENT_NAME: sibyl-sequential-writer
AGENT_TIER: sibyl-standard
SIBYL_ROOT: /Users/cwan0785/sibyl-system

Workspace path: $ARGUMENTS[0]
