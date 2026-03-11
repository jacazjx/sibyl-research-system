---
description: "停止研究项目并关闭 Ralph Loop 循环"
argument-hint: "<project_or_workspace>"
---

# /sibyl-research:stop

停止研究项目并关闭 Ralph Loop 持续迭代循环。

**所有用户可见的输出遵循项目语言配置（`action.language` / `config.language`）；论文正文与 LaTeX 始终使用英文。默认配置为中文。**

工作目录: 项目根目录（通过 $SIBYL_ROOT 或 cd 到 clone 位置）

参数: `$ARGUMENTS`（项目名称或 workspace 路径）

## 步骤

0. **规范化目标 workspace**：
```bash
TARGET_WORKSPACE="$ARGUMENTS"
if [[ "$TARGET_WORKSPACE" != */* && "$TARGET_WORKSPACE" != .* ]]; then
  TARGET_WORKSPACE="workspaces/$TARGET_WORKSPACE"
fi
```

1. 写入手动停止标记：
```bash
cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_pause; cli_pause('$TARGET_WORKSPACE', 'user_stop')"
```

1.5. 停止 Sentinel 看门狗：
```bash
echo '{"stop": true}' > "$TARGET_WORKSPACE/sentinel_stop.json"
```

1.7. 清除当前项目对 Claude Session / tmux pane 的归属声明：
```bash
cd $SIBYL_ROOT && .venv/bin/python3 -c "from sibyl.orchestrate import cli_sentinel_session; cli_sentinel_session('$TARGET_WORKSPACE', '', '')"
```

2. 取消 Ralph Loop（关闭 stop hook 循环）：
   使用 Skill 工具调用 `ralph-loop:cancel-ralph`

3. 输出确认信息：告知用户项目已停止，可用 `/sibyl-research:resume <project>` 恢复。
