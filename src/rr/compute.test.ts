import { describe, it, expect } from "vitest";
import { computeRR, computeLeagueMean } from "./compute.js";
import type { RRIndicators } from "../types/indicators.js";
import type { RRWeights } from "../types/rr.js";

// ── 最小合法 RRWeights ────────────────────────────────────────────────────
const weights: RRWeights = {
  version: "rr-test",
  base: {
    kastCoef: 0.0073,
    kprCoef: 0.3591,
    dprCoef: -0.5329,
    impactKprWeight: 2.13,
    impactAprWeight: 0.42,
    impactIntercept: -0.41,
    impactCoef: 0.2372,
    adrCoef: 0.0032,
    intercept: 0.1587,
  },
  ecoMultipliers: {
    ecoKillMultiplier: 1.0,
    forceKillMultiplier: 1.0,
    fullBuyKillMultiplier: 1.0,
    pistolKillMultiplier: 1.0,
    ecoVsFullBonus: 1.0,
  },
  layer2: { roundSwingCoef: 0.0 },
  clamp: { min: 0.1, max: 3.0 },
  anchor: { mode: "league_mean" },
};

// ── 基础选手数据（联赛平均水平，期望 RR ≈ 1.0）───────────────────────────
function makeAvgPlayer(overrides: Partial<RRIndicators> = {}): RRIndicators {
  const totalRounds = 24;
  return {
    steamId64: "test",
    totalRounds,
    kills: 17,
    deaths: 16,
    assists: 4,
    kpr: 17 / totalRounds,
    dpr: 16 / totalRounds,
    apr: 4 / totalRounds,
    adr: 73,
    hsPercent: 45,
    kast: 73,
    survivalRate: (totalRounds - 16) / totalRounds,
    twoKillRounds: 4,
    threeKillRounds: 1,
    fourKillRounds: 0,
    fiveKillRounds: 0,
    multiKillRate: 5 / totalRounds,
    firstKillCount: 3,
    firstDeathCount: 3,
    firstKillRate: 3 / totalRounds,
    firstDeathRate: 3 / totalRounds,
    openingDuelRate: 6 / totalRounds,
    openingDuelWinRate: 0.5,
    tradeKillCount: 4,
    tradeDeathCount: 3,
    tradeKillRate: 4 / totalRounds,
    tradeDeathRate: 3 / 16,
    clutchAttempts: 3,
    clutchWins: 1,
    clutchWinRate: 1 / 3,
    clutchFrequency: 3 / totalRounds,
    clutchScore: 1,
    clutchScoreRate: 1 / totalRounds,
    vsOne: { count: 2, won: 1 },
    vsTwo: { count: 1, won: 0 },
    vsThree: { count: 0, won: 0 },
    vsFour: { count: 0, won: 0 },
    vsFive: { count: 0, won: 0 },
    awpKills: 0,
    awpKillsPerRound: 0,
    awpKillRate: 0,
    sniperKills: 0,
    sniperKillRate: 0,
    awpMultiKillRate: null,
    awpDuelWinRate: null,
    utilityDamage: 120,
    utilityDamagePerRound: 5,
    flashAssistCount: 2,
    flashAssistPerRound: 2 / totalRounds,
    blindDurationTotal: 3.5,
    blindDurationPerRound: 3.5 / totalRounds,
    enemyFlashDurationSeconds: null,
    enemyFlashDurationPerRound: null,
    teamFlashDurationSeconds: null,
    teamFlashDurationPerRound: null,
    grenadeCount: 18,
    grenadeCountPerRound: 18 / totalRounds,
    ecoRoundCount: 4,
    forceRoundCount: 4,
    fullBuyRoundCount: 12,
    pistolRoundCount: 4,
    avgEquipmentValue: 3200,
    combatDeathCount: null,
    bombDeathCount: null,
    wallbangKillCount: null,
    roundSwingTotal: null,
    roundSwingPerKill: null,
    ...overrides,
  };
}

describe("computeRR", () => {
  it("联赛平均水平选手 RR 应在 0.9–1.1 之间", () => {
    const result = computeRR(makeAvgPlayer(), weights);
    // 17K/16D (正 K/D) 的选手略高于联赛均值，1.0–1.15 是合理范围
    expect(result.rr).toBeGreaterThan(0.9);
    expect(result.rr).toBeLessThan(1.15);
    expect(result.weightsVersion).toBe("rr-test");
  });

  it("totalRounds=0 时返回兜底值 1.0", () => {
    const result = computeRR(makeAvgPlayer({ totalRounds: 0 }), weights);
    expect(result.rr).toBe(1.0);
  });

  it("高 frag 选手 RR > 1.0", () => {
    const result = computeRR(
      makeAvgPlayer({
        kills: 28,
        kpr: 28 / 24,
        adr: 110,
        kast: 85,
        deaths: 10,
        dpr: 10 / 24,
      }),
      weights,
    );
    expect(result.rr).toBeGreaterThan(1.0);
  });

  it("breakdown 各项求和约等于 rrBase", () => {
    const result = computeRR(makeAvgPlayer(), weights);
    const { kastTerm, kprTerm, dprTerm, impactTerm, adrTerm, intercept } =
      result.breakdown;
    const summed = kastTerm + kprTerm + dprTerm + impactTerm + adrTerm + intercept;
    expect(Math.abs(summed - result.rrBase)).toBeLessThan(0.01);
  });

  it("Layer 2 关闭时 rrSwing 为 0", () => {
    const result = computeRR(makeAvgPlayer(), weights);
    expect(result.rrSwing).toBe(0);
  });

  it("pistol round multiplier is controlled by weights", () => {
    const allPistol = makeAvgPlayer({
      ecoRoundCount: 0,
      forceRoundCount: 0,
      fullBuyRoundCount: 0,
      pistolRoundCount: 24,
    });
    const tuned: RRWeights = {
      ...weights,
      ecoMultipliers: {
        ...weights.ecoMultipliers,
        pistolKillMultiplier: 1.2,
      },
    };

    expect(computeRR(allPistol, tuned).rr).toBeGreaterThan(computeRR(allPistol, weights).rr);
  });

  it("clamp 生效：极差选手不低于 0.1", () => {
    const result = computeRR(
      makeAvgPlayer({ kills: 0, kpr: 0, adr: 0, kast: 0, deaths: 24, dpr: 1 }),
      weights,
    );
    expect(result.rr).toBeGreaterThanOrEqual(0.1);
  });
});

describe("computeLeagueMean", () => {
  it("空数组返回 1.0", () => {
    expect(computeLeagueMean([])).toBe(1.0);
  });

  it("均值计算正确", () => {
    const results = [1.0, 1.2, 0.8].map((rr) => ({
      rr,
      rrBase: rr,
      rrSwing: 0,
      weightsVersion: "test",
      breakdown: {
        kastTerm: 0, kprTerm: 0, dprTerm: 0,
        impactTerm: 0, adrTerm: 0, intercept: 0,
      },
    }));
    expect(computeLeagueMean(results)).toBeCloseTo(1.0);
  });
});
