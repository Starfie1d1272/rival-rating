import { describe, expect, it } from "vitest";
import { computeRRSixAccounts } from "./six-accounts.js";
import type { RRSixAccountWeights, RRSignals } from "../../types/accounts.js";
import weightsJson from "../../weights/rr-six-accounts-v1.json" with { type: "json" };

const weights = weightsJson as unknown as RRSixAccountWeights;
const mapControlEnabledWeights: RRSixAccountWeights = {
  ...weights,
  accountWeights: { ...weights.accountWeights, mapControl: 0.2 },
};

function makeSignals(overrides: Partial<RRSignals> = {}): RRSignals {
  const rounds = 100;
  const base: RRSignals = {
    steamId64: "p1",
    rounds,
    combat: {
      kills: 70,
      deaths: 65,
      assists: 20,
      effectiveDamage: 8000,
      openingKills: 10,
      openingDeaths: 9,
      multiKills: { two: 10, three: 3, four: 1, five: 0 },
      headshotKills: 35,
      wallbangKills: 1,
      killsByBuyDelta: null,
      killsByManState: null,
    },
    trade: {
      tradeKills: 18,
      tradedDeaths: 15,
      deaths: 65,
      tradedOpeningDeaths: 4,
      strategicIsolationDeaths: 0,
    },
    mapControl: {
      uniqueStrategicControlSeconds: 90,
      contestedFrontierControlSeconds: 70,
      routeDenialSeconds: 50,
      teammateAdvanceUnits: 120,
      firstControlEvents: 10,
    },
    utility: {
      flashAssists: 5,
      effectiveEnemyFlashSeconds: 40,
      teamFlashSuppressionSeconds: 3,
      smokeProtectedCrossings: 8,
      smokeSightlineDenialSeconds: 25,
      smokeIsolationSeconds: 15,
      incendiaryPathDelayUnits: 60,
      incendiaryDisplacementEvents: 3,
      utilityDamage: 300,
    },
    clutch: {
      vsOne: { count: 2, won: 1 },
      vsTwo: { count: 1, won: 0 },
      vsThree: { count: 0, won: 0 },
      vsFour: { count: 0, won: 0 },
      vsFive: { count: 0, won: 0 },
    },
    objective: { plants: 3, defuses: 1, plantsConverted: 2 },
  };
  return { ...base, ...overrides };
}

describe("computeRRSixAccounts", () => {
  it("returns a neutral result when rounds is zero", () => {
    const out = computeRRSixAccounts(makeSignals({ rounds: 0 }), weights);
    expect(out.rr).toBe(1);
    expect(out.accounts.mapControl).toBe(0);
  });

  it("adds MapControl as a first-class positive account", () => {
    const low = computeRRSixAccounts(makeSignals({
      mapControl: {
        uniqueStrategicControlSeconds: 0,
        contestedFrontierControlSeconds: 0,
        routeDenialSeconds: 0,
        teammateAdvanceUnits: 0,
        firstControlEvents: 0,
      },
    }), mapControlEnabledWeights);
    const high = computeRRSixAccounts(makeSignals({
      mapControl: {
        uniqueStrategicControlSeconds: 200,
        contestedFrontierControlSeconds: 150,
        routeDenialSeconds: 120,
        teammateAdvanceUnits: 300,
        firstControlEvents: 25,
      },
    }), mapControlEnabledWeights);

    expect(high.accounts.mapControl).toBeGreaterThan(low.accounts.mapControl);
    expect(high.rrRaw).toBeGreaterThan(low.rrRaw);
  });

  it("uses strategic isolation only to reduce Trade penalty", () => {
    const isolated = computeRRSixAccounts(makeSignals({
      trade: {
        tradeKills: 18,
        tradedDeaths: 15,
        deaths: 65,
        tradedOpeningDeaths: 4,
        strategicIsolationDeaths: 10,
      },
    }), weights);
    const unisolated = computeRRSixAccounts(makeSignals({
      trade: {
        tradeKills: 18,
        tradedDeaths: 15,
        deaths: 65,
        tradedOpeningDeaths: 4,
        strategicIsolationDeaths: 0,
      },
    }), weights);

    expect(isolated.accounts.trade).toBeGreaterThan(unisolated.accounts.trade);
    expect(isolated.accounts.mapControl).toBe(unisolated.accounts.mapControl);
  });
});
