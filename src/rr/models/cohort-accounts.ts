/**
 * cohort-accounts — 跨选手的六账户 RR 平衡（赛季 / 单场 cohort 通用）
 *
 * 背景（55 场 ratingPro/WE 校准实证）：
 *  - 六账户的 raw 量级天然不同（combat 每回合发生，clutch/objective 稀有），
 *    `computeRRSixAccounts` 的线性相加里 combat 容易碾压其余账户。
 *  - 整体评分 ≈ combat（combat 单独 corr(ratingPro)=0.90）；非 combat 账户独立信号弱且与
 *    combat 共线（clutch standalone 0.46 但与 combat 共线 0.56）。
 *  - 残差化后，正交团队增量对 ratingPro/WE 的边际预测力 ≈ 0。
 *
 * 因此本函数：
 *  1. 恢复每账户未加权 raw（= 加权贡献 / accountWeight），跨选手 z-score。
 *  2. combat 作主干；其余账户**残差化**（减去 combat 能解释的部分，只留正交增量），
 *     度量"超出你 fragging 水平的团队贡献"，避免与 combat 双重计分。
 *  3. composite = w_combat·zc + Σ w_a·zr_a；scale 使离散度对齐 targetStd；anchor 到 1.0。
 *
 * 立场：combat 是数据强制的主干；非 combat 权重是**刻意的价值选择**（识别团队贡献），
 * 不是数据回归出来的。Rating 不做按选手场数的冷启动收缩——它是不变量，照实展示，
 * 由读者结合 mapCount 理解（冷启动收缩只用在 PRISM 画像，见 computePrism）。
 *
 * 纯函数，无副作用。
 */

import { computeRRSixAccounts } from "./six-accounts.js";
import { RR_ACCOUNTS } from "../../types/accounts.js";
import type { RRAccountKey, RRSixAccountWeights, RRSignals } from "../../types/accounts.js";

export interface CohortAccountResult {
  steamId64: string;
  /** 锚定后 RR，1.0 = cohort 均值；不做按选手场数的收缩。 */
  rr: number;
  /** composite（scale/anchor 前），调试用。 */
  rrRaw: number;
  /** 各账户对 RR 的平衡贡献（残差化后；Σ = rr − 1）。 */
  accounts: Record<RRAccountKey, number>;
}

export interface CohortAccountsOptions {
  /** 目标离散度（accountRR 的 std）。默认 0.2；调用方可传 std(rrV1) 对齐 HLTV 刻度。 */
  targetStd?: number;
}

export function computeCohortAccountsRR(
  signals: RRSignals[],
  weights: RRSixAccountWeights,
  opts: CohortAccountsOptions = {},
): CohortAccountResult[] {
  const n = signals.length;
  if (n === 0) return [];
  const w = weights.accountWeights;
  const results = signals.map((s) => computeRRSixAccounts(s, weights));

  // 1. per-account raw（= 加权贡献 / accountWeight），跨选手标准化
  const z = {} as Record<RRAccountKey, number[]>;
  for (const k of RR_ACCOUNTS) {
    z[k] = standardize(results.map((r) => (w[k] !== 0 ? r.accounts[k] / w[k] : 0)));
  }

  // 2. combat 主干；其余账户残差化（正交于 combat）
  const zc = z.combat;
  const used = { ...z } as Record<RRAccountKey, number[]>;
  for (const k of RR_ACCOUNTS) {
    if (k === "combat") continue;
    const slope = zc.reduce((acc, v, i) => acc + v * (z[k][i] ?? 0), 0) / n; // 两者已标准化 → 点积/n = 相关
    used[k] = standardize(z[k].map((v, i) => v - slope * (zc[i] ?? 0)));
  }

  // 3. composite + scale + anchor
  const composite = signals.map((_, i) => RR_ACCOUNTS.reduce((s, k) => s + w[k] * (used[k][i] ?? 0), 0));
  const targetStd = opts.targetStd ?? 0.2;
  const compStd = pstd(composite);
  const scale = compStd > 1e-9 ? targetStd / compStd : 0;

  return signals.map((sig, i) => {
    const accounts = {} as Record<RRAccountKey, number>;
    for (const k of RR_ACCOUNTS) accounts[k] = scale * w[k] * (used[k][i] ?? 0);
    return {
      steamId64: sig.steamId64,
      rr: Math.max(weights.clamp.min, 1 + scale * (composite[i] ?? 0)),
      rrRaw: composite[i] ?? 0,
      accounts,
    };
  });
}

// ─── 工具 ─────────────────────────────────────────────────────────────────

function mean(xs: number[]): number {
  return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0;
}

function pstd(xs: number[]): number {
  const m = mean(xs);
  return xs.length ? Math.sqrt(xs.reduce((a, x) => a + (x - m) ** 2, 0) / xs.length) : 0;
}

function standardize(xs: number[]): number[] {
  const m = mean(xs);
  const s = pstd(xs);
  return s > 1e-9 ? xs.map((x) => (x - m) / s) : xs.map(() => 0);
}
