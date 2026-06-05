/**
 * value-accounts-v2-lite — 价值账户 RR 模型
 *
 * 本体论：选手价值不是"统计量的线性组合"（HLTV 路线），而是五个语义正交账户
 * 的加总——Combat / Trade / Clutch / Objective / Utility。Economy 不是账户，
 * 而是修正击杀价值的 context 乘子。
 *
 * 形状（v1-lite，线性、透明）：
 *   RR_raw = intercept + Σ_account accountWeight · accountRaw
 *   每个 accountRaw 是该账户信号的 per-round 加权和；
 *   Combat 的击杀项再乘一个 context 乘子（经济差 × 人数差）。
 *
 * 复杂度刻意压在这一版很低：价值在"账户切法"（本体论），不在花哨数学。
 * 真正的精度升级（情境 WPA、职业数据训练）留给 v2-full / v3，届时换 model 而非调系数。
 *
 * 校准现状（务必知情）：当前 JSON 里的权重是"凭游戏理解的先验"，未经真实数据校准。
 * V2 格式让信号更丰富 ≠ 权重更可信。可信度仍依赖：① 先验；② ~50 场赛季数据相对
 * 校准 + 联赛锚定；③ 用 ratingPro 等做对照验证。详见 docs/rr-v2.md 的校准方法论。
 */

import type {
  AccountSignalsV2,
  CombatSignals,
  CombatWeights,
  ClutchSignals,
  ClutchWeights,
  RRAccountKey,
  RRModel,
  RRResultV2,
  ValueAccountsWeights,
} from "../../types/accounts.js";
import valueAccountsWeights from "../../weights/rr-value-accounts-v2-lite.json" with { type: "json" };

/**
 * 计算单名选手单张地图的 value-accounts RR（锚定前）。
 *
 * 纯函数，无副作用。rounds<=0 时返回中性基线 1.0。
 */
export function computeValueAccountsRR(
  sig: AccountSignalsV2,
  w: ValueAccountsWeights,
): RRResultV2 {
  if (sig.rounds <= 0) {
    return zeroResult(w.version);
  }
  const r = sig.rounds;

  // ── Combat ─────────────────────────────────────────────────────────────
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

  // ── Trade ──────────────────────────────────────────────────────────────
  const t = sig.trade;
  const untradedDeaths = Math.max(0, t.deaths - t.tradedDeaths);
  const tradeRaw =
    w.trade.tradeKillWeight * (t.tradeKills / r) +
    w.trade.tradedDeathWeight * (t.tradedDeaths / r) +
    w.trade.untradedDeathPenalty * (untradedDeaths / r);

  // ── Clutch（实际结果 − 静态期望）─────────────────────────────────────────
  const clutchRaw = (w.clutch.winValueWeight * clutchExcess(sig.clutch, w.clutch)) / r;

  // ── Objective ──────────────────────────────────────────────────────────
  const o = sig.objective;
  const objectiveRaw =
    w.objective.plantWeight * (o.plants / r) +
    w.objective.defuseWeight * (o.defuses / r) +
    w.objective.plantConvertedBonus * ((o.plantsConverted ?? 0) / r);

  // ── Utility ────────────────────────────────────────────────────────────
  const u = sig.utility;
  const utilityRaw =
    w.utility.flashAssistWeight * (u.flashAssists / r) +
    w.utility.enemyFlashSecWeight * (u.enemyFlashDurationSeconds / r) +
    w.utility.teamFlashPenalty * ((u.teamFlashDurationSeconds ?? 0) / r) +
    w.utility.utilityDamageWeight * (u.utilityDamage / r);

  // ── 账户贡献（已乘 accountWeight）─────────────────────────────────────────
  const accounts: Record<RRAccountKey, number> = {
    combat: w.accountWeights.combat * combatRaw,
    trade: w.accountWeights.trade * tradeRaw,
    clutch: w.accountWeights.clutch * clutchRaw,
    objective: w.accountWeights.objective * objectiveRaw,
    utility: w.accountWeights.utility * utilityRaw,
  };

  const rrRaw =
    w.intercept +
    accounts.combat +
    accounts.trade +
    accounts.clutch +
    accounts.objective +
    accounts.utility;

  const rr = Math.max(w.clamp.min, Math.min(w.clamp.max, rrRaw));

  return {
    rr,
    rrRaw,
    weightsVersion: w.version,
    model: "value-accounts-v2-lite",
    accounts,
    combatContextFactor: contextFactor,
  };
}

/**
 * 联赛均值（用于锚定到 1.00）。调用方将每名选手 rr 再乘 (1.0 / mean) 完成归一。
 * 与 RRResult 版的 computeLeagueMean 同语义，独立一份避免跨类型耦合。
 */
export function computeLeagueMeanV2(results: RRResultV2[]): number {
  if (results.length === 0) return 1.0;
  const sum = results.reduce((acc, x) => acc + x.rr, 0);
  return sum / results.length;
}

/** 可插拔模型描述符，供上游按 id 路由 / 按 inputKind 校验。 */
export const valueAccountsV2LiteModel: RRModel<
  AccountSignalsV2,
  ValueAccountsWeights,
  RRResultV2
> = {
  id: "value-accounts-v2-lite",
  version: valueAccountsWeights.version,
  inputKind: "account-signals-v2",
  compute: computeValueAccountsRR,
};

// ─── 内部工具 ───────────────────────────────────────────────────────────────

/**
 * Combat 击杀项的 context 乘子 = 经济差乘子 × 人数差乘子。
 * 任一分桶为 null（analysis 仓库未实现）则该维度取 1.0，整体优雅降级。
 * 乘子只作用于"已分类"的击杀（除以桶内总和，而非 kills），避免分桶不完整时把乘子拖向 0。
 */
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

/**
 * 残局净超额 Σ(won − count·expectation)。
 * 赢 1v3 贡献 +(1 − 0.10)，输 1v3 贡献 −0.10，自动实现"赢难局加分多、输难局扣分少"。
 */
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

function zeroResult(version: string): RRResultV2 {
  return {
    rr: 1.0,
    rrRaw: 1.0,
    weightsVersion: version,
    model: "value-accounts-v2-lite",
    accounts: { combat: 0, trade: 0, clutch: 0, objective: 0, utility: 0 },
    combatContextFactor: 1,
  };
}
