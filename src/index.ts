/**
 * @rivalhub/rival-rating — 公开 API
 *
 * RR（Rival Rating）标量引擎 + PRISM 八维画像
 */

// ─── 类型 ─────────────────────────────────────────────────────────────────
export type { RRIndicators } from "./types/indicators.js";
export type { RRWeights, RRResult, RRAnchor, RREcoMultipliers } from "./types/rr.js";
export type {
  AccountSignalsV2,
  CombatSignals,
  TradeSignals,
  ClutchSignals,
  ObjectiveSignals,
  UtilitySignals,
  RRAccountKey,
  RRResultV2,
  ValueAccountsWeights,
  CombatWeights,
  TradeWeights,
  ClutchWeights,
  ObjectiveWeights,
  UtilityWeights,
  CohortAccountWeights,
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

// ─── RR 标量 ──────────────────────────────────────────────────────────────
export { computeRR, computeLeagueMean } from "./rr/compute.js";

// ─── RR v2：价值账户模型 + 可插拔 RRModel ─────────────────────────────────
export {
  computeValueAccountsRR,
  computeLeagueMeanV2,
  valueAccountsV2LiteModel,
} from "./rr/models/value-accounts-v2-lite.js";
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
//   import { rrWeightsV1 } from "@rivalhub/rival-rating";
//   const weights = rrWeightsV1 as unknown as RRWeights;
// JSON 内含 `_comment`/`_desc` 等注释字段,故保持裸导出由调用方断言,
// 不在此处强标 RRWeights/PrismWeights（避免 anchor.mode 等 union 收窄摩擦）。
export { default as rrWeightsV1 } from "./weights/rr-v1.json" with { type: "json" };
export { default as rrValueAccountsV2Lite } from "./weights/rr-value-accounts-v2-lite.json" with { type: "json" };
export { default as prismWeightsV1 } from "./weights/prism-v1.json" with { type: "json" };
