# Repo Tools

`tools/` contains repository-level helper projects that support Sibyl development or the local Claude environment.

Rules for this directory:

- Put reusable repo tools here, not under `workspaces/`.
- A tool may install or sync into user-level locations such as `~/.claude/...`, but its source of truth lives here.
- Tool state should stay inside the tool's own folder or the user-level install target, not inside Sibyl project workspaces.
- Anything under `workspaces/` should be a real Sibyl research project with `status.json`, project memory, and layered runtime scaffold.

Current tools:

- `claude-quota-guard/`: local Claude quota hook and status helper
