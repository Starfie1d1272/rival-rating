/**
 * RR six-account model.
 *
 * RR is the transparent main rating model:
 * Combat / Trade / MapControl / Utility / Clutch / Objective.
 */

import type {
  ClutchSignals,
  ClutchWeights,
  CombatSignals,
  CombatWeights,
  RRAccountKey,
  RRModel,
  RRSixAccountResult,
  RRSixAccountWeights,
  RRSignals,
} from "../../types/accounts.js";

export function computeRRSixAccounts(
  sig: RRSignals,
  w: RRSixAccountWeights,
): RRSixAccountResult {
  if (sig.rounds <= 0) {
    return zeroResult(w.version);
  }
  const r = sig.rounds;

  const c = sig.combat;
  const contextFactor = combatContextFactor(c, w.combat);
  const killTerm = w.combat.killWeight * (c.kills / r) * contextFactor;
  const combatRaw =
    killTerm +
    w.combat.deathWeight * (c.deaths / r) +
    w.combat.damageWeight * (c.effectiveDamage / r) +
    w.combat.openingWeight * ((c.openingKills - c.openingDeaths) / r) +
    w.combat.multiKillWeight *
      ((c.multiKills.two + c.multiKills.three + c.multiKills.four + c.multiKills.five) / r) +
    w.combat.headshotWeight * (c.headshotKills / r) +
    w.combat.wallbangWeight * ((c.wallbangKills ?? 0) / r);

  const t = sig.trade;
  const strategicIsolationDeaths = t.strategicIsolationDeaths ?? 0;
  const effectiveUntradedDeaths = Math.max(0, t.deaths - t.tradedDeaths - strategicIsolationDeaths);
  const tradeRaw =
    w.trade.tradeKillWeight * (t.tradeKills / r) +
    w.trade.tradedDeathWeight * (t.tradedDeaths / r) +
    w.trade.tradedOpeningDeathWeight * ((t.tradedOpeningDeaths ?? 0) / r) +
    w.trade.untradedDeathPenalty * (effectiveUntradedDeaths / r);

  const m = sig.mapControl;
  const mapControlRaw =
    w.mapControl.uniqueStrategicControlSecondsWeight *
      cappedPerRound(m.uniqueStrategicControlSeconds, r, w.mapControlNormalizers.uniqueStrategicControlSecondsPerRoundCap) +
    w.mapControl.contestedFrontierControlSecondsWeight *
      cappedPerRound(m.contestedFrontierControlSeconds, r, w.mapControlNormalizers.contestedFrontierControlSecondsPerRoundCap) +
    w.mapControl.routeDenialSecondsWeight *
      cappedPerRound(m.routeDenialSeconds, r, w.mapControlNormalizers.routeDenialSecondsPerRoundCap) +
    w.mapControl.teammateAdvanceUnitsWeight *
      cappedPerRound(m.teammateAdvanceUnits, r, w.mapControlNormalizers.teammateAdvanceUnitsPerRoundCap) +
    w.mapControl.firstControlEventsWeight *
      cappedPerRound(m.firstControlEvents, r, w.mapControlNormalizers.firstControlEventsPerRoundCap);

  const u = sig.utility;
  const utilityRaw =
    w.utility.flashAssistWeight *
      cappedPerRound(u.flashAssists, r, w.utilityNormalizers.flashAssistsPerRoundCap) +
    w.utility.effectiveEnemyFlashSecondsWeight *
      cappedPerRound(u.effectiveEnemyFlashSeconds, r, w.utilityNormalizers.effectiveEnemyFlashSecondsPerRoundCap) +
    w.utility.teamFlashSuppressionPenalty *
      cappedPerRound(u.teamFlashSuppressionSeconds, r, w.utilityNormalizers.teamFlashSuppressionSecondsPerRoundCap) +
    w.utility.smokeProtectedCrossingsWeight *
      cappedPerRound(u.smokeProtectedCrossings, r, w.utilityNormalizers.smokeProtectedCrossingsPerRoundCap) +
    w.utility.smokeSightlineDenialSecondsWeight *
      cappedPerRound(u.smokeSightlineDenialSeconds, r, w.utilityNormalizers.smokeSightlineDenialSecondsPerRoundCap) +
    w.utility.smokeIsolationSecondsWeight *
      cappedPerRound(u.smokeIsolationSeconds, r, w.utilityNormalizers.smokeIsolationSecondsPerRoundCap) +
    w.utility.incendiaryPathDelayUnitsWeight *
      cappedPerRound(u.incendiaryPathDelayUnits, r, w.utilityNormalizers.incendiaryPathDelayUnitsPerRoundCap) +
    w.utility.incendiaryDisplacementEventsWeight *
      cappedPerRound(u.incendiaryDisplacementEvents, r, w.utilityNormalizers.incendiaryDisplacementEventsPerRoundCap) +
    w.utility.utilityDamageWeight *
      cappedPerRound(u.utilityDamage, r, w.utilityNormalizers.utilityDamagePerRoundCap);

  const clutchAttempts =
    sig.clutch.vsOne.count +
    sig.clutch.vsTwo.count +
    sig.clutch.vsThree.count +
    sig.clutch.vsFour.count +
    sig.clutch.vsFive.count;
  const clutchShrink = clutchAttempts / (clutchAttempts + w.clutch.shrinkageK);
  const clutchRaw = (w.clutch.winValueWeight * clutchExcess(sig.clutch, w.clutch) * clutchShrink) / r;

  const o = sig.objective;
  const objectiveRaw =
    w.objective.plantWeight * (o.plants / r) +
    w.objective.defuseWeight * (o.defuses / r) +
    w.objective.plantConvertedBonus * ((o.plantsConverted ?? 0) / r);

  const accounts: Record<RRAccountKey, number> = {
    combat: w.score.scale * w.accountWeights.combat * combatRaw,
    trade: w.score.scale * w.accountWeights.trade * tradeRaw,
    mapControl: w.score.scale * w.accountWeights.mapControl * mapControlRaw,
    utility: w.score.scale * w.accountWeights.utility * utilityRaw,
    clutch: w.score.scale * w.accountWeights.clutch * clutchRaw,
    objective: w.score.scale * w.accountWeights.objective * objectiveRaw,
  };

  const rrRaw =
    w.score.base +
    accounts.combat +
    accounts.trade +
    accounts.mapControl +
    accounts.utility +
    accounts.clutch +
    accounts.objective;
  const rr = Math.max(w.clamp.min, Math.min(w.clamp.max, rrRaw));

  return {
    rr,
    rrRaw,
    weightsVersion: w.version,
    model: "rr-six-accounts",
    accounts,
    combatContextFactor: contextFactor,
  };
}

