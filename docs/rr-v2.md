# RR v2：价值账户模型

> 状态：接口已就绪，权重为未校准先验。`hltv-linear-v1` 保留为对照组。

## 一句话

把 RR 标量从「五个统计量的线性加权」（HLTV 本体论）重构为 **五个语义正交价值账户（Combat / Trade / Clutch / Objective / Utility）的加总**，Economy 不单开账户而是做击杀 context 乘子（避免和 Combat 重复计分）。

## 双模型并存

本库用一个可插拔的 `RRModel` 接口（`src/types/accounts.ts`）让两个范式同时存在：

| model id | 输入契约 | 输出类型 | 定位 |
|---|---|---|---|
| `hltv-linear-v1` | `RRIndicators`（扁平信号袋） | `RRResult` | baseline / 对照组，HLTV 2.0 逆向 |
| `value-accounts-v2-lite` | `AccountSignalsV2`（五账户证据） | `RRResultV2` | **主力新模型**，按价值账户重做的 |

`analysis-kit` 可以两个都跑，对比两份分数。

## 账户证据契约（`AccountSignalsV2`）

```
Combat:    K/D/A / 多杀 / 首杀 / 爆头 / 穿墙 + 经济差分桶 + 人数差分桶
Trade:     tradeKill / tradedDeath / untradedDeath
Clutch:    1v1–1v5 各局面次数+胜负（模型用"实际−静态期望"打分）
Objective: 下包/拆包/下包转化获胜
Utility:   flashAssist / 致盲敌方秒数 / 致盲队友秒数 / 道具伤害
```

关键设计：

- **Eco 不是账户**：`killsByBuyDelta`（经济差分桶）和 `killsByManState`（人数差分桶）是 Combat 的 **context 修正**，不独立计分，避免重复。
- **`null` 可降级**：任一分桶/字段为 `null`（analysis 仓库尚未实现），乘子自动取 1.0，不报错。所以契约面向 v2-full 设计，但能优雅退化到 v2-lite。
- **证据 ≠ 分数**：这一层只是事实。击杀值多少分由权重 JSON 决定。

## 给 analysis 仓库的提示词

> 在 `@cs2dak/core` 里新增一个 `deriveAccountSignalsV2(pkg: DemoPackage): AccountSignalsV2` 函数，接受已加载的 DemoPackage、已构建的 playerRoundFacts，输出 rival-rating v2 的新输入契约 AccountSignalsV2。
>
> 你需要两个仓库作为参考：
> 1. **契约与模型**：`rival-rating` 的 `src/types/accounts.ts`（AccountSignalsV2 结构）+ `src/weights/rr-value-accounts-v2-lite.json`（权重） + `src/rr/models/value-accounts-v2-lite.ts`（模型实现）
> 2. **现有适配代码**：`packages/core/src/index.ts` 的 `buildPlayerIndicators`（你已经读到 events 层了，就是这些数据源）
>
> 新函数需要做：
> - 从 kills 重建 `killsByBuyDelta`（按击杀 tick 时双方装备价值差，分 advantage/even/disadvantage 三桶）和 `killsByManState`（按击杀时存活人数差，分 manUp/even/manDown 三桶）
> - 把现有的 stats/clutches 映射到 AccountSignalsV2 的五个子对象
> - `null` 字段先填 null（不要硬塞 0）
>
> 产出 AccountSignalsV2 后，就可以调 `computeValueAccountsRR(signals, weights)` 跑 v2 模型了。

## 权重：校准状态（务必知情）

`rr-value-accounts-v2-lite.json` 里的所有权重是我凭游戏理解定的**未校准先验**，仅供管道跑通 + 相对排序。绝对刻度由联赛锚定提供（同 RR v1 流程）。

**V2 格式让信号更丰富 ≠ 权重变可信。** 可信度三步才能建立：

1. 先验（当前状态）
2. ~50 场赛季数据做相对校准 + 联赛锚定
3. ratingPro / 主观评分做对照验证

所以目前这个版本的分数**只会有更好的相对区分力，不是绝对准确**。别用这个给选手发正式分。

## 工程细节

- **输入是「单场」**：AccountSignalsV2 是单名选手单张 demo 的原始值，模型内部自己做 `/rounds` 归到 per-round。
- **锚定在调用方做**：`computeValueAccountsRR` 返回的 rr 是锚定前的（同 `computeRR`），调用方跑完所有选手后调 `computeLeagueMeanV2` 算均值，再整体 `× (1/mean)`。
- **Objective 权重刻意压低**：下包者不一定是回合最大功臣，v1 先做 0.1，防噪声污染分数。
- **Combat context 分桶未填充时 = 全部降级为乘子 1.0**：analysis 仓库可以先 stub，分数照样产出，后面再补。
