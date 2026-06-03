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

## cohort 平衡：标准化 + 残差化（`computeCohortAccountsRR`）

`computeValueAccountsRR` 是**单选手**线性相加，存在一个结构问题：五账户 raw 量级天然差
~20–40×（combat 每回合发生，clutch/objective 稀有），线性相加里 combat 碾压其余四账户，
`accountWeight` 先验形同虚设。这需要一群选手（cohort）才能修，故单开
`computeCohortAccountsRR(signals[], weights, { targetStd })`。默认 `targetStd` / `epsilon`
来自 `rr-value-accounts-v2-lite.json` 的 `cohort` 配置，调用方也可临时覆盖：

1. 恢复每账户未加权 raw，跨选手 z-score。
2. combat 作主干；其余账户**残差化**（减去 combat 能解释的部分，只留正交增量），度量
   "超出 fragging 水平的团队贡献"，避免与 combat 双重计分。
3. composite = `w_combat·zc + Σ w_a·zr_a`；scale 对齐 `cohort.targetStd`（调用方可传 std(rrV1) 覆盖）；anchor 到 1.0。

赛季 cohort（57 人）用全员；单场用场内 10 人（注意 n=10 时残差回归偏噪声，单场更适合
直接展示 `computeValueAccountsRR` 的线性快照，canonical Rating 用赛季 cohort）。

### 校准结论（55 场 OCR ratingPro / WE，按 steam64 季级关联）

- 整体评分 ≈ combat：combat 单独 corr(ratingPro)=0.90；ratingPro/WE 本身就是 combat 主导。
- 非 combat 账户独立信号弱且与 combat 共线（clutch standalone 0.46，与 combat 共线 0.56）。
- **残差化后，正交团队增量对 ratingPro/WE 的边际预测力 ≈ 0。**

→ **combat 是数据强制的主干；非 combat 的 accountWeight 是刻意的价值选择（识别团队贡献），
不是数据回归出来的。** 这是"市场（ratingPro/WE）低估团队价值"的明确产品立场，
代价是 `corr(accountRR, ratingPro)=0.68 < rrV1 的 0.90`——v2 刻意偏离市场排名。

### 不变量原则

Rating（accountRR）**不做按选手场数的冷启动收缩**——它是不变量，照实展示，由读者结合
`mapCount` 理解可信度。冷启动收缩只用于 PRISM 八维画像（`computePrism`，小样本会把雷达拉满）。
