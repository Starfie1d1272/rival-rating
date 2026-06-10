import { describe, it, expect } from "vitest";
import {
  hltv2BaselineWeightsV1,
  prismWeightsV1,
  rrSixAccountProBaselineV0,
  rrSixAccountWeightsV1,
} from "./index.js";

describe("weights JSON 导出契约", () => {
  it("hltv2BaselineWeightsV1 可导入且含 version", () => {
    expect((hltv2BaselineWeightsV1 as { version: string }).version).toBe("hltv-2-baseline-1.0");
  });
  it("rrSixAccountWeightsV1 可导入且含 version", () => {
    expect((rrSixAccountWeightsV1 as { version: string }).version).toBe("rr-six-accounts-1.0");
  });
  it("rrSixAccountProBaselineV0 可导入且含 version", () => {
    expect((rrSixAccountProBaselineV0 as { version: string }).version).toBe(
      "pro_baseline_cs2_2026H1_52zips_raw_v0_provisional",
    );
  });
  it("prismWeightsV1 可导入且含 version", () => {
    expect((prismWeightsV1 as { version: string }).version).toBe("prism-1.1");
  });
});
