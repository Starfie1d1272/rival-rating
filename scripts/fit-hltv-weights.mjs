#!/usr/bin/env node

import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { basename, dirname, join } from "node:path";

const args = parseArgs(process.argv.slice(2));
const fixturesDir = args.fixtures ?? "fixtures/account-signals-v2";
const labelsDir = args.labels ?? "fixtures/hltv-labels";
const lambda = number(args.lambda, 1);
const outPath = args.out;
const metricsPath = args.metrics;

const featureSpec = [
  { name: "combat.killsPerRound", value: (s) => safeDiv(s.combat.kills, s.rounds) },
  { name: "combat.deathsPerRound", value: (s) => safeDiv(s.combat.deaths, s.rounds) },
  { name: "combat.damagePerRound", value: (s) => safeDiv(s.combat.effectiveDamage, s.rounds) },
  {
    name: "combat.openingDiffPerRound",
    value: (s) => safeDiv(s.combat.openingKills - s.combat.openingDeaths, s.rounds),
  },
  {
    name: "combat.multiKillsPerRound",
    value: (s) =>
      safeDiv(
        s.combat.multiKills.two +
          s.combat.multiKills.three +
          s.combat.multiKills.four +
          s.combat.multiKills.five,
        s.rounds,
      ),
  },
  { name: "combat.headshotsPerRound", value: (s) => safeDiv(s.combat.headshotKills, s.rounds) },
  { name: "combat.wallbangsPerRound", value: (s) => safeDiv(s.combat.wallbangKills ?? 0, s.rounds) },
  { name: "trade.tradeKillsPerRound", value: (s) => safeDiv(s.trade.tradeKills, s.rounds) },
  { name: "trade.tradedDeathsPerRound", value: (s) => safeDiv(s.trade.tradedDeaths, s.rounds) },
  {
    name: "trade.untradedDeathsPerRound",
    value: (s) => safeDiv(Math.max(0, s.trade.deaths - s.trade.tradedDeaths), s.rounds),
  },
  {
    name: "clutch.winsPerRound",
    value: (s) =>
      safeDiv(
        s.clutch.vsOne.won +
          s.clutch.vsTwo.won +
          s.clutch.vsThree.won +
          s.clutch.vsFour.won +
          s.clutch.vsFive.won,
        s.rounds,
      ),
  },
  { name: "objective.plantsPerRound", value: (s) => safeDiv(s.objective.plants, s.rounds) },
  { name: "objective.defusesPerRound", value: (s) => safeDiv(s.objective.defuses, s.rounds) },
  {
    name: "objective.plantsConvertedPerRound",
    value: (s) => safeDiv(s.objective.plantsConverted ?? 0, s.rounds),
  },
  { name: "utility.flashAssistsPerRound", value: (s) => safeDiv(s.utility.flashAssists, s.rounds) },
  {
    name: "utility.enemyFlashSecondsPerRound",
    value: (s) => safeDiv(s.utility.enemyFlashDurationSeconds, s.rounds),
  },
  {
    name: "utility.teamFlashSecondsPerRound",
    value: (s) => safeDiv(s.utility.teamFlashDurationSeconds ?? 0, s.rounds),
  },
  { name: "utility.damagePerRound", value: (s) => safeDiv(s.utility.utilityDamage, s.rounds) },
];

if (!existsSync(fixturesDir)) {
  fail(`Missing fixtures directory: ${fixturesDir}`);
}
if (!existsSync(labelsDir)) {
  fail(`Missing labels directory: ${labelsDir}`);
}

const examples = loadExamples(fixturesDir, labelsDir);
if (examples.length < 2) {
  fail(`Need at least 2 labeled player-map rows, found ${examples.length}`);
}

const featureNames = featureSpec.map((feature) => feature.name);
const x = examples.map((example) => [1, ...featureSpec.map((feature) => feature.value(example.signal))]);
const y = examples.map((example) => example.hltvRating);
const { means, scales, standardized } = standardizeFeatures(x);
const coefficientsStd = solveRidge(standardized, y, lambda);
const coefficients = unstandardizeCoefficients(coefficientsStd, means, scales);
const predictions = x.map((row) => dot(row, coefficients));
const metrics = buildMetrics(examples, y, predictions, featureNames, coefficients, lambda);
const weights = buildWeights(coefficients, metrics);

if (metricsPath) {
  writeJson(metricsPath, metrics);
}
if (outPath) {
  writeJson(outPath, weights);
}

console.log(
  JSON.stringify(
    {
      rows: examples.length,
      fixtures: new Set(examples.map((example) => example.fixtureId)).size,
      lambda,
      mae: round(metrics.metrics.mae, 6),
      rmse: round(metrics.metrics.rmse, 6),
      pearson: round(metrics.metrics.pearson, 6),
      spearman: round(metrics.metrics.spearman, 6),
      out: outPath,
      metrics: metricsPath,
    },
    null,
    2,
  ),
);

