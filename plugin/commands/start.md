---
description: "启动研究项目并自动进入持续迭代循环"
argument-hint: "<spec_path_or_topic>"
---

# /sibyl-research:start

启动研究项目并自动进入持续迭代循环。

**所有用户可见的输出遵循项目语言配置（`action.language` / `config.language`）；论文正文与 LaTeX 始终使用英文。默认配置为中文。**

工作目录: `$SIBYL_ROOT`

## Python 环境

所有 python3 调用必须使用 `.venv/bin/python3`，不要使用裸 `python3`。

## 输入方式

- Markdown 路径: `workspaces/project/spec.md`
- 纯文本 topic（兼容旧用法）

参数: `$ARGUMENTS`

## 步骤

0. **打印启动横幅**，格式如下（语言遵循项目配置，默认中文）：

```
╔═════════════════════════════════════════════════════════════════╗
║     SIBYL RESEARCH SYSTEM  ·  Autonomous Research Engine        ║
╚═════════════════════════════════════════════════════════════════╝

  项目：<project_name>
  主题：<topic（如已知）>
  阶段：initializing...
  迭代：#0

  正在启动持续迭代研究循环 →
```

然后执行以下命令获取当前所有项目快照并在横幅中展示：
```bash
cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_list_projects; cli_list_projects()"
```
将结果以简洁表格形式附在横幅后，显示各项目的名称、阶段、迭代数。

1. 判断参数类型并初始化：
```bash
# Markdown 模式（参数以 .md 结尾或包含路径分隔符）
cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_init_from_spec; cli_init_from_spec('SPEC_PATH')"
# Topic 模式
cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_init; cli_init('TOPIC')"
```
2. 记录返回的 `workspace_path` 和 `project_name`

2.5. **保存 Session / Pane 归属供 Sentinel 使用，并先检查是否和其他项目冲突**：
   ```bash
   CURRENT_PANE=""
   if [ -n "${TMUX:-}" ]; then
     CURRENT_PANE=$(tmux display-message -p '#{pane_id}')
   fi
   SESSION_JSON=$(cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_sentinel_session; cli_sentinel_session('WORKSPACE_PATH', '${CLAUDE_CODE_SESSION_ID:-}', '${CURRENT_PANE:-}')")
   echo "$SESSION_JSON"
   if [[ "$(echo "$SESSION_JSON" | jq -r '.ownership_conflict // false')" == "true" ]]; then
     echo "检测到当前 Claude Session 或 tmux pane 已被其他项目占用。每个项目必须使用独立的 Claude pane/session。"
     echo "$SESSION_JSON" | jq '.conflicts'
     exit 0
   fi
   ```

3. **生成 Ralph Loop prompt 并启动持续迭代**：

   ```bash
   cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_write_ralph_prompt; cli_write_ralph_prompt('WORKSPACE_PATH', 'PROJECT_NAME')"
   ```

   然后使用 Skill 工具调用 `ralph-loop:ralph-loop`，prompt 使用**单行 shell-safe 文本**：
   ```
   按照 WORKSPACE_PATH/.claude/ralph-prompt.txt 中的指令持续迭代西比拉研究项目 PROJECT_NAME，工作目录 WORKSPACE_PATH，按编排循环章节执行每轮操作
   ```
   参数: `--max-iterations 30 --completion-promise 'SIBYL_PIPELINE_COMPLETE'`

   如果 Ralph Loop 不可用（插件错误），则手动执行编排循环。

4. **启动 Sentinel 看门狗**（在 tmux 的 sibling pane 中，确保实验轮询不中断）：
   ```bash
   if [ -n "${TMUX:-}" ] && [ -n "${CURRENT_PANE:-}" ]; then
     SIBYL_ROOT="$(cd /Users/cwan0785/sibyl-system && pwd)"
     # 在当前 window 右侧创建窄 pane 运行 sentinel
     tmux split-window -h -l 60 \
       "bash $SIBYL_ROOT/sibyl/sentinel.sh WORKSPACE_PATH $CURRENT_PANE 120"
     # 焦点切回主 pane
     tmux select-pane -t "$CURRENT_PANE"
     echo "Sentinel 已启动（右侧 pane）"
   else
     echo "未检测到 tmux，Sentinel 未启动。建议在 tmux session 中运行。"
   fi
   ```
   注意：将 WORKSPACE_PATH 替换为实际路径。

## 编排循环

**动态渲染编排循环定义（运行时 prompt 以 Python builder 为准）：**
```bash
cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import render_control_plane_prompt; print(render_control_plane_prompt('loop', workspace_path='WORKSPACE_PATH'))"
```

读取输出内容获取运行时 control-plane protocol，然后按其中的 LOOP 流程执行。