export function computeRRSixAccountMean(results: RRSixAccountResult[]): number {
  if (results.length === 0) return 1.0;
  return results.reduce((acc, x) => acc + x.rr, 0) / results.length;
}

export const rrSixAccountsModel: RRModel<RRSignals, RRSixAccountWeights, RRSixAccountResult> = {
  id: "rr-six-accounts",
  version: "rr-six-accounts-1.0",
  inputKind: "rr-signals",
  compute: computeRRSixAccounts,
};

function combatContextFactor(c: CombatSignals, w: CombatWeights): number {
  let factor = 1;

  if (c.killsByBuyDelta) {
    const b = c.killsByBuyDelta;
    const sum = b.disadvantage + b.even + b.advantage;
    if (sum > 0) {
      factor *=
        (b.disadvantage * w.buyDelta.disadvantageMultiplier +
          b.even +
          b.advantage * w.buyDelta.advantageMultiplier) /
        sum;
    }
  }

  if (c.killsByManState) {
    const m = c.killsByManState;
    const sum = m.manDown + m.even + m.manUp;
    if (sum > 0) {
      factor *=
        (m.manDown * w.manState.manDownMultiplier +
          m.even +
          m.manUp * w.manState.manUpMultiplier) /
        sum;
    }
  }

  return factor;
}

function clutchExcess(s: ClutchSignals, w: ClutchWeights): number {
  const e = w.expectation;
  return (
    s.vsOne.won - s.vsOne.count * e.vsOne +
    (s.vsTwo.won - s.vsTwo.count * e.vsTwo) +
    (s.vsThree.won - s.vsThree.count * e.vsThree) +
    (s.vsFour.won - s.vsFour.count * e.vsFour) +
    (s.vsFive.won - s.vsFive.count * e.vsFive)
  );
}

function zeroResult(version: string): RRSixAccountResult {
  return {
    rr: 1.0,
    rrRaw: 1.0,
    weightsVersion: version,
    model: "rr-six-accounts",
    accounts: { combat: 0, trade: 0, mapControl: 0, utility: 0, clutch: 0, objective: 0 },
    combatContextFactor: 1,
  };
}

function cappedPerRound(value: number | null, rounds: number, capPerRound: number): number {
  if (value === null || capPerRound <= 0 || rounds <= 0) return 0;
  return Math.max(0, Math.min(value / rounds, capPerRound)) / capPerRound;
}