function loadExamples(fixturesDir, labelsDir) {
  const labelFiles = readdirSync(labelsDir)
    .filter((file) => file.endsWith(".json"))
    .sort();
  const examples = [];

  for (const file of labelFiles) {
    const path = join(labelsDir, file);
    const labelsFile = JSON.parse(readFileSync(path, "utf8"));
    const fixtureId = labelsFile.fixtureId ?? basename(file, ".json");
    const fixturePath = join(fixturesDir, `${fixtureId}.json`);
    if (!existsSync(fixturePath)) {
      throw new Error(`Label file ${path} references missing fixture ${fixturePath}`);
    }

    const fixture = JSON.parse(readFileSync(fixturePath, "utf8"));
    const signalsBySteamId = new Map(fixture.signals.map((signal) => [signal.steamId64, signal]));
    for (const label of asArray(labelsFile.labels)) {
      const steamId64 = String(label.steamId64 ?? "");
      const signal = signalsBySteamId.get(steamId64);
      if (!signal) {
        throw new Error(`Label ${steamId64} in ${path} is missing from fixture ${fixturePath}`);
      }
      const hltvRating = number(label.hltvRating, Number.NaN);
      if (!Number.isFinite(hltvRating)) {
        throw new Error(`Label ${steamId64} in ${path} has invalid hltvRating`);
      }
      examples.push({
        fixtureId,
        steamId64,
        playerName: label.playerName,
        hltvRating,
        ratingVersion: label.ratingVersion ?? labelsFile.ratingVersion,
        sourceUrl: label.sourceUrl ?? labelsFile.sourceUrl,
        signal,
      });
    }
  }

  return examples;
}

function buildWeights(coefficients, metrics) {
  const c = (name) => coefficients[featureNames.indexOf(name) + 1] ?? 0;
  return {
    version: "rr-hltv-fit-v1-0.1",
    description:
      "Candidate ValueAccountsWeights fit against visible HLTV player-map ratings. Treat as an evaluation artifact, not production RR philosophy.",
    fit: {
      target: "hltvRating",
      ratingVersions: [...new Set(metrics.rows.map((row) => row.ratingVersion).filter(Boolean))],
      rows: metrics.rows.length,
      lambda: metrics.lambda,
      metrics: metrics.metrics,
    },
    intercept: round(coefficients[0] ?? 1, 8),
    accountWeights: {
      combat: 1,
      trade: 1,
      clutch: 1,
      objective: 1,
      utility: 1,
    },
    combat: {
      killWeight: round(c("combat.killsPerRound"), 8),
      deathWeight: round(c("combat.deathsPerRound"), 8),
      damageWeight: round(c("combat.damagePerRound"), 8),
      openingWeight: round(c("combat.openingDiffPerRound"), 8),
      multiKillWeight: round(c("combat.multiKillsPerRound"), 8),
      headshotWeight: round(c("combat.headshotsPerRound"), 8),
      wallbangWeight: round(c("combat.wallbangsPerRound"), 8),
      buyDelta: { disadvantageMultiplier: 1, advantageMultiplier: 1 },
      manState: { manDownMultiplier: 1, manUpMultiplier: 1 },
    },
    trade: {
      tradeKillWeight: round(c("trade.tradeKillsPerRound"), 8),
      tradedDeathWeight: round(c("trade.tradedDeathsPerRound"), 8),
      untradedDeathPenalty: round(c("trade.untradedDeathsPerRound"), 8),
    },
    clutch: {
      expectation: { vsOne: 0.5, vsTwo: 0.25, vsThree: 0.1, vsFour: 0.04, vsFive: 0.01 },
      winValueWeight: round(c("clutch.winsPerRound"), 8),
    },
    objective: {
      plantWeight: round(c("objective.plantsPerRound"), 8),
      defuseWeight: round(c("objective.defusesPerRound"), 8),
      plantConvertedBonus: round(c("objective.plantsConvertedPerRound"), 8),
    },
    utility: {
      flashAssistWeight: round(c("utility.flashAssistsPerRound"), 8),
      enemyFlashSecWeight: round(c("utility.enemyFlashSecondsPerRound"), 8),
      teamFlashPenalty: round(c("utility.teamFlashSecondsPerRound"), 8),
      utilityDamageWeight: round(c("utility.damagePerRound"), 8),
    },
    cohort: { targetStd: 0.2, epsilon: 1e-9 },
    clamp: { min: 0.1, max: 3 },
    anchor: {
      mode: "league_mean",
      note: "Fitted to HLTV labels. Refit with more labels before using for evaluation.",
    },
  };
}

function buildMetrics(examples, actual, predicted, featureNames, coefficients, lambda) {
  const residuals = actual.map((value, index) => value - predicted[index]);
  const abs = residuals.map(Math.abs);
  const squared = residuals.map((value) => value * value);
  return {
    version: "hltv-fit-metrics-v1",
    lambda,
    rows: examples.map((example, index) => ({
      fixtureId: example.fixtureId,
      steamId64: example.steamId64,
      playerName: example.playerName,
      ratingVersion: example.ratingVersion,
      sourceUrl: example.sourceUrl,
      actual: round(actual[index], 6),
      predicted: round(predicted[index], 6),
      residual: round(residuals[index], 6),
    })),
    coefficients: Object.fromEntries(
      ["intercept", ...featureNames].map((name, index) => [name, round(coefficients[index] ?? 0, 8)]),
    ),
    metrics: {
      mae: mean(abs),
      rmse: Math.sqrt(mean(squared)),
      pearson: pearson(actual, predicted),
      spearman: spearman(actual, predicted),
    },
  };
}

