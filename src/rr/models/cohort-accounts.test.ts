import { describe, it, expect } from "vitest";
import { computeCohortAccountsRR } from "./cohort-accounts.js";
import type { RRSixAccountWeights, RRSignals } from "../../types/accounts.js";
import weightsJson from "../../weights/rr-six-accounts-v1.json" with { type: "json" };

const weights = weightsJson as unknown as RRSixAccountWeights;

function makePlayer(
  id: string,
  o: { kills?: number; deaths?: number; damage?: number; clutchWon?: number; clutchCount?: number; mapControl?: number } = {},
): RRSignals {
  const rounds = 200;
  const clutchCount = o.clutchCount ?? 4;
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
      killsByBuyDelta: { disadvantage: 20, even: 90, advantage: 30 },
      killsByManState: { manDown: 40, even: 60, manUp: 40 },
    },
    trade: {
      tradeKills: 30,
      tradedDeaths: 25,
      deaths: o.deaths ?? 130,
      tradedOpeningDeaths: 8,
      strategicIsolationDeaths: 2,
    },
    mapControl: {
      uniqueStrategicControlSeconds: o.mapControl ?? 180,
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
      vsOne: { count: clutchCount, won: o.clutchWon ?? 1 },
      vsTwo: { count: 2, won: 0 },
      vsThree: { count: 1, won: 0 },
      vsFour: { count: 0, won: 0 },
      vsFive: { count: 0, won: 0 },
    },
    objective: { plants: 6, defuses: 3, plantsConverted: 4 },
  };
}

describe("computeCohortAccountsRR", () => {
  it("anchors the cohort mean to ~1.0 and never shrinks by sample size", () => {
    const cohort = [
      makePlayer("a", { kills: 180, damage: 20000 }),
      makePlayer("b", { kills: 150, damage: 17000 }),
      makePlayer("c", { kills: 130, damage: 15000 }),
      makePlayer("d", { kills: 110, damage: 13000 }),
      makePlayer("e", { kills: 95, damage: 11000 }),
    ];
    const out = computeCohortAccountsRR(cohort, weights);
    const mean = out.reduce((s, r) => s + r.rr, 0) / out.length;
    expect(out).toHaveLength(5);
    expect(mean).toBeCloseTo(1.0, 6);
    // combat 是主干：fragging 最高的人 RR 最高
    const byId = new Map(out.map((r) => [r.steamId64, r.rr]));
    expect(byId.get("a")!).toBeGreaterThan(byId.get("e")!);
  });

  it("residualizes non-combat: teamplay beyond fragging moves the clutch account", () => {
    // 两个 combat 完全相同、只有 clutch 不同的选手，clutch 贡献必须不同
    const cohort = [
      makePlayer("low", { clutchWon: 0, clutchCount: 4 }),
      makePlayer("high", { clutchWon: 4, clutchCount: 4 }),
      makePlayer("mid", { clutchWon: 2, clutchCount: 4 }),
      makePlayer("x", { kills: 170, damage: 19000, clutchWon: 1 }),
      makePlayer("y", { kills: 100, damage: 12000, clutchWon: 1 }),
    ];
    const out = computeCohortAccountsRR(cohort, weights);
    const acc = new Map(out.map((r) => [r.steamId64, r.accounts]));
    // clutch 全赢的人 clutch 贡献 > 全输的人
    expect(acc.get("high")!.clutch).toBeGreaterThan(acc.get("low")!.clutch);
    // residual 账户对总和有贡献（非全 0）
    const clutchStd = stdev(out.map((r) => r.accounts.clutch));
    expect(clutchStd).toBeGreaterThan(0);
  });

  it("keeps MapControl as an independent residual account", () => {
    const cohort = [
      makePlayer("low", { mapControl: 60 }),
      makePlayer("high", { mapControl: 300 }),
      makePlayer("mid", { mapControl: 160 }),
      makePlayer("x", { kills: 170, damage: 19000, mapControl: 100 }),
      makePlayer("y", { kills: 100, damage: 12000, mapControl: 220 }),
    ];
    const out = computeCohortAccountsRR(cohort, weights);
    const acc = new Map(out.map((r) => [r.steamId64, r.accounts]));
    expect(acc.get("high")!.mapControl).toBeGreaterThan(acc.get("low")!.mapControl);
  });

  it("returns empty for empty cohort", () => {
    expect(computeCohortAccountsRR([], weights)).toEqual([]);
  });
});

function stdev(xs: number[]): number {
  const m = xs.reduce((a, b) => a + b, 0) / xs.length;
  return Math.sqrt(xs.reduce((a, x) => a + (x - m) ** 2, 0) / xs.length);
}
