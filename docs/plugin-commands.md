# Plugin Commands Reference

All commands are prefixed with `/sibyl-research:` in Claude Code.

## Launch Context

- Repo root launch is best for setup and global maintenance commands such as `:init`, `:status`, `:migrate`, and `:evolve`.
- Active project execution should start Claude from `workspaces/<project>/`, not from the repo root and not from `workspaces/<project>/current`.
- For multi-project parallel execution, use one tmux pane/session per workspace root and one Claude instance per pane. Do not reuse a single Claude pane/session across multiple projects.

## Core Commands

### `/sibyl-research:init`

Interactive initialization. Generates a `spec.md` requirements file and creates the workspace.

```
/sibyl-research:init
```

### `/sibyl-research:start <project>`

Start the autonomous research loop. Enters continuous iteration via Ralph Loop.

> **Prerequisite**: Claude Code should be launched with `--dangerously-skip-permissions` for this command to work as intended. Without it, the autonomous loop will be interrupted by hundreds of permission prompts per iteration. See [Getting Started](getting-started.md) for details and security considerations.

```
/sibyl-research:start my-project
```

### `/sibyl-research:continue <project>`

Resume a project from its current stage. Re-enters the orchestration loop.

```
/sibyl-research:continue my-project
```

### `/sibyl-research:resume <project>`

Resume a manually stopped project, or clear any legacy pause marker before re-entering the loop. In normal autonomous operation, `cli_next()` auto-clears transient `paused_at` states, so `continue` is usually enough.

```
/sibyl-research:resume my-project
```

### `/sibyl-research:status`

View status of all research projects (stage, iteration, score, errors).

```
/sibyl-research:status
```

### `/sibyl-research:stop <project>`

Stop the research project and close the Ralph Loop.

```
/sibyl-research:stop my-project
```

## Research Control

### `/sibyl-research:debug <project>`

Single-step mode. Executes one pipeline stage at a time, waiting for confirmation before advancing. Useful for debugging and understanding the pipeline.

```
/sibyl-research:debug my-project
```

### `/sibyl-research:pivot <project>`

Force a PIVOT — abandon the current research direction and return to idea debate with alternative proposals.

```
/sibyl-research:pivot my-project
```

## Sync & Evolution

### `/sibyl-research:sync <project>`

Manually sync research data to Feishu/Lark cloud documents. Normally triggered automatically after each stage.

```
/sibyl-research:sync my-project
```

### `/sibyl-research:evolve`

Run cross-project evolution analysis. Extracts lessons from all completed projects and generates agent prompt improvements.

```
/sibyl-research:evolve
```

## Migration

### `/sibyl-research:migrate <project>`

Migrate a local project from an older workspace structure to the current version.

```
/sibyl-research:migrate old-project
```

### `/sibyl-research:migrate-server <project>`

Initialize or migrate the server-side directory structure for a project. Creates `projects/<project>/`, `shared/`, and `registry.json` on the remote server.

```
/sibyl-research:migrate-server my-project
```
