import { describe, it, expect } from "vitest";
import { hltv2BaselineWeightsV1, prismWeightsV1, rrSixAccountWeightsV1 } from "./index.js";

describe("weights JSON 导出契约", () => {
  it("hltv2BaselineWeightsV1 可导入且含 version", () => {
    expect((hltv2BaselineWeightsV1 as { version: string }).version).toBe("hltv-2-baseline-1.0");
  });
  it("rrSixAccountWeightsV1 可导入且含 version", () => {
    expect((rrSixAccountWeightsV1 as { version: string }).version).toBe("rr-six-accounts-1.0");
  });
  it("prismWeightsV1 可导入且含 version", () => {
    expect((prismWeightsV1 as { version: string }).version).toBe("prism-1.1");
  });
});
