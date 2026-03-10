import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const DEFAULT_USAGE_CACHE_FILE = '~/.claude/micucodeline/.api_usage_cache.json';
const DEFAULT_BALANCE_CACHE_DIR = '~/.claude/micucodeline/cache';
const DEFAULT_STATE_DIR = '~/.claude/quota-guard';

function expandHome(inputPath) {
  if (!inputPath || inputPath === '~') {
    return os.homedir();
  }

  if (inputPath.startsWith('~/')) {
    return path.join(os.homedir(), inputPath.slice(2));
  }

  return inputPath;
}

function toNumber(value, fallback = null) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function toBoolean(value, fallback) {
  if (value === undefined || value === null || value === '') {
    return fallback;
  }

  const normalized = String(value).trim().toLowerCase();
  if (['1', 'true', 'yes', 'on'].includes(normalized)) {
    return true;
  }

  if (['0', 'false', 'no', 'off'].includes(normalized)) {
    return false;
  }

  return fallback;
}

function clamp(number, min, max) {
  return Math.min(max, Math.max(min, number));
}

function readJson(filePath) {
  try {
    const raw = fs.readFileSync(filePath, 'utf8').trim();
    if (!raw) {
      return null;
    }
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function findNewestBalanceFile(balanceCacheDir) {
  try {
    const entries = fs
      .readdirSync(balanceCacheDir, { withFileTypes: true })
      .filter((entry) => entry.isFile() && /^balance_.*\.json$/.test(entry.name))
      .map((entry) => {
        const fullPath = path.join(balanceCacheDir, entry.name);
        const stats = fs.statSync(fullPath);
        return { fullPath, mtimeMs: stats.mtimeMs };
      })
      .sort((left, right) => right.mtimeMs - left.mtimeMs);

    return entries[0]?.fullPath ?? null;
  } catch {
    return null;
  }
}

function parseDate(value) {
  if (!value) {
    return null;
  }

  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function readStdin() {
  try {
    const raw = fs.readFileSync(0, 'utf8');
    return raw ? raw.toString() : '';
  } catch {
    return '';
  }
}

function safeParseJson(raw) {
  if (!raw || !raw.trim()) {
    return null;
  }

  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function loadHookInput() {
  return safeParseJson(readStdin()) ?? {};
}

export function loadConfig(env = process.env) {
  return {
    minFiveHourRemainingPercent: clamp(
      toNumber(env.CLAUDE_QUOTA_GUARD_MIN_FIVE_HOUR_REMAINING_PERCENT, 5),
      0,
      100
    ),
    minBalance: toNumber(env.CLAUDE_QUOTA_GUARD_MIN_BALANCE),
    minBalanceRemainingPercent: toNumber(
      env.CLAUDE_QUOTA_GUARD_MIN_BALANCE_REMAINING_PERCENT
    ),
    pollSeconds: Math.max(1, Math.floor(toNumber(env.CLAUDE_QUOTA_GUARD_POLL_SECONDS, 60))),
    maxWaitSeconds: Math.max(0, Math.floor(toNumber(env.CLAUDE_QUOTA_GUARD_MAX_WAIT_SECONDS, 0))),
    staleUsageSeconds: Math.max(
      0,
      Math.floor(toNumber(env.CLAUDE_QUOTA_GUARD_STALE_USAGE_SECONDS, 900))
    ),
    failOpen: toBoolean(env.CLAUDE_QUOTA_GUARD_FAIL_OPEN, true),
    stateDir: expandHome(env.CLAUDE_QUOTA_GUARD_STATE_DIR || DEFAULT_STATE_DIR),
    usageCacheFile: expandHome(
      env.CLAUDE_QUOTA_GUARD_USAGE_CACHE_FILE || DEFAULT_USAGE_CACHE_FILE
    ),
    balanceFile: env.CLAUDE_QUOTA_GUARD_BALANCE_FILE
      ? expandHome(env.CLAUDE_QUOTA_GUARD_BALANCE_FILE)
      : null,
    balanceCacheDir: expandHome(
      env.CLAUDE_QUOTA_GUARD_BALANCE_CACHE_DIR || DEFAULT_BALANCE_CACHE_DIR
    ),
    resetGraceSeconds: Math.max(
      0,
      Math.floor(toNumber(env.CLAUDE_QUOTA_GUARD_RESET_GRACE_SECONDS, 15))
    )
  };
}

export function loadQuotaSnapshot(config = loadConfig()) {
  const usageCache = readJson(config.usageCacheFile);
  const balanceFile = config.balanceFile || findNewestBalanceFile(config.balanceCacheDir);
  const balanceCache = balanceFile ? readJson(balanceFile) : null;

  const cachedAt = parseDate(usageCache?.cached_at);
  const resetAt = parseDate(usageCache?.resets_at);
  const now = new Date();
  const staleUsage =
    cachedAt !== null &&
    config.staleUsageSeconds > 0 &&
    now.getTime() - cachedAt.getTime() > config.staleUsageSeconds * 1000;

  const fiveHourUtilization = toNumber(usageCache?.five_hour_utilization);
  const sevenDayUtilization = toNumber(usageCache?.seven_day_utilization);
  const balance = toNumber(balanceCache?.balance);
  const total = toNumber(balanceCache?.total);
  const used = toNumber(balanceCache?.used);

  return {
    capturedAt: now.toISOString(),
    staleUsage,
    usage: {
      sourcePath: config.usageCacheFile,
      exists: usageCache !== null,
      cachedAt: cachedAt ? cachedAt.toISOString() : null,
      resetAt: resetAt ? resetAt.toISOString() : null,
      fiveHourUtilization,
      fiveHourRemainingPercent:
        fiveHourUtilization === null ? null : clamp(100 - fiveHourUtilization, 0, 100),
      sevenDayUtilization,
      sevenDayRemainingPercent:
        sevenDayUtilization === null ? null : clamp(100 - sevenDayUtilization, 0, 100)
    },
    balance: {
      sourcePath: balanceFile,
      exists: balanceCache !== null,
      balance,
      total,
      used,
      isUnlimited: Boolean(balanceCache?.is_unlimited),
      remainingPercent:
        balance !== null && total && total > 0 ? clamp((balance / total) * 100, 0, 100) : null
    }
  };
}

export function decideQuota(snapshot, config = loadConfig()) {
  const reasons = [];

  if (
    snapshot.usage.fiveHourRemainingPercent !== null &&
    snapshot.usage.fiveHourRemainingPercent < config.minFiveHourRemainingPercent
  ) {
    reasons.push(
      `five-hour remaining ${formatPercent(snapshot.usage.fiveHourRemainingPercent)} < ${formatPercent(config.minFiveHourRemainingPercent)}`
    );
  }

  if (
    config.minBalance !== null &&
    snapshot.balance.balance !== null &&
    snapshot.balance.balance < config.minBalance
  ) {
    reasons.push(
      `balance ${formatNumber(snapshot.balance.balance)} < ${formatNumber(config.minBalance)}`
    );
  }

  if (
    config.minBalanceRemainingPercent !== null &&
    snapshot.balance.remainingPercent !== null &&
    snapshot.balance.remainingPercent < config.minBalanceRemainingPercent
  ) {
    reasons.push(
      `balance remaining ${formatPercent(snapshot.balance.remainingPercent)} < ${formatPercent(config.minBalanceRemainingPercent)}`
    );
  }

  return {
    lowQuota: reasons.length > 0,
    reasons
  };
}

export function formatPercent(value) {
  return value === null || value === undefined ? 'n/a' : `${value.toFixed(1)}%`;
}

export function formatNumber(value) {
  return value === null || value === undefined ? 'n/a' : `${value.toFixed(2)}`;
}

export function formatReset(value) {
  if (!value) {
    return 'n/a';
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return 'n/a';
  }

  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  }).format(date);
}

export function formatSummary(snapshot, decision, options = {}) {
  const compact = Boolean(options.compact);
  const parts = [
    `5h ${formatPercent(snapshot.usage.fiveHourRemainingPercent)}`,
    `7d ${formatPercent(snapshot.usage.sevenDayRemainingPercent)}`,
    `reset ${formatReset(snapshot.usage.resetAt)}`
  ];

  if (snapshot.balance.balance !== null && snapshot.balance.total !== null) {
    parts.push(
      `bal ${formatNumber(snapshot.balance.balance)}/${formatNumber(snapshot.balance.total)}`
    );
  }

  if (snapshot.staleUsage && !compact) {
    parts.push('usage-cache stale');
  }

  if (decision.lowQuota) {
    parts.push(compact ? 'quota-low' : `hold: ${decision.reasons.join('; ')}`);
  }

  return parts.join(' | ');
}

function ensureStateDir(stateDir) {
  try {
    fs.mkdirSync(stateDir, { recursive: true });
  } catch {
    return false;
  }
  return true;
}

export function persistState(config, snapshot, decision, extra = {}) {
  if (!config.stateDir) {
    return;
  }

  if (!ensureStateDir(config.stateDir)) {
    return;
  }

  const record = {
    recordedAt: new Date().toISOString(),
    snapshot,
    decision,
    ...extra
  };

  try {
    fs.writeFileSync(
      path.join(config.stateDir, 'last-state.json'),
      JSON.stringify(record, null, 2)
    );
    fs.appendFileSync(path.join(config.stateDir, 'history.jsonl'), `${JSON.stringify(record)}\n`);
  } catch {
    // Ignore state persistence errors. The hook should stay best-effort.
  }
}

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

export async function waitForQuota(config, logger = console.error) {
  const startedAt = Date.now();
  let polls = 0;

  while (true) {
    const snapshot = loadQuotaSnapshot(config);
    const decision = decideQuota(snapshot, config);
    persistState(config, snapshot, decision, { polls });

    const hasData =
      snapshot.usage.exists ||
      snapshot.balance.exists ||
      snapshot.usage.fiveHourRemainingPercent !== null ||
      snapshot.balance.balance !== null;

    if (!hasData) {
      return {
        outcome: config.failOpen ? 'allow-no-data' : 'block-no-data',
        snapshot,
        decision,
        waitedMs: Date.now() - startedAt,
        polls
      };
    }

    if (!decision.lowQuota) {
      return {
        outcome: 'allow',
        snapshot,
        decision,
        waitedMs: Date.now() - startedAt,
        polls
      };
    }

    const elapsedSeconds = Math.floor((Date.now() - startedAt) / 1000);
    if (config.maxWaitSeconds > 0 && elapsedSeconds >= config.maxWaitSeconds) {
      return {
        outcome: config.failOpen ? 'allow-timeout' : 'block-timeout',
        snapshot,
        decision,
        waitedMs: Date.now() - startedAt,
        polls
      };
    }

    logger(
      `[quota-guard] ${formatSummary(snapshot, decision)}. Polling again in ${config.pollSeconds}s.`
    );
    await sleep(config.pollSeconds * 1000);
    polls += 1;
  }
}
