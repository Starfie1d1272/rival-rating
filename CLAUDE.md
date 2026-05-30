# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 常用命令

```bash
pnpm test            # 运行全部测试（vitest run）
pnpm test:watch      # 监听模式
pnpm typecheck       # tsc --noEmit 类型检查

# 运行单个测试文件
pnpm vitest run src/rr/compute.test.ts
pnpm vitest run src/prism/zscore.test.ts
```

## 架构

这是一个**纯计算库**，无框架依赖，无副作用。输入 `RRIndicators`，输出 RR 标量和 PRISM 八维画像。

```
RRIndicators（Layer 0，由上游 RivalHub 填充）
         │
   ┌─────┴──────┐
 RR 标量      PRISM 八维画像
 单人计算      必须批量（cohort 级 z-score）
```

**关键约束：PRISM 必须批量计算。** 八维百分位依赖赛季内全体选手做 z-score，不能单人单场计算。RR 标量可单人计算，最后用联赛均值锚定（`computeLeagueMean` → 整体乘 `1/mean`）。

### 目录结构

| 路径 | 职责 |
|---|---|
| `src/types/indicators.ts` | `RRIndicators` — 所有原始信号，两个引擎的共同输入 |
| `src/types/rr.ts` | RR 权重 schema + 计算结果类型 |
| `src/types/prism.ts` | PRISM 权重 schema + 八维枚举 + 结果类型 |
| `src/rr/compute.ts` | `computeRR` / `computeLeagueMean` |
| `src/prism/compute.ts` | `computePrism` / `rrToPercentile` |
| `src/prism/extract.ts` | `extractAxisScore` — 从 indicators 按 SignalConfig[] 加权提取轴分 |
| `src/prism/zscore.ts` | z-score、冷启动收缩、百分位工具函数 |
| `src/weights/rr-v1.json` | RR Layer 1 系数（当前未用真实数据校准） |
| `src/weights/prism-v1.json` | PRISM 八维 α 值 + 信号配置 |

### 权重版本机制

所有系数外置到版本化 JSON，**公式形状稳定，调参只改 JSON**。版本格式：`rr-X.Y` / `prism-X.Y`。

当前状态（v0.1.0 脚手架）：
- RR Layer 1：HLTV 2.0 逆向公式作为过渡基线，eco 乘子全 1.0（待 ~50 张图校准后激活）
- RR Layer 2（Round Swing）：`roundSwingCoef=0`，透明关闭，待 ~1000 张图后开启
- PRISM 冷启动收缩常数：`coldStartK=4`，待真实 cohort 验证

### PRISM 双编码设计

- **形状（轴半径）= 风格指纹**：α 控制风格/水平配比（α=0.85 狙击轴 ≈ 纯风格，α=0.20 生存轴 ≈ 纯水平）
- **颜色 = RR 百分位（水平）**：两个维度独立编码，互不干扰
- α 参数在 `prism-v1.json` 每根轴里配置，修改无需改代码

### 生态关系

- 上游：[cs2-demo-format](https://github.com/Starfie1d1272/cs2-demo-format) — demo 导出格式，`RRIndicators` 的数据来源
- 消费方：[RivalHub](https://github.com/Starfie1d1272/RivalHub) — 解析 demo → 适配 `RRIndicators` → 调用本库 → 展示

本库只做计算，不感知数据来源和去向。

## TypeScript 配置

`strict: true` + `exactOptionalPropertyTypes` + `noUncheckedIndexedAccess`，索引访问结果为 `T | undefined`，需显式处理。`RRIndicators` 中部分字段为 `number | null`（暂无数据的占位），对应权重设 0 即可无效化。
