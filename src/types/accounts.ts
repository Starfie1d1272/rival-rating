/**
 * RR six-account signal contract.
 *
 * This layer stores facts only. Upstream analysis reconstructs what happened;
 * this package decides how much each fact contributes to RR.
 */

export const RR_ACCOUNTS = [
  "combat",
  "trade",
  "mapControl",
  "utility",
  "clutch",
  "objective",
] as const;
export type RRAccountKey = (typeof RR_ACCOUNTS)[number];

export interface CombatSignals {
  kills: number;
  deaths: number;
  assists: number;
  /** Effective weapon damage, capped by remaining health. Utility damage belongs to Utility. */
  effectiveDamage: number;
  openingKills: number;
  openingDeaths: number;
  multiKills: { two: number; three: number; four: number; five: number };
  headshotKills: number;
  wallbangKills: number | null;
  killsByBuyDelta: { disadvantage: number; even: number; advantage: number } | null;
  killsByManState: { manDown: number; even: number; manUp: number } | null;
}

export interface TradeSignals {
  tradeKills: number;
  tradedDeaths: number;
  deaths: number;
  tradedOpeningDeaths: number | null;
  /** Isolation deaths that MapControl marks as strategically valuable. Reduces Trade penalty only. */
  strategicIsolationDeaths: number | null;
}

export interface MapControlSignals {
  uniqueStrategicControlSeconds: number | null;
  contestedFrontierControlSeconds: number | null;
  routeDenialSeconds: number | null;
  teammateAdvanceUnits: number | null;
  firstControlEvents: number | null;
}

export interface UtilitySignals {
  flashAssists: number;
  effectiveEnemyFlashSeconds: number | null;
  teamFlashSuppressionSeconds: number | null;
  smokeProtectedCrossings: number | null;
  smokeSightlineDenialSeconds: number | null;
  smokeIsolationSeconds: number | null;
  incendiaryPathDelayUnits: number | null;
  incendiaryDisplacementEvents: number | null;
  utilityDamage: number;
}

export interface ClutchSignals {
  vsOne: { count: number; won: number };
  vsTwo: { count: number; won: number };
  vsThree: { count: number; won: number };
  vsFour: { count: number; won: number };
  vsFive: { count: number; won: number };
}

export interface ObjectiveSignals {
  plants: number;
  defuses: number;
  plantsConverted: number | null;
}

export interface RRSignals {
  steamId64: string;
  rounds: number;
  sourceVersion?: string;
  combat: CombatSignals;
  trade: TradeSignals;
  mapControl: MapControlSignals;
  utility: UtilitySignals;
  clutch: ClutchSignals;
  objective: ObjectiveSignals;
}

export interface CombatWeights {
  killWeight: number;
  deathWeight: number;
  damageWeight: number;
  openingWeight: number;
  multiKillWeight: number;
  headshotWeight: number;
  wallbangWeight: number;
  buyDelta: { disadvantageMultiplier: number; advantageMultiplier: number };
  manState: { manDownMultiplier: number; manUpMultiplier: number };
}

export interface TradeWeights {
  tradeKillWeight: number;
  tradedDeathWeight: number;
  tradedOpeningDeathWeight: number;
  untradedDeathPenalty: number;
}

export interface MapControlWeights {
  uniqueStrategicControlSecondsWeight: number;
  contestedFrontierControlSecondsWeight: number;
  routeDenialSecondsWeight: number;
  teammateAdvanceUnitsWeight: number;
  firstControlEventsWeight: number;
}

export interface MapControlNormalizers {
  uniqueStrategicControlSecondsPerRoundCap: number;
  contestedFrontierControlSecondsPerRoundCap: number;
  routeDenialSecondsPerRoundCap: number;
  teammateAdvanceUnitsPerRoundCap: number;
  firstControlEventsPerRoundCap: number;
}

export interface UtilityWeights {
  flashAssistWeight: number;
  effectiveEnemyFlashSecondsWeight: number;
  teamFlashSuppressionPenalty: number;
  smokeProtectedCrossingsWeight: number;
  smokeSightlineDenialSecondsWeight: number;
  smokeIsolationSecondsWeight: number;
  incendiaryPathDelayUnitsWeight: number;
  incendiaryDisplacementEventsWeight: number;
  utilityDamageWeight: number;
}

export interface UtilityNormalizers {
  flashAssistsPerRoundCap: number;
  effectiveEnemyFlashSecondsPerRoundCap: number;
  teamFlashSuppressionSecondsPerRoundCap: number;
  smokeProtectedCrossingsPerRoundCap: number;
  smokeSightlineDenialSecondsPerRoundCap: number;
  smokeIsolationSecondsPerRoundCap: number;
  incendiaryPathDelayUnitsPerRoundCap: number;
  incendiaryDisplacementEventsPerRoundCap: number;
  utilityDamagePerRoundCap: number;
}

export interface ClutchWeights {
  expectation: {
    vsOne: number;
    vsTwo: number;
    vsThree: number;
    vsFour: number;
    vsFive: number;
  };
  winValueWeight: number;
  shrinkageK: number;
}

export interface ObjectiveWeights {
  plantWeight: number;
  defuseWeight: number;
  plantConvertedBonus: number;
}

export interface RRSixAccountWeights {
  version: string;
  description?: string;
  score: { base: number; scale: number };
  accountWeights: Record<RRAccountKey, number>;
  combat: CombatWeights;
  trade: TradeWeights;
  mapControl: MapControlWeights;
  mapControlNormalizers: MapControlNormalizers;
  utility: UtilityWeights;
  utilityNormalizers: UtilityNormalizers;
  clutch: ClutchWeights;
  objective: ObjectiveWeights;
  clamp: { min: number; max: number };
  anchor: { mode: "league_mean" | "frozen_pro_baseline"; note?: string };
}

export interface RRSixAccountResult {
  rr: number;
  rrRaw: number;
  weightsVersion: string;
  model: string;
  accounts: Record<RRAccountKey, number>;
  combatContextFactor: number;
}

export interface RRModel<I, W, R> {
  id: string;
  version: string;
  inputKind: "rr-indicators" | "rr-signals";
  compute(input: I, weights: W): R;
}
