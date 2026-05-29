import { describe, it, expect } from "vitest";
import { zScoreAll, coldStartShrink, normalCDF, zToPercentile } from "./zscore.js";

describe("zScoreAll", () => {
  it("标准化后均值≈0、标准差≈1", () => {
    const z = zScoreAll([1, 2, 3, 4, 5]);
    const mean = z.reduce((a, b) => a + b, 0) / z.length;
    const std = Math.sqrt(z.reduce((a, b) => a + b * b, 0) / z.length);
    expect(Math.abs(mean)).toBeLessThan(1e-10);
    expect(std).toBeCloseTo(0.894, 2); // 样本标准差 n-1
  });

  it("全相同值返回全 0", () => {
    expect(zScoreAll([3, 3, 3])).toEqual([0, 0, 0]);
  });

  it("单个元素返回 [0]", () => {
    expect(zScoreAll([5])).toEqual([0]);
  });
});

describe("coldStartShrink", () => {
  it("n=0 时完全收缩到 0", () => {
    expect(coldStartShrink(2.0, 0, 4)).toBe(0);
  });

  it("n>>k 时几乎不收缩", () => {
    expect(coldStartShrink(1.0, 1000, 4)).toBeCloseTo(1.0, 2);
  });

  it("n=k 时收缩一半", () => {
    expect(coldStartShrink(1.0, 4, 4)).toBe(0.5);
  });

  it("k=0 时不收缩", () => {
    expect(coldStartShrink(1.5, 1, 0)).toBe(1.5);
  });
});

describe("normalCDF", () => {
  it("z=0 → 0.5", () => {
    expect(normalCDF(0)).toBeCloseTo(0.5, 3);
  });

  it("z=1.96 → ≈0.975", () => {
    expect(normalCDF(1.96)).toBeCloseTo(0.975, 2);
  });

  it("z=-1.96 → ≈0.025", () => {
    expect(normalCDF(-1.96)).toBeCloseTo(0.025, 2);
  });
});

describe("zToPercentile", () => {
  it("大批次用经验排名", () => {
    const cohort = [-2, -1, 0, 1, 2];
    // z=0 在中间，应在 60 百分位（3/5 * 100）
    expect(zToPercentile(0, cohort)).toBeCloseTo(60, 0);
  });

  it("小批次退化到正态 CDF，z=0 → 50", () => {
    expect(zToPercentile(0, [0, 1])).toBeCloseTo(50, 0);
  });
});
