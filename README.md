# rival-rating

> **RR** 透明六账户评分 + **PRISM** 八维风格画像。
> 一个无框架依赖、无副作用的 CS2 选手评分计算库。

[![version](https://img.shields.io/badge/version-0.2.0-orange)](./package.json)
[![status](https://img.shields.io/badge/weights-prior-yellow)](./docs/rr.md#六账户与先验权重)

## 这是什么

`rival-rating` 只做评分计算。上游把 demo 事件派生为稳定事实信号，本库把这些事实信号计算成：

1. **RR**：主评分，最终形态是 Combat / Trade / MapControl / Utility / Clutch / Objective 六账户。
2. **HLTV 2.0 baseline**：`computeRR` / `hltv-2-baseline-v1.json`，作为盒分对照组，不承载 RR 主模型。
3. **PRISM**：八维打法画像，回答风格，不回答谁更强。

RR 不直接复刻 HLTV，也不把 ratingPro / WE 当最终标签。市场评分天然偏向 Combat，本库的产品立场是：
Combat 是主干，但补枪、控图、道具、残局和目标也应作为可解释账户进入评分。

## 安装

```bash
pnpm add @rivalhub/rival-rating
```

当前公开 API：

```ts
import {
  computeRR,                    // HLTV 2.0 baseline
  computeRRSixAccounts,         // RR 六账户主模型
  computeCohortAccountsRR,
  computeFrozenProBaselineRR,
  rrSixAccountProBaselineV0,    // provisional 52-ZIP职业基准
  computePrism,
} from "@rivalhub/rival-rating";
```

RR 六账户是当前主路径；HLTV 2.0 baseline 只作为盒分对照组保留。

## 模型入口

| 文档 | 内容 |
|---|---|
| [docs/rr.md](./docs/rr.md) | RR 六账户最终形态、每个指标解释、先验权重 |
| [docs/hltv-2-baseline.md](./docs/hltv-2-baseline.md) | HLTV 2.0 baseline 的定位与指标解释 |

## 目标架构

```text
cs2-demo-analysis-kit
  └─ AccountSignals / MapControlSignals / UtilitySpatialSignals
        │
        ▼
rival-rating
  ├─ HLTV 2.0 baseline       // 对照组
  ├─ RR 六账户               // 主评分
  │   ├─ Combat
  │   ├─ Trade
  │   ├─ MapControl
  │   ├─ Utility
  │   ├─ Clutch
  │   └─ Objective
  └─ PRISM 八维画像           // 风格
```

本库不读取 `.dem`，不依赖 awpy，不拥有 nav/BVH 资产。地图空间信号由
`cs2-demo-analysis-kit` / `@cs2dak/maps` 派生后传入。

## RR 六账户先验权重

| 账户 | 先验权重 | 说明 |
|---|---:|---|
| Combat | 1.00 | 武器击杀、武器伤害、死亡、首杀、多杀、劣势击杀 |
| Trade | 0.45 | 补枪、被补、有效未交易死亡惩罚 |
| MapControl | 0.00 | 当前保持 shadow；上游 official fields 稳定后再 ramp |
| Utility | 0.30 | 闪、烟、火等道具创造的空间/压制/伤害 |
| Clutch | 0.35 | 1vX 残局胜负超出静态期望 |
| Objective | 0.15 | 下包、拆包、下包转化 |

这些是人工先验，不是监督学习直接拟合结果。职业样本负责标准化和残差化；胜率模型只做验证/校准。
当前 `rr-six-accounts-v1.json` 是第一轮保守先验：非 Combat 账户权重已下调，MapControl / Utility
使用 per-round cap 做尺度治理，Clutch 使用小样本收缩。

## 当前实现状态

| 能力 | 状态 |
|---|---|
| HLTV 2.0 baseline (`computeRR`) | ✅ 已实现 |
| 六账户 RR (`computeRRSixAccounts`) | ✅ 已实现 |
| cohort 标准化 + Combat 残差化 | ✅ 已实现 |
| frozen pro baseline | ✅ 已有 52 ZIP provisional v0 |
| MapControl / UtilitySpatial 输入契约 | ✅ 已实现；默认权重保持 shadow，事实信号由 `cs2-demo-analysis-kit` 派生 |
| RR 六账户权重 JSON | ✅ 已实现 |

## PRISM 八维

| 维 | 说明 | α（风格比重） |
|---|---|---:|
| Firepower | 纯输出，不看生存 | 0.40 |
| Opening | 首杀对枪 | 0.60 |
| Clutch | 残局倾向与能力 | 0.55 |
| Sniping | AWP 风格标签 | 0.85 |
| Survival | 生存/低死亡率 | 0.20 |
| Utility | 道具使用风格 | 0.70 |
| Trading | 补枪/团队交换 | 0.60 |
| Entry | 开路尖刀 | 0.70 |

PRISM 是 cohort 风格画像，不是 RR 主评分。

## 开发

```bash
pnpm install
pnpm test
pnpm typecheck
```

## 生态关系

| 仓库 | 角色 |
|---|---|
| `cs2-demo-format` | demo ZIP 合同 |
| `cs2-demo-analysis-kit` | 从 demo / ZIP 派生 RR 所需事实信号 |
| `rival-rating` | 账户契约、先验权重、标准化/残差化、RR/PRISM 计算 |
| RivalHub / 其他产品 | 展示、身份归并、赛季上下文、友好化解释 |
