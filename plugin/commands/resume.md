---
description: "手动恢复已停止或遗留暂停标记的研究项目"
argument-hint: "<project>"
---

# /sibyl-research:resume

手动恢复已停止的项目，或清除遗留暂停标记后重新进入编排循环。

**所有用户可见的输出遵循项目语言配置（`action.language` / `config.language`）；论文正文与 LaTeX 始终使用英文。默认配置为中文。**

工作目录: `$SIBYL_ROOT`

参数: `$ARGUMENTS`（项目名称）

## 步骤

1. 恢复项目：
```bash
cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_resume; cli_resume('workspaces/$ARGUMENTS')"
```

2. 获取当前状态：
```bash
cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_status; cli_status('workspaces/$ARGUMENTS')"
```

2.5. **更新 Session ID 供 Sentinel 使用**：
   ```bash
   cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_sentinel_session; cli_sentinel_session('workspaces/$ARGUMENTS', '${CLAUDE_CODE_SESSION_ID:-}')"
   ```

3. **生成 Ralph Loop prompt 并启动持续迭代**：

   ```bash
   cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_write_ralph_prompt; cli_write_ralph_prompt('workspaces/$ARGUMENTS', '$ARGUMENTS')"
   ```

   然后使用 Skill 工具调用 `ralph-loop:ralph-loop`，prompt 使用**单行 shell-safe 文本**：
   ```
   按照 /tmp/sibyl-ralph-prompt.txt 中的指令持续迭代西比拉研究项目 $ARGUMENTS，工作目录 workspaces/$ARGUMENTS，按编排循环章节执行每轮操作
   ```
   参数: `--max-iterations 30 --completion-promise 'SIBYL_PIPELINE_COMPLETE'`

   如果 Ralph Loop 不可用（插件错误），则手动执行编排循环。

4. **启动 Sentinel 看门狗**（在 tmux 的 sibling pane 中）：
   ```bash
   if [ -n "${TMUX:-}" ]; then
     SIBYL_ROOT="$(cd /Users/cwan0785/sibyl-system && pwd)"
     CURRENT_PANE=$(tmux display-message -p '#{pane_id}')
     tmux split-window -h -l 60 \
       "bash $SIBYL_ROOT/sibyl/sentinel.sh workspaces/$ARGUMENTS $CURRENT_PANE 120"
     tmux select-pane -t "$CURRENT_PANE"
     echo "Sentinel 已启动（右侧 pane）"
   else
     echo "未检测到 tmux，Sentinel 未启动。建议在 tmux session 中运行。"
   fi
   ```

## 编排循环

**动态加载编排循环定义（支持热重载）：**
```bash
cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import load_prompt; print(load_prompt('orchestration_loop'))"
```

读取输出内容获取完整的 CLI API 参考、进度追踪和编排循环定义，然后按其中的 LOOP 流程执行。
将输出中所有 `WORKSPACE_PATH` 替换为实际的 workspace 路径。
