/**
 * hltv-linear-v1 — 把现有 computeRR 包成 RRModel 描述符。
 *
 * 这套（HLTV 2.0 逆向线性公式）从"唯一的 RR 实现"降级为"众多估值器里的一个"，
 * 作为 v2 价值账户模型的 baseline / 对照组保留，不删除。
 */

import type { RRIndicators } from "../../types/indicators.js";
import type { RRWeights, RRResult } from "../../types/rr.js";
import type { RRModel } from "../../types/accounts.js";
import { computeRR } from "../compute.js";

export const hltvLinearV1Model: RRModel<RRIndicators, RRWeights, RRResult> = {
  id: "hltv-linear-v1",
  version: "hltv-2-baseline-1.0",
  inputKind: "rr-indicators",
  compute: computeRR,
};
