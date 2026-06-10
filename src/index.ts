/**
 * @rivalhub/rival-rating — 公开 API
 *
 * RR（Rival Rating）标量引擎 + PRISM 八维画像
 */

// ─── 类型 ─────────────────────────────────────────────────────────────────
export type { RRIndicators } from "./types/indicators.js";
export type { RRWeights, RRResult, RRAnchor, RREcoMultipliers } from "./types/rr.js";
export type {
  CombatSignals,
  TradeSignals,
  MapControlSignals,
  ClutchSignals,
  ObjectiveSignals,
  UtilitySignals,
  RRAccountKey,
  RRSignals,
  RRSixAccountResult,
  RRSixAccountWeights,
  CombatWeights,
  TradeWeights,
  MapControlWeights,
  ClutchWeights,
  ObjectiveWeights,
  UtilityWeights,
  RRModel,
} from "./types/accounts.js";
export { RR_ACCOUNTS } from "./types/accounts.js";
export type {
  PrismWeights,
  PrismAxisKey,
  PrismAxisConfig,
  PrismAxisResult,
  PrismResult,
  SignalConfig,
} from "./types/prism.js";
export { PRISM_AXES, PRISM_AXIS_ORDER } from "./types/prism.js";

// ─── HLTV 2.0 baseline（盒分对照组，保留 computeRR 兼容命名）───────────────
export { computeRR, computeLeagueMean } from "./rr/compute.js";

// ─── RR 主模型：六账户 + 可插拔 RRModel ───────────────────────────────────
export {
  computeRRSixAccounts,
  computeRRSixAccountMean,
  rrSixAccountsModel,
} from "./rr/models/six-accounts.js";
export { hltvLinearV1Model } from "./rr/models/hltv-linear-v1.js";

// ─── RR v2：cohort 平衡（标准化 + 残差化，赛季/单场通用）──────────────────
export { computeCohortAccountsRR } from "./rr/models/cohort-accounts.js";
export type { CohortAccountResult, CohortAccountsOptions } from "./rr/models/cohort-accounts.js";

// ─── RR v2：固定职业基准归一化（单 demo 绝对评分，1.0 = 职业平均）─────────
export {
  computeFrozenProBaselineRR,
  computeFrozenProBaselineBatch,
} from "./rr/models/frozen-pro-baseline.js";
export type { ProBaselineConfig, ProBaselineAccount } from "./rr/models/frozen-pro-baseline.js";

// ─── PRISM 画像 ───────────────────────────────────────────────────────────
export { computePrism, rrToPercentile } from "./prism/compute.js";
export type { PrismComputeInput } from "./prism/compute.js";
export { zScoreAll, coldStartShrink, zToPercentile, normalCDF } from "./prism/zscore.js";
export { extractAxisScore } from "./prism/extract.js";

// ─── 默认权重 ─────────────────────────────────────────────────────────────
// 直接命名导出 JSON,消费方按需断言类型：
//   import { hltv2BaselineWeightsV1 } from "@rivalhub/rival-rating";
//   const weights = hltv2BaselineWeightsV1 as unknown as RRWeights;
// JSON 内含 `_comment`/`_desc` 等注释字段,故保持裸导出由调用方断言,
// 不在此处强标 RRWeights/PrismWeights（避免 anchor.mode 等 union 收窄摩擦）。
export { default as hltv2BaselineWeightsV1 } from "./weights/hltv-2-baseline-v1.json" with { type: "json" };
export { default as rrSixAccountWeightsV1 } from "./weights/rr-six-accounts-v1.json" with { type: "json" };
export { default as rrSixAccountProBaselineV0 } from "./weights/rr-six-account-pro-baseline-v0.json" with { type: "json" };
export { default as prismWeightsV1 } from "./weights/prism-v1.json" with { type: "json" };
