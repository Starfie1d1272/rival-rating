import { describe, it, expect } from "vitest";
import { rrWeightsV1, prismWeightsV1 } from "./index.js";

describe("weights JSON 导出契约", () => {
  it("rrWeightsV1 可导入且含 version", () => {
    expect((rrWeightsV1 as { version: string }).version).toBe("rr-1.0");
  });
  it("prismWeightsV1 可导入且含 version", () => {
    expect((prismWeightsV1 as { version: string }).version).toBe("prism-1.0");
  });
});
