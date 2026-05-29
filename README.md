# rival-rating

> **RR (Rival Rating)** 绝对刻度标量 + **PRISM** 八维风格雷达
> 一套独立的 CS2 战术射击选手评分引擎。

[![version](https://img.shields.io/badge/version-0.1.0-orange)](./package.json)
[![status](https://img.shields.io/badge/weights-uncalibrated-yellow)](#权重版本与状态)

---

## 这是什么

`rival-rating` 是一个**纯函数评分库**：输入一名选手的比赛指标（击杀、KAST、ADR、首杀、残局……），
输出两样东西——

1. **RR 标量**：一个绝对刻度的数字，`1.00` = 联赛均值。跨赛季、跨比赛可比。
2. **PRISM 八维画像**：一张风格指纹雷达图，形状表达打法风格，颜色表达水平高低。

它**不依赖任何框架**（无 React / 数据库 / 网络），只做计算。所有可调参数外置在版本化的 JSON
权重文件里，调参不改代码。

> 评分体系**独立设计**，不复刻 HLTV——借鉴其思路（KAST/Impact/Round Swing），但维度划分、
> 权重结构、着色方案均为自有设计。

---

## 安装

```bash
pnpm add @rivalhub/rival-rating
```

```ts
import { computeRR, computePrism } from "@rivalhub/rival-rating";
import rrWeights from "@rivalhub/rival-rating/weights/rr-v1.json";

const rr = computeRR(indicators, rrWeights);     // → { rr: 1.07, breakdown: {...} }
const prism = computePrism(cohort, prismWeights); // → 每名选手的八维 + 百分位着色
```

---

## 架构

```
demo / 数据源  →  RRIndicators（指标层 Layer 0，由调用方填充）
                       │
            ┌──────────┴───────────┐
         RR 标量                 PRISM 八维画像
       绝对刻度                 赛季内 z-score
     1.00 = 联赛均值            风格指纹 + 水平着色
     跨赛季可比                 冷启动收缩
```

**关键设计：PRISM 是 cohort 级的。** 八维靠赛季内全体选手的 z-score 标准化得出，
因此**必须批量计算**（不能单场单人算）。RR 标量则可单人计算，再用联赛均值锚定。

### RR 标量

| 层级 | 算法 | 状态 |
|---|---|---|
| Layer 1 | 上下文加权（eco 乘子 + 情境权重） | ✅ 基础公式已实现，eco 乘子待真实数据校准 |
| Layer 2 | Round Swing / WPA（逐杀 ΔP） | 🔒 待 ~1000 张图样本后开启 |

### PRISM 八维

| 维 | 说明 | α（风格比重） |
|---|---|---|
| 火力 Firepower | 纯输出，不看生存 | 0.40 |
| 首杀 Opening | 首杀对枪赢下来 | 0.60 |
| 残局 Clutch | 1vX 残局胜率 | 0.55 |
| 狙击 Sniping | AWP 风格标签 | 0.85 |
| 生存 Survival | 活下来 / 低死亡率 | 0.20 |
| 道具 Utility | 投掷物贡献 | 0.70 |
| 补枪 Trading | 补枪、护队友 | 0.60 |
| 突破 Entry | 开路尖刀，首先暴露 | 0.70 |

**双编码**：形状（轴半径）= 风格，颜色 = RR 百分位（水平）。每个维度的 α 决定它
偏「风格」还是偏「水平」——狙击轴 α=0.85（纯风格标签），生存轴 α=0.20（主要看水平）。

---

## 权重版本与状态

| 文件 | 内容 | 状态 |
|---|---|---|
| `weights/rr-v1.json` | RR Layer 1 基础系数（HLTV 2.0 逆向公式作为过渡基线） | ⚠️ 未用真实数据校准 |
| `weights/prism-v1.json` | PRISM 八维 α 值 + 信号配置 | ⚠️ z-score cohort 待真实样本验证 |

> **当前为 0.1.0 脚手架版**：算法骨架与测试齐备，但权重尚未经真实赛事数据校准。
> 待收集足量样本完成首次 cohort 校准后升至 0.2.0，权重验证稳定后才考虑 1.0.0。

所有数字外置，替换系数只需换 JSON 并升版本号，公式形状保持稳定。

---

## 开发

```bash
pnpm install
pnpm test          # vitest，20+ 用例
pnpm tsc --noEmit  # 类型检查
```

---

## 生态关系

| 仓库 | 角色 |
|---|---|
| [cs2-demo-format](https://github.com/Starfie1d1272/cs2-demo-format) | demo 导出格式契约（RRIndicators 的上游数据来源） |
| [RivalHub](https://github.com/Starfie1d1272/RivalHub) | 消费方：解析 demo → 适配为 RRIndicators → 调用本库 → 展示 |

本库只负责计算，**不感知**数据从哪来、算完往哪去。RivalHub 在适配层
（`to-rr-indicators.ts`）把 demo 数据翻译成 `RRIndicators`，再喂给本库。

### OCR 外部字段（保留在 RivalHub，不属于本库）

- `ratingPro` — 完美平台 RatingPro（OCR 摄入的第三方数据）
- `we` — 完美平台 RS（OCR 摄入）

这两个是「第三方摄入」，不挂 RR 品牌，原样保留在 RivalHub，**与 RR/PRISM 互不干扰**。
