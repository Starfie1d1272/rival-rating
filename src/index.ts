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

// ─── 默认权重（直接 import JSON 用）──────────────────────────────────────
// 调用方按需 import：
//   import rrWeightsV1   from "@rivalhub/rival-rating/src/weights/rr-v1.json" assert { type: "json" };
//   import prismWeightsV1 from "@rivalhub/rival-rating/src/weights/prism-v1.json" assert { type: "json" };
