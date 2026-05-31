/**
 * AccountSignalsV2 — 价值账户证据层（RR v2 的输入契约）
 *
 * 设计立场：
 *  - 这一层只装"事实证据"，不装"价值判断"。一次击杀值多少分由模型（权重）决定，
 *    这里只如实记录"发生了什么、在什么上下文里发生"。
 *  - 由上游 cs2-demo-analysis-kit 从 V2 demo 事件重建后填充；本库只消费。
 *  - 五个账户：Combat / Trade / Clutch / Objective / Utility。
 *    Economy 不是账户，而是修正击杀价值的 context（见 Combat 的分桶字段）。
 *  - `null` = analysis 仓库 v1 尚未实现该项。模型遇到 null 一律降级（乘子取 1.0 /
 *    项取 0），不报错。所以契约可以面向 v2-full 设计，却能优雅退化到 v2-lite。
 *  - 所有计数/求和都是"单张 demo、单名选手"的原始量；per-round 归一由模型用 `rounds` 做。
 */

/** 五大价值账户键（顺序即默认展示顺序） */
export const RR_ACCOUNTS = [
  "combat",
  "trade",
  "clutch",
  "objective",
  "utility",
] as const;
export type RRAccountKey = (typeof RR_ACCOUNTS)[number];

// ─── Combat：决斗 / 输出账户 ────────────────────────────────────────────────

export interface CombatSignals {
  kills: number;
  deaths: number;
  assists: number;
  /** 有效伤害（healthDamage，已按剩余血量 cap），不是 raw damage */
  effectiveDamage: number;
  openingKills: number;
  openingDeaths: number;
  /** 多杀回合数（按当回合击杀数归类，互斥） */
  multiKills: { two: number; three: number; four: number; five: number };
  headshotKills: number;
  /** 穿墙/穿烟击杀（锐利度信号）；null = 未实现 */
  wallbangKills: number | null;

  // ── context 分桶（用于击杀价值乘子；任一为 null 则该维度乘子取 1.0）──
  /**
   * 按"击杀者 vs 被击杀者本回合装备价值差"对击杀分桶：
   *  - disadvantage：击杀者更穷（以弱打强 / upset，应加权）
   *  - even：装备相近
   *  - advantage：击杀者更富（以强凌弱 / 刷分，应降权）
   * 三桶之和 ≤ kills（未分类的击杀不计入，乘子只作用于已分类部分）。
   * null = analysis 仓库尚未做按击杀 tick 的经济重建。
   */
  killsByBuyDelta: { disadvantage: number; even: number; advantage: number } | null;
  /**
   * 按"击杀发生时本方存活人数差"对击杀分桶（需用击杀顺序重建存活数）：
   *  - manDown：本方人数劣势时击杀（救场，应加权）
   *  - even：人数均势
   *  - manUp：本方人数优势时击杀（顺风，可降权）
   * null = analysis 仓库尚未做存活数重建。
   */
  killsByManState: { manDown: number; even: number; manUp: number } | null;
}

// ─── Trade：交易 / 补枪账户 ─────────────────────────────────────────────────

export interface TradeSignals {
  /** 补掉敌人（为刚阵亡的队友复仇） */
  tradeKills: number;
  /** 自己阵亡后被队友及时补回 */
  tradedDeaths: number;
  /** 自己阵亡总数（用于推导"未被交易死亡" = deaths - tradedDeaths） */
  deaths: number;
  /** 首死中被交易的次数（entry 选手的"生命价值"）；null = 未实现 */
  tradedOpeningDeaths: number | null;
}

// ─── Clutch：残局账户 ───────────────────────────────────────────────────────

/**
 * 残局只记"打了多少次、赢了多少次"，按对手数分桶。
 * "赢 1v3 比赢 1v1 值钱"由模型的静态期望表（expectation）决定，证据层不打分。
 */
export interface ClutchSignals {
  vsOne: { count: number; won: number };
  vsTwo: { count: number; won: number };
  vsThree: { count: number; won: number };
  vsFour: { count: number; won: number };
  vsFive: { count: number; won: number };
}

// ─── Objective：目标账户 ────────────────────────────────────────────────────

export interface ObjectiveSignals {
  plants: number;
  defuses: number;
  /** 下包后本回合最终获胜的次数（post-plant 转化价值）；null = 未实现 */
  plantsConverted: number | null;
}

// ─── Utility：功能 / 道具账户 ───────────────────────────────────────────────

export interface UtilitySignals {
  flashAssists: number;
  /** 致盲敌方总秒数 */
  enemyFlashDurationSeconds: number;
  /** 致盲己方队友总秒数（负向风险项）；null = 未实现 */
  teamFlashDurationSeconds: number | null;
  /** 道具有效伤害（HE / molly 等） */
  utilityDamage: number;
}

