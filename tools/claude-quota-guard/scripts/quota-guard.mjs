#!/usr/bin/env node

import {
  formatSummary,
  loadConfig,
  loadHookInput,
  loadQuotaSnapshot,
  decideQuota,
  waitForQuota
} from './lib/quota-guard-lib.mjs';

function printJson(value) {
  process.stdout.write(`${JSON.stringify(value, null, 2)}\n`);
}

async function main() {
  const args = new Set(process.argv.slice(2));
  const config = loadConfig();
  const hookInput = loadHookInput();

  if (args.has('--check')) {
    const snapshot = loadQuotaSnapshot(config);
    const decision = decideQuota(snapshot, config);
    printJson({
      mode: 'check',
      hookInput,
      config,
      snapshot,
      decision,
      summary: formatSummary(snapshot, decision)
    });
    return;
  }

  if (args.has('--summary')) {
    const snapshot = loadQuotaSnapshot(config);
    const decision = decideQuota(snapshot, config);
    process.stdout.write(`${formatSummary(snapshot, decision)}\n`);
    return;
  }

  const result = await waitForQuota(config);

  if (result.outcome === 'allow' || result.outcome === 'allow-no-data' || result.outcome === 'allow-timeout') {
    if (result.waitedMs > 0) {
      process.stderr.write(
        `[quota-guard] continuing after ${Math.round(result.waitedMs / 1000)}s: ${formatSummary(result.snapshot, result.decision)}\n`
      );
    }
    return;
  }

  process.stderr.write(
    `[quota-guard] blocked: ${formatSummary(result.snapshot, result.decision)}\n`
  );
  process.exit(2);
}

main().catch((error) => {
  process.stderr.write(`[quota-guard] unexpected error: ${error?.stack || error}\n`);
  process.exit(0);
});
