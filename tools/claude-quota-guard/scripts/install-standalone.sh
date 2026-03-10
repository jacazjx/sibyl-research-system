#!/usr/bin/env bash
set -euo pipefail

SOURCE_ROOT="/Users/cwan0785/sibyl-system/tools/claude-quota-guard"
TARGET_ROOT="$HOME/.claude/quota-guard"

mkdir -p "$TARGET_ROOT/scripts/lib"

cp "$SOURCE_ROOT/scripts/quota-guard.mjs" "$TARGET_ROOT/scripts/quota-guard.mjs"
cp "$SOURCE_ROOT/scripts/lib/quota-guard-lib.mjs" "$TARGET_ROOT/scripts/lib/quota-guard-lib.mjs"

backup_path="$HOME/.claude/settings.json.bak.$(date +%s)"
cp "$HOME/.claude/settings.json" "$backup_path"

node <<'NODE'
const fs = require('fs');
const os = require('os');
const path = require('path');

const home = os.homedir();
const settingsPath = path.join(home, '.claude', 'settings.json');
const hookCommand = `node ${path.join(home, '.claude', 'quota-guard', 'scripts', 'quota-guard.mjs')}`;
const settings = JSON.parse(fs.readFileSync(settingsPath, 'utf8'));

settings.env = settings.env || {};
if (!settings.env.CLAUDE_QUOTA_GUARD_MIN_FIVE_HOUR_REMAINING_PERCENT) {
  settings.env.CLAUDE_QUOTA_GUARD_MIN_FIVE_HOUR_REMAINING_PERCENT = '5';
}
if (!settings.env.CLAUDE_QUOTA_GUARD_POLL_SECONDS) {
  settings.env.CLAUDE_QUOTA_GUARD_POLL_SECONDS = '60';
}
if (!settings.env.CLAUDE_QUOTA_GUARD_MAX_WAIT_SECONDS) {
  settings.env.CLAUDE_QUOTA_GUARD_MAX_WAIT_SECONDS = '0';
}

settings.hooks = settings.hooks || {};
const currentHooks = Array.isArray(settings.hooks.UserPromptSubmit)
  ? settings.hooks.UserPromptSubmit
  : [];

const alreadyPresent = currentHooks.some(
  (entry) =>
    Array.isArray(entry?.hooks) &&
    entry.hooks.some((hook) => hook?.command === hookCommand)
);

if (!alreadyPresent) {
  currentHooks.push({
    matcher: '*',
    hooks: [
      {
        type: 'command',
        command: hookCommand
      }
    ]
  });
}

settings.hooks.UserPromptSubmit = currentHooks;
fs.writeFileSync(settingsPath, `${JSON.stringify(settings, null, 2)}\n`);
NODE

node "$TARGET_ROOT/scripts/quota-guard.mjs" --check >/dev/null

echo "Installed quota-guard into $TARGET_ROOT"
echo "Updated $HOME/.claude/settings.json"
echo "Backup saved to $backup_path"
