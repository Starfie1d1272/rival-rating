/**
 * frozen-pro-baseline — 固定职业基准归一化（单 demo 绝对评分）
 *
 * 与 cohort-accounts 的关系（两套 normalizer strategy）：
 *  - `computeCohortAccountsRR`：**赛季相对**。需要一整批选手，跨人 z-score + 残差化，
 *    1.0 = 这批人的均值。不可移植、单 demo 无法用。
 *  - `computeFrozenProBaselineRR`（本文件）：**固定职业基准**。standardize 的 mean/std、
 *    残差化斜率、scale 全部从职业样本**冻结**进 `ProBaselineConfig`，于是**单个
 *    player-map 不需要 cohort 就能算出绝对、可移植的 RR**，1.0 = 职业平均。
 *
 * 数学（与 analysis 仓库 freeze-pro-baseline.ts 完全一致）：
 *   raw_a       = computeValueAccountsRR(sig).accounts[a] / accountWeight[a]
 *   z_a         = (raw_a − mean_a) / std_a                         // 用冻结的 mean/std
 *   used_combat = z_combat
 *   used_a      = (z_a − slope_a·z_combat) / sqrt(1 − slope_a²)    // 用冻结的残差化斜率
 *   composite   = Σ_a accountWeight_a · used_a
 *   RR          = max(clamp.min, 1 + scale · composite)            // 用冻结的 scale
 *
 * 立场：普通天梯玩家对着这把职业尺子量，均值自然落到 0.8–0.9（离职业还有多远），
 * 是有意为之的价值主张，不是 bug。友好化放展示层，模型只给绝对的职业基准分。
 *
 * 纯函数，无副作用。
 */

import { computeValueAccountsRR } from "./value-accounts-v2-lite.js";
import { RR_ACCOUNTS } from "../../types/accounts.js";
import type { AccountSignalsV2, RRAccountKey, ValueAccountsWeights } from "../../types/accounts.js";
import type { CohortAccountResult } from "./cohort-accounts.js";

/** 单个账户的冻结分布参数。 */
export interface ProBaselineAccount {
  /** 职业样本里该账户 raw 值的均值（standardize 用）。 */
  mean: number;
  /** 职业样本里该账户 raw 值的标准差（standardize 用）。 */
  std: number;
  /** 残差化斜率 = corr(z_account, z_combat)；combat 自身为 0（不残差化）。 */
  slope: number;
  /** 分布偏度（调试 / 判断是否需要尾部饱和），归一化不使用。 */
  skew?: number;
  /** raw 值的分位数表（21 点，0..1），为 v1 percentile-mapping 预留，归一化不使用。 */
  percentiles?: number[];
}

/** 冻结的职业基准配置（由 analysis 仓库 freeze-pro-baseline.ts 产出的 JSON）。 */
export interface ProBaselineConfig {
  version: string;
  /** 必须与计算 raw 时所用的 accountWeights 一致。 */
  accountWeights: Record<RRAccountKey, number>;
  clamp: { min: number; max: number };
  /** z-score / 残差化的数值稳定阈值。未填时使用 ValueAccountsWeights.cohort.epsilon。 */
  epsilon?: number;
  /** 全局缩放：std(rrV1) / std(composite)，对齐 HLTV 刻度。 */
  scale: number;
  /** 锚点，固定 1.0 = 职业平均。 */
  anchor: number;
  accounts: Record<RRAccountKey, ProBaselineAccount>;
}

/**
 * 用冻结职业基准给**单个** player-map 算绝对 RR。
 *
 * @param sig       单名选手单张 demo 的账户证据
 * @param weights   value-accounts 权重（accountWeights 必须与 baseline 一致）
 * @param baseline  冻结的职业基准配置
 */
export function computeFrozenProBaselineRR(
  sig: AccountSignalsV2,
  weights: ValueAccountsWeights,
  baseline: ProBaselineConfig,
): CohortAccountResult {
  const w = weights.accountWeights;
  const epsilon = baseline.epsilon ?? weights.cohort.epsilon;
  const result = computeValueAccountsRR(sig, weights);

  // 1. raw → z（用冻结的 mean/std）
  const z = {} as Record<RRAccountKey, number>;
  for (const k of RR_ACCOUNTS) {
    const raw = w[k] !== 0 ? result.accounts[k] / w[k] : 0;
    const p = baseline.accounts[k];
    z[k] = p.std > epsilon ? (raw - p.mean) / p.std : 0;
  }

  // 2. combat 主干；其余账户残差化（用冻结的斜率）
  const zc = z.combat;
  const used = {} as Record<RRAccountKey, number>;
  used.combat = zc;
  for (const k of RR_ACCOUNTS) {
    if (k === "combat") continue;
    const slope = baseline.accounts[k].slope;
    const denom = Math.sqrt(Math.max(epsilon, 1 - slope * slope));
    used[k] = (z[k] - slope * zc) / denom;
  }

  // 3. composite + scale + anchor
  const composite = RR_ACCOUNTS.reduce((s, k) => s + w[k] * used[k], 0);
  const accounts = {} as Record<RRAccountKey, number>;
  for (const k of RR_ACCOUNTS) accounts[k] = baseline.scale * w[k] * used[k];

  return {
    steamId64: sig.steamId64,
    rr: Math.max(baseline.clamp.min, baseline.anchor + baseline.scale * composite),
    rrRaw: composite,
    accounts,
  };
}

/** 批量便利封装：对多名选手分别套同一把冻结尺子（彼此独立，不构成 cohort）。 */
export function computeFrozenProBaselineBatch(
  signals: AccountSignalsV2[],
  weights: ValueAccountsWeights,
  baseline: ProBaselineConfig,
): CohortAccountResult[] {
  return signals.map((s) => computeFrozenProBaselineRR(s, weights, baseline));
}
