#!/usr/bin/env node

import {
  formatSummary,
  loadConfig,
  loadHookInput,
  loadQuotaSnapshot,
  decideQuota
} from './lib/quota-guard-lib.mjs';

function readModelName(input) {
  if (!input || typeof input !== 'object') {
    return null;
  }

  return input?.model?.display_name || input?.model?.id || null;
}

function readWorkspace(input) {
  if (!input || typeof input !== 'object') {
    return null;
  }

  return input?.workspace?.current_dir || null;
}

function basenameOrNull(value) {
  if (!value || typeof value !== 'string') {
    return null;
  }

  const parts = value.split('/').filter(Boolean);
  return parts[parts.length - 1] || value;
}

const config = loadConfig();
const input = loadHookInput();
const snapshot = loadQuotaSnapshot(config);
const decision = decideQuota(snapshot, config);

const segments = [formatSummary(snapshot, decision, { compact: true })];
const modelName = readModelName(input);
const workspace = basenameOrNull(readWorkspace(input));

if (workspace) {
  segments.push(`cwd ${workspace}`);
}

if (modelName) {
  segments.push(`model ${modelName}`);
}

process.stdout.write(`${segments.join(' | ')}\n`);
