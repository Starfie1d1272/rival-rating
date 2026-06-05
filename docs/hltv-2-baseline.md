# HLTV 2.0 Baseline

> HLTV 2.0 社区逆向公式的实现，用作对照组和迁移基线，不承载 RR 品牌本体。

## 定位

HLTV 2.0 baseline 回答的问题是：

> 这名选手的盒分产出有多接近 HLTV 2.0 风格的评价？

它不是最终 RR，因为它天然偏向 Combat，难以看见补枪、控图、道具空间和目标协作的独立价值。

## 输入

模型消费 `RRIndicators`，也就是扁平统计信号：

| 指标 | 解释 |
|---|---|
| `kpr` / `dpr` | 每回合击杀 / 死亡 |
| `kast` | Kill / Assist / Survive / Trade 回合占比 |
| `impact` | 首杀、多杀等影响力近似项 |
| `adr` | 每回合平均伤害 |
| `rating2Like` 相关字段 | 用于拟合 HLTV 2.0 逆向结构的盒分指标 |

权重文件是 `src/weights/hltv-2-baseline-v1.json`。公开导出名为
`hltv2BaselineWeightsV1`；文档和产品叙事中统一称为 **HLTV 2.0 baseline**。

## 与 RR 的关系

| 项 | HLTV 2.0 baseline | RR |
|---|---|---|
| 本体 | 扁平统计线性模型 | 透明六账户模型 |
| 主要偏好 | Combat / box score | Combat 主干 + 团队贡献 |
| 用途 | 对照、回归检查、刻度参考 | 主评分 |
| 是否使用 nav/BVH | 否 | 不直接使用；只消费 DAK 派生后的空间信号 |
| 是否用于权重校准 | 可作为外部参照之一 | 是最终输出 |

HLTV 2.0 baseline 的高相关性不代表它是正确目标，只说明市场评分本身偏向枪火产出。
RR 刻意保留非 Combat 账户，是产品立场。
