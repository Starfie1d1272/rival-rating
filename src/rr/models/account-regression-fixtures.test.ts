import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { computeCohortAccountsRR } from "./cohort-accounts.js";
import { computeValueAccountsRR } from "./value-accounts-v2-lite.js";
import type { AccountSignalsV2, ValueAccountsWeights } from "../../types/accounts.js";
import weightsJson from "../../weights/rr-value-accounts-v2-lite.json" with { type: "json" };

const weights = weightsJson as unknown as ValueAccountsWeights;
const fixturesDir = fileURLToPath(new URL("../../../fixtures/account-signals-v2/", import.meta.url));
const fixtureFiles = existsSync(fixturesDir)
  ? readdirSync(fixturesDir).filter((file) => file.endsWith(".json")).sort()
  : [];
const updateExpected = process.env.UPDATE_ACCOUNT_FIXTURE_EXPECTED === "1";

interface AccountRegressionFixture {
  id: string;
  source?: {
    matchUrl?: string;
    demoFile?: string;
    tier?: string;
    parsedAt?: string;
  };
  signals: AccountSignalsV2[];
  expected?: {
    tolerance?: number;
    players?: {
      steamId64: string;
      valueAccountsRR?: number;
      cohortRR?: number;
    }[];
  };
}

describe("demo-derived account regression fixtures", () => {
  it("has a fixture directory for AccountSignalsV2 JSON exported from parsed demos", () => {
    expect(existsSync(fixturesDir)).toBe(true);
  });

  for (const file of fixtureFiles) {
    it(`keeps ${file} score outputs stable`, () => {
      const fixture = readFixture(file);
      expect(fixture.signals.length).toBeGreaterThan(0);

      const valueResults = fixture.signals.map((signal) => computeValueAccountsRR(signal, weights));
      const cohortResults = computeCohortAccountsRR(fixture.signals, weights);

      for (const result of valueResults) expect(Number.isFinite(result.rr)).toBe(true);
      for (const result of cohortResults) expect(Number.isFinite(result.rr)).toBe(true);

      const cohortMean =
        cohortResults.reduce((sum, result) => sum + result.rr, 0) / cohortResults.length;
      expect(cohortMean).toBeCloseTo(1.0, 6);

      if (updateExpected) {
        writeFixture(file, {
          ...fixture,
          expected: {
            tolerance: fixture.expected?.tolerance ?? 1e-6,
            players: fixture.signals.map((signal, i) => ({
              steamId64: signal.steamId64,
              valueAccountsRR: roundScore(valueResults[i]?.rr),
              cohortRR: roundScore(cohortResults[i]?.rr),
            })),
          },
        });
      }

      if (!fixture.expected?.players) return;

      const tolerance = fixture.expected.tolerance ?? 1e-6;
      const valueBySteamId = new Map(
        valueResults.map((result, i) => [fixture.signals[i]?.steamId64 ?? "", result]),
      );
      const cohortBySteamId = new Map(cohortResults.map((result) => [result.steamId64, result]));

      for (const expected of fixture.expected.players) {
        if (expected.valueAccountsRR !== undefined) {
          const actual = valueBySteamId.get(expected.steamId64)?.rr;
          expectWithinTolerance(actual, expected.valueAccountsRR, tolerance);
        }
        if (expected.cohortRR !== undefined) {
          const actual = cohortBySteamId.get(expected.steamId64)?.rr;
          expectWithinTolerance(actual, expected.cohortRR, tolerance);
        }
      }
    });
  }
});

function readFixture(file: string): AccountRegressionFixture {
  return JSON.parse(readFileSync(join(fixturesDir, file), "utf8")) as AccountRegressionFixture;
}

function writeFixture(file: string, fixture: AccountRegressionFixture): void {
  writeFileSync(join(fixturesDir, file), `${JSON.stringify(fixture, null, 2)}\n`);
}

function roundScore(value: number | undefined): number {
  if (value === undefined || !Number.isFinite(value)) {
    throw new Error("Cannot freeze a non-finite fixture score");
  }
  return Math.round(value * 1_000_000) / 1_000_000;
}

function expectWithinTolerance(actual: number | undefined, expected: number, tolerance: number): void {
  expect(actual).toBeDefined();
  expect(Math.abs((actual ?? Number.NaN) - expected)).toBeLessThanOrEqual(tolerance);
}
