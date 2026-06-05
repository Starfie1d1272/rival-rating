import { describe, it, expect } from "vitest";
import { computeFrozenProBaselineRR } from "./frozen-pro-baseline.js";
import type { ProBaselineConfig } from "./frozen-pro-baseline.js";
import { computeRRSixAccounts } from "./six-accounts.js";
import { RR_ACCOUNTS } from "../../types/accounts.js";
import type { RRAccountKey, RRSixAccountWeights, RRSignals } from "../../types/accounts.js";
import weightsJson from "../../weights/rr-six-accounts-v1.json" with { type: "json" };

const weights = weightsJson as unknown as RRSixAccountWeights;

function makePlayer(id: string, o: { kills?: number; deaths?: number; damage?: number } = {}): RRSignals {
  const rounds = 200;
  return {
    steamId64: id,
    rounds,
    combat: {
      kills: o.kills ?? 140,
      deaths: o.deaths ?? 130,
      assists: 50,
      effectiveDamage: o.damage ?? 16000,
      openingKills: 18,
      openingDeaths: 16,
      multiKills: { two: 20, three: 8, four: 1, five: 0 },
      headshotKills: 70,
      wallbangKills: 3,
      killsByBuyDelta: null,
      killsByManState: null,
    },
    trade: {
      tradeKills: 30,
      tradedDeaths: 25,
      deaths: o.deaths ?? 130,
      tradedOpeningDeaths: 8,
      strategicIsolationDeaths: 2,
    },
    mapControl: {
      uniqueStrategicControlSeconds: 180,
      contestedFrontierControlSeconds: 120,
      routeDenialSeconds: 90,
      teammateAdvanceUnits: 250,
      firstControlEvents: 20,
    },
    utility: {
      flashAssists: 10,
      effectiveEnemyFlashSeconds: 90,
      teamFlashSuppressionSeconds: 8,
      smokeProtectedCrossings: 15,
      smokeSightlineDenialSeconds: 60,
      smokeIsolationSeconds: 40,
      incendiaryPathDelayUnits: 180,
      incendiaryDisplacementEvents: 5,
      utilityDamage: 600,
    },
    clutch: {
      vsOne: { count: 4, won: 1 },
      vsTwo: { count: 2, won: 0 },
      vsThree: { count: 1, won: 0 },
      vsFour: { count: 0, won: 0 },
      vsFive: { count: 0, won: 0 },
    },
    objective: { plants: 6, defuses: 3, plantsConverted: 4 },
  };
}

/** 用某选手的 raw 账户当 mean 造一个 baseline → 该选手所有 z=0。 */
function baselineCenteredOn(p: RRSignals, opts: { scale?: number } = {}): ProBaselineConfig {
  const w = weights.accountWeights;
  const res = computeRRSixAccounts(p, weights);
  const accounts = {} as ProBaselineConfig["accounts"];
  for (const k of RR_ACCOUNTS as readonly RRAccountKey[]) {
    accounts[k] = { mean: w[k] !== 0 ? res.accounts[k] / w[k] : 0, std: 0.1, slope: 0 };
  }
  return {
    version: "test-baseline",
    accountWeights: w,
    clamp: weights.clamp,
    scale: opts.scale ?? 0.2,
    anchor: 1.0,
    accounts,
  };
}

describe("computeFrozenProBaselineRR", () => {
  it("scores a player exactly at baseline mean to the anchor (1.0)", () => {
    const ref = makePlayer("ref");
    const baseline = baselineCenteredOn(ref);
    const out = computeFrozenProBaselineRR(ref, weights, baseline);
    expect(out.rr).toBeCloseTo(1.0, 6);
    expect(out.rrRaw).toBeCloseTo(0, 6);
  });

  it("is portable: a single player's RR depends only on signal+baseline, not on any cohort", () => {
    const ref = makePlayer("ref");
    const baseline = baselineCenteredOn(ref);
    const target = makePlayer("t", { kills: 170, damage: 19000 });
    const a = computeFrozenProBaselineRR(target, weights, baseline);
    const b = computeFrozenProBaselineRR(target, weights, baseline);
    expect(a.rr).toBe(b.rr); // 确定性，无 cohort 依赖
  });

  it("rates above the anchor when combat exceeds the baseline mean", () => {
    const ref = makePlayer("ref");
    const baseline = baselineCenteredOn(ref);
    const strong = makePlayer("strong", { kills: 200, damage: 24000 });
    const out = computeFrozenProBaselineRR(strong, weights, baseline);
    expect(out.rr).toBeGreaterThan(1.0);
  });

  it("respects the clamp floor for far-below-baseline play", () => {
    const ref = makePlayer("ref", { kills: 200, damage: 24000 });
    const baseline = baselineCenteredOn(ref, { scale: 5 }); // 放大离散度，逼出下限
    const weak = makePlayer("weak", { kills: 30, deaths: 170, damage: 4000 });
    const out = computeFrozenProBaselineRR(weak, weights, baseline);
    expect(out.rr).toBeGreaterThanOrEqual(weights.clamp.min);
  });

  it("breakdown sums to (rr - anchor)", () => {
    const ref = makePlayer("ref");
    const baseline = baselineCenteredOn(ref);
    const target = makePlayer("t", { kills: 160, damage: 18000 });
    const out = computeFrozenProBaselineRR(target, weights, baseline);
    const sum = (Object.values(out.accounts) as number[]).reduce((s, v) => s + v, 0);
    expect(sum).toBeCloseTo(out.rr - baseline.anchor, 6);
  });
});
