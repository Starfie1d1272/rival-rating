/**
 * @rivalhub/rival-rating — 公开 API
 *
 * RR（Rival Rating）标量引擎 + PRISM 八维画像
 */

// ─── 类型 ─────────────────────────────────────────────────────────────────
export type { RRIndicators } from "./types/indicators.js";
export type { RRWeights, RRResult, RRAnchor, RREcoMultipliers } from "./types/rr.js";
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
export { default as prismWeightsV1 } from "./weights/prism-v1.json" with { type: "json" };