// ─── 顶层契约 ───────────────────────────────────────────────────────────────

export interface AccountSignalsV2 {
  steamId64: string;
  /** 该选手在这张 demo 实际参与的正式回合数（per-round 归一分母） */
  rounds: number;
  /** 派生方版本号（如 "cs2-demo-analysis-kit/0.3"），仅用于排错 */
  sourceVersion?: string;

  combat: CombatSignals;
  trade: TradeSignals;
  clutch: ClutchSignals;
  objective: ObjectiveSignals;
  utility: UtilitySignals;
}

// ─── value-accounts 模型权重 schema ─────────────────────────────────────────

export interface CombatWeights {
  /** 作用于 KPR */
  killWeight: number;
  /** 作用于 DPR（通常为负） */
  deathWeight: number;
  /** 作用于有效伤害 per-round */
  damageWeight: number;
  /** 作用于 (openingKills - openingDeaths) per-round */
  openingWeight: number;
  /** 作用于多杀回合率 */
  multiKillWeight: number;
  /** 作用于爆头击杀 per-round（默认 0：爆头是风格非价值，留作调参） */
  headshotWeight: number;
  /** 作用于穿墙击杀 per-round */
  wallbangWeight: number;
  /** 经济差乘子：以弱打强 >1，以强凌弱 <1 */
  buyDelta: { disadvantageMultiplier: number; advantageMultiplier: number };
  /** 人数差乘子：人数劣势击杀 >1，人数优势击杀 <1 */
  manState: { manDownMultiplier: number; manUpMultiplier: number };
}

export interface TradeWeights {
  tradeKillWeight: number;
  tradedDeathWeight: number;
  /** 未被交易死亡的惩罚（通常为负） */
  untradedDeathPenalty: number;
}

export interface ClutchWeights {
  /** 各局面的静态获胜期望（baseline），用于"实际结果 − 期望" */
  expectation: {
    vsOne: number;
    vsTwo: number;
    vsThree: number;
    vsFour: number;
    vsFive: number;
  };
  /** 作用于残局净超额（Σ(won − count·expectation)）per-round 后的系数 */
  winValueWeight: number;
}

export interface ObjectiveWeights {
  plantWeight: number;
  defuseWeight: number;
  /** 下包转化获胜的额外奖励 per-round */
  plantConvertedBonus: number;
}

export interface UtilityWeights {
  flashAssistWeight: number;
  /** 作用于致盲敌方秒数 per-round */
  enemyFlashSecWeight: number;
  /** 作用于致盲队友秒数 per-round（通常为负） */
  teamFlashPenalty: number;
  utilityDamageWeight: number;
}

export interface ValueAccountsWeights {
  /** 格式：rr-value-accounts-v2-lite-X.Y */
  version: string;
  description?: string;
  /** RR 基线截距（让平均水平 statline 的原始分 ≈ 1.0；锚定前的粗校准） */
  intercept: number;
  /** 五账户在 RR 中的相对权重 */
  accountWeights: Record<RRAccountKey, number>;
  combat: CombatWeights;
  trade: TradeWeights;
  clutch: ClutchWeights;
  objective: ObjectiveWeights;
  utility: UtilityWeights;
  clamp: { min: number; max: number };
  anchor: { mode: "league_mean" | "pro_mean"; note?: string };
}

// ─── 计算结果 ───────────────────────────────────────────────────────────────

export interface RRResultV2 {
  /** 最终 RR 分（已 clamp，未锚定；锚定由 computeLeagueMeanV2 + 调用方完成） */
  rr: number;
  /** clamp 前的原始分（调试用） */
  rrRaw: number;
  weightsVersion: string;
  /** 模型标识，便于存储/路由区分 */
  model: string;
  /** 各账户对 RR 的加权贡献（已乘 accountWeight；可解释性） */
  accounts: Record<RRAccountKey, number>;
  /** Combat 击杀项的 context 乘子（1.0 = context 未生效 / 已降级） */
  combatContextFactor: number;
}

// ─── 可插拔模型接口 ─────────────────────────────────────────────────────────

/**
 * RRModel — 让"估值范式"可替换的一等抽象。
 *
 * hltv-linear-v1（吃 RRIndicators）和 value-accounts-v2-lite（吃 AccountSignalsV2）
 * 都实现这个接口，通过 `id` 路由、`inputKind` 校验上游喂的是哪种契约。
 */
export interface RRModel<I, W, R> {
  /** 稳定标识，用于存储与路由，如 "value-accounts-v2-lite" */
  id: string;
  /** 权重版本（取自 weights JSON 的 version） */
  version: string;
  /** 该模型需要的输入契约类型 */
  inputKind: "rr-indicators" | "account-signals-v2";
  compute(input: I, weights: W): R;
}
