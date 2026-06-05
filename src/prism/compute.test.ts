import { describe, expect, it } from "vitest";
import { computePrism } from "./compute.js";
import type { RRIndicators } from "../types/indicators.js";
import type { PrismWeights } from "../types/prism.js";
import weightsJson from "../weights/prism-v1.json" with { type: "json" };

const weights = weightsJson as unknown as PrismWeights;

function makeIndicators(id: string): RRIndicators {
  return {
    steamId64: id,
    totalRounds: 20,
    kills: 10,
    deaths: 10,
    assists: 3,
    kpr: 0.5,
    dpr: 0.5,
    apr: 0.15,
    adr: 70,
    hsPercent: 45,
    kast: 70,
    survivalRate: 0.5,
    twoKillRounds: 2,
    threeKillRounds: 1,
    fourKillRounds: 0,
    fiveKillRounds: 0,
    multiKillRate: 0.15,
    firstKillCount: 2,
    firstDeathCount: 2,
    firstKillRate: 0.1,
    firstDeathRate: 0.1,
    openingDuelRate: 0.2,
    openingDuelWinRate: 0.5,
    tradeKillCount: 2,
    tradeDeathCount: 2,
    tradeKillRate: 0.1,
    tradeDeathRate: 0.2,
    clutchAttempts: 1,
    clutchWins: 0,
    clutchWinRate: 0,
    clutchFrequency: 0.05,
    clutchScore: 0,
    clutchScoreRate: 0,
    vsOne: { count: 1, won: 0 },
    vsTwo: { count: 0, won: 0 },
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
    utilityDamage: 0,
    utilityDamagePerRound: 0,
    flashAssistCount: 0,
    flashAssistPerRound: 0,
    blindDurationTotal: 0,
    blindDurationPerRound: 0,
    enemyFlashDurationSeconds: null,
    enemyFlashDurationPerRound: null,
    teamFlashDurationSeconds: null,
    teamFlashDurationPerRound: null,
    grenadeCount: 0,
    grenadeCountPerRound: 0,
    ecoRoundCount: 0,
    forceRoundCount: 0,
    fullBuyRoundCount: 0,
    pistolRoundCount: 0,
    avgEquipmentValue: 0,
    combatDeathCount: null,
    bombDeathCount: null,
    wallbangKillCount: null,
    roundSwingTotal: null,
    roundSwingPerKill: null,
  };
}

describe("computePrism", () => {
  it("marks an axis as no-signal and does not create a fake percentile", () => {
    const custom: PrismWeights = {
      ...weights,
      axes: {
        ...weights.axes,
        utility: {
          alpha: 0.5,
          involvement: [{ signal: "effectiveEnemyFlashSecondsPerRound", weight: 1 }],
          efficiency: [{ signal: "smokeProtectedCrossingsPerRound", weight: 1 }],
        },
      },
    };

    const [out] = computePrism([
      { indicators: makeIndicators("a"), mapCount: 10, rrPercentile: 50 },
      { indicators: makeIndicators("b"), mapCount: 10, rrPercentile: 50 },
    ], custom);

    expect(out!.axes.utility.hasSignal).toBe(false);
    expect(out!.axes.utility.availableSignalWeight).toBe(0);
    expect(out!.axes.utility.percentile).toBe(0);
  });
});
