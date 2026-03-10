---
description: "恢复已有研究项目"
argument-hint: "<project>"
---

# /sibyl-research:continue

恢复已有项目并进入编排循环。

**所有用户可见的输出遵循项目语言配置（`action.language` / `config.language`）；论文正文与 LaTeX 始终使用英文。默认配置为中文。**

工作目录: 项目根目录（通过 $SIBYL_ROOT 或 cd 到 clone 位置）

参数: `$ARGUMENTS`（项目名称）

## 步骤

1. **读取 breadcrumb 恢复上下文**：
   读取 `workspaces/$ARGUMENTS/breadcrumb.json`，了解中断前的状态：
   - `stage`: 当前所在阶段
   - `action_type`: 中断前正在执行的操作类型
   - `in_loop`: 是否在轮询循环中（experiment_wait / gpu_poll）
   - `loop_type`: 循环类型（用于恢复轮询）
   - `iteration`: 当前迭代编号
   - `description`: 操作描述

2. **查看项目状态**：
```bash
cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_status; cli_status('workspaces/$ARGUMENTS')"
```

2.5. **如果检测到手动 stop 或遗留 pause 标记，先清理状态**：
   - 如果 `cli_status` 输出里 `stop_requested == true`，立即执行：
   ```bash
   cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_resume; cli_resume('workspaces/$ARGUMENTS')"
   ```
   - 如果 `paused == true` 但 `stop_requested == false`，这是遗留暂停标记；可以直接继续，因为 `cli_next()` 会自动清除。如果你希望先显式清理，也可以调用同一条 `cli_resume`。

3. **更新 Session ID 供 Sentinel 使用**：
   ```bash
   cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_sentinel_session; cli_sentinel_session('workspaces/$ARGUMENTS', '${CLAUDE_CODE_SESSION_ID:-}')"
   ```

4. **动态加载编排循环定义（支持热重载）**：
   ```bash
   cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import load_prompt; print(load_prompt('orchestration_loop'))"
   ```
   读取输出内容获取完整的 CLI API 参考、进度追踪和编排循环定义。

5. **进入编排循环**：
   按加载的编排循环定义中的 LOOP 流程执行，将所有 `WORKSPACE_PATH` 替换为 `workspaces/$ARGUMENTS`。

   如果 breadcrumb 显示 `in_loop == true`（中断前在轮询循环中），直接调用 `cli_next` 获取最新状态并恢复轮询，不需要重新执行已完成的阶段。
