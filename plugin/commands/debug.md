---
description: "Debug 模式：单步执行编排循环，不启动 Ralph Loop"
argument-hint: "<spec_path_or_project_name>"
---

# /sibyl-research:debug

Debug 模式：单步执行编排循环，不启动 Ralph Loop，方便调试和修复问题。

**所有用户可见的输出遵循项目语言配置（`action.language` / `config.language`）；论文正文与 LaTeX 始终使用英文。默认配置为中文。**

工作目录: 项目根目录（通过 $SIBYL_ROOT 或 cd 到 clone 位置）

## Python 环境

所有 python3 调用必须使用 `.venv/bin/python3`，不要使用裸 `python3`。

## 与 /sibyl-start 的区别

- 不启动 Ralph Loop 循环
- 每次只执行一个 action，然后停下来等待用户确认
- 出错时直接停下来，方便排查和修复
- 可反复执行 `/sibyl-debug` 继续下一步

## 输入方式

- Markdown 路径: `workspaces/project/spec.md`
- 纯文本 topic
- 项目名称（已初始化的项目直接跳过初始化）

参数: `$ARGUMENTS`

## 步骤

0. **打印 debug 横幅**：

```
╔═════════════════════════════════════════════════════════════════╗
║       SIBYL RESEARCH SYSTEM  ·  Debug Mode (单步调试)           ║
╚═════════════════════════════════════════════════════════════════╝
```

然后执行以下命令获取当前所有项目快照并在横幅中展示：
```bash
cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_list_projects; cli_list_projects()"
```
展示项目状态表格。

1. **判断参数并初始化**（如果项目已存在则跳过初始化）：
   - 从参数中提取项目名（如果是路径如 `workspaces/ttt-dlm/spec.md`，提取 `ttt-dlm`；如果是纯名称如 `ttt-dlm`，直接使用）
   - 检查 `workspaces/<project>/state.json` 是否存在：
     - **已存在**：跳过初始化，直接进入步骤 2
     - **不存在 + 参数是 .md 路径**：
       ```bash
       cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_init_from_spec; cli_init_from_spec('SPEC_PATH')"
       ```
     - **不存在 + 参数是纯文本**：
       ```bash
       cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_init; cli_init('TOPIC')"
       ```
   - 如果项目存在遗留 paused 标记或已被手动 stop，自动 resume：
     ```bash
     cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_resume; cli_resume('workspaces/PROJECT')"
     ```

1.5. **创建当前步骤 Task**（仅追踪本次单步执行）：
   - 调用 `cli_status` 获取当前 stage 和 iteration
   - 使用 `TaskCreate` 创建一个 task：
     - subject: `[{project}] debug #{iteration} - {current_stage}`
     - description: 当前阶段的简要说明

2. **单步获取下一个 action**：
```bash
cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_next; cli_next('workspaces/PROJECT')"
```

3. **显示 action 详情**，格式：
```
  [DEBUG] Action 详情
  ──────────────────
  action_type: xxx
  stage:       xxx
  description: xxx
```

4. **设置语言环境变量**：`export SIBYL_LANGUAGE=<action.language>`

5. **执行该 action**：

   动态加载编排循环定义获取 action dispatch 规则：
   ```bash
   cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import load_prompt; print(load_prompt('orchestration_loop'))"
   ```

   按编排循环定义中对应 action_type 的规则执行该 action。
   如果检测到遗留 `paused_at` / 手动 stop 标记，先自动 resume，再重新获取 action。

5. **记录结果**：
```bash
cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_record; cli_record('workspaces/PROJECT', 'STAGE')"
```
记录 `cli_record` 返回的 JSON；如果包含 `sync_requested: true`，表示需要启动后台飞书同步。

5.5. **阶段间处理**（cli_record 成功后执行）：

   a0. **更新进度 Task**：TaskUpdate(taskId=步骤1.5创建的taskId, status="completed")。

   a. **阶段汇总**：用 1-3 句项目语言对应的语言总结本阶段完成的工作和关键发现。
      如果是长上下文阶段（literature_search, idea_debate, experiment_*,
      writing_*, critique_*, review_*），将汇总写入阶段文档：
      写入 WORKSPACE_PATH/logs/stage_summaries/STAGE.md
      内容包括：阶段名、时间、关键产出文件列表、核心发现/结论摘要

   b. **更新研究日志**：追加一条记录到 WORKSPACE_PATH/logs/research_diary.md
      格式: ## [STAGE] YYYY-MM-DD HH:MM\n<汇总内容>\n

   c. **飞书后台同步**：如果 `cli_record` 返回 `sync_requested: true`，后台启动 `sibyl-lark-sync workspaces/PROJECT`，不要等待它完成，也不要让它阻塞 debug 主流程。

   注意：debug 模式**不执行 /compact**，因为每次执行一步就停下来，新 session 自然有新上下文。

6. **停下来等待**：打印结果摘要，提示用户：
```
  [DEBUG] 当前步骤执行完毕
  ──────────────────────
  已完成：<stage> - <description>
  下一步：再次执行 /sibyl-debug <project> 继续
```

## 错误处理

- 出错时直接报告错误详情，**不自动重试**
- 用户可修复问题后重新执行 `/sibyl-debug`
- 不调用 cli_pause，不进入等待循环