function standardizeFeatures(matrix) {
  const cols = matrix[0]?.length ?? 0;
  const means = Array(cols).fill(0);
  const scales = Array(cols).fill(1);
  const standardized = matrix.map((row) => [...row]);

  for (let col = 1; col < cols; col += 1) {
    means[col] = mean(matrix.map((row) => row[col] ?? 0));
    const variance = mean(matrix.map((row) => ((row[col] ?? 0) - means[col]) ** 2));
    scales[col] = Math.sqrt(variance) || 1;
    for (const row of standardized) {
      row[col] = ((row[col] ?? 0) - means[col]) / scales[col];
    }
  }

  return { means, scales, standardized };
}

function unstandardizeCoefficients(coefficientsStd, means, scales) {
  const coefficients = [...coefficientsStd];
  coefficients[0] = coefficientsStd[0] ?? 0;
  for (let i = 1; i < coefficients.length; i += 1) {
    coefficients[i] = (coefficientsStd[i] ?? 0) / (scales[i] ?? 1);
    coefficients[0] -= coefficients[i] * (means[i] ?? 0);
  }
  return coefficients;
}

function solveRidge(x, y, lambda) {
  const cols = x[0]?.length ?? 0;
  const xtx = Array.from({ length: cols }, () => Array(cols).fill(0));
  const xty = Array(cols).fill(0);

  for (let row = 0; row < x.length; row += 1) {
    for (let i = 0; i < cols; i += 1) {
      xty[i] += (x[row][i] ?? 0) * (y[row] ?? 0);
      for (let j = 0; j < cols; j += 1) {
        xtx[i][j] += (x[row][i] ?? 0) * (x[row][j] ?? 0);
      }
    }
  }

  for (let i = 1; i < cols; i += 1) {
    xtx[i][i] += lambda;
  }

  return gaussianSolve(xtx, xty);
}

function gaussianSolve(a, b) {
  const n = b.length;
  const m = a.map((row, i) => [...row, b[i]]);

  for (let col = 0; col < n; col += 1) {
    let pivot = col;
    for (let row = col + 1; row < n; row += 1) {
      if (Math.abs(m[row][col]) > Math.abs(m[pivot][col])) pivot = row;
    }
    if (Math.abs(m[pivot][col]) < 1e-12) {
      m[pivot][col] = 1e-12;
    }
    [m[col], m[pivot]] = [m[pivot], m[col]];
    const div = m[col][col];
    for (let j = col; j <= n; j += 1) m[col][j] /= div;
    for (let row = 0; row < n; row += 1) {
      if (row === col) continue;
      const factor = m[row][col];
      for (let j = col; j <= n; j += 1) {
        m[row][j] -= factor * m[col][j];
      }
    }
  }

  return m.map((row) => row[n]);
}

function parseArgs(args) {
  return Object.fromEntries(
    args
      .filter((arg) => arg.startsWith("--") && arg.includes("="))
      .map((arg) => {
        const index = arg.indexOf("=");
        return [arg.slice(2, index), arg.slice(index + 1)];
      }),
  );
}

function safeDiv(value, divisor) {
  return divisor > 0 ? value / divisor : 0;
}

function mean(values) {
  return values.length > 0 ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
}

function dot(a, b) {
  return a.reduce((sum, value, index) => sum + value * (b[index] ?? 0), 0);
}

function pearson(a, b) {
  const am = mean(a);
  const bm = mean(b);
  const numerator = a.reduce((sum, value, index) => sum + (value - am) * ((b[index] ?? 0) - bm), 0);
  const denominator = Math.sqrt(
    a.reduce((sum, value) => sum + (value - am) ** 2, 0) *
      b.reduce((sum, value) => sum + (value - bm) ** 2, 0),
  );
  return denominator > 0 ? numerator / denominator : 0;
}

function spearman(a, b) {
  return pearson(ranks(a), ranks(b));
}

function ranks(values) {
  const sorted = values
    .map((value, index) => ({ value, index }))
    .sort((a, b) => a.value - b.value);
  const ranks = Array(values.length);
  for (let i = 0; i < sorted.length; ) {
    let j = i + 1;
    while (j < sorted.length && sorted[j].value === sorted[i].value) j += 1;
    const rank = (i + j + 1) / 2;
    for (let k = i; k < j; k += 1) ranks[sorted[k].index] = rank;
    i = j;
  }
  return ranks;
}

function number(value, fallback) {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function round(value, digits) {
  const scale = 10 ** digits;
  return Math.round(value * scale) / scale;
}

function writeJson(path, value) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, `${JSON.stringify(value, null, 2)}\n`);
}

function fail(message) {
  console.error(message);
  process.exit(1);
}
