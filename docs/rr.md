# RR：透明六账户评分模型

> 当前主模型文档。代码已收敛到六账户 RR：
> Combat / Trade / MapControl / Utility / Clutch / Objective。

## 一句话

RR 是一个透明、可解释的 CS2 选手贡献评分。它不把 HLTV、ratingPro 或 WE 当最终标签，
而是把选手行为拆成六个语义账户，先用人工先验表达产品立场，再用职业样本做固定基准和残差化，
最后用胜率模型做验证与小幅校准。

```text
事实信号
  → 六账户 raw
  → frozen pro baseline 标准化
  → Combat 主干残差化
  → 先验权重加权
  → RR
```

HLTV 2.0 逆向公式只保留为 baseline，对应当前 `hltv-linear-v1` 模型和
`weights/hltv-2-baseline-v1.json`。它不再承载 RR 主模型命名。

## 模型边界

| 名称 | 回答什么 | 状态 |
|---|---|---|
| **HLTV 2.0 baseline** | 盒分产出接近 HLTV 2.0 的程度 | 已实现，用作对照 |
| **RR** | 这名选手对回合/比赛贡献了什么价值 | 六账户主模型，已实现 |
| **PRISM** | 这名选手是什么风格 | 独立风格画像，不是评分本体 |

RR 不直接监督学习，不直接拟合 HLTV / ratingPro / WE。监督模型只用于：

- 校准账户 raw 的量级；
- 检查六账户相对权重是否离谱；
- 发现伪价值指标，例如保枪时间、垃圾烟、无意义绕后；
- 验证 MapControl / UtilitySpatial 是否真的稳定对应回合胜率增益。

最终分数仍然是透明六账户模型。

## 六账户与先验权重

第一版 RR 使用保守先验权重：

| 账户 | 先验权重 | 回答的问题 | 权重理由 |
|---|---:|---|---|
| Combat | 1.00 | 你直接赢了多少武器对抗 | CS2 的主目标仍然是击杀、伤害、少死，Combat 必须是主干 |
| Trade | 0.40 | 你的死亡和队友是否可交换 | 交易网络重要，但 trade kill 已在 Combat 计入，避免双重奖励 |
| MapControl | 0.20 | 你靠站位/枪线为团队创造了多少空间 | 第一版保守进入，避免奖励保枪、蹲点和无效 lurk |
| Utility | 0.25 | 你靠道具创造了多少空间/压制 | 空间型指标尚待职业样本校准，先低于最终理想权重 |
| Clutch | 0.30 | 你在残局中是否超出期望 | 关键回合重要，但样本少，配合 shrinkage 降低波动 |
| Objective | 0.10 | 你完成了多少爆破目标 | 目标动作常在战术链末端，第一版最低权重 |

`mapControl: 0.20` 是 shadow → 正式过渡权重。职业样本验证稳定后，可以考虑升到 `0.25–0.35`。
`rr-six-accounts-v1.json` 使用 `score.base=1.0` 和 `score.scale=0.10`，避免把 raw 线性分和
league mean anchor 混成同一个语义；产品层如需本地相对分，应另算 `relativeRR`。

## 账户指标定义

### Combat

Combat 只奖励直接武器对抗价值，不吃道具伤害、补枪价值或控图价值。

| 指标 | 解释 | 价值方向 |
|---|---|---|
| `kills` | 武器击杀数 | 正向 |
| `deaths` | 自己死亡数 | 负向 |
| `effectiveDamage` | 有效武器伤害，按对手剩余血量 cap，避免 overkill 刷分 | 正向 |
| `openingKills` | 本回合首杀 | 正向 |
| `openingDeaths` | 本回合首死 | 负向 |
| `multiKills.two/three/four/five` | 2K/3K/4K/5K 回合数 | 正向，表示回合突破能力 |
| `headshotKills` | 爆头击杀 | 默认风格信号，价值权重可为 0 |
| `wallbangKills` | 穿墙/穿烟击杀 | 小幅正向，表示信息和枪线利用 |
| `killsByBuyDelta` | 按击杀者与被击杀者装备差分桶 | 以弱打强加权，以强凌弱降权 |
| `killsByManState` | 按击杀发生时人数差分桶 | 人少时击杀加权，人多时击杀降权 |

推荐 raw 形态沿用当前代码：

```text
combatRaw =
    killWeight × KPR × contextFactor
  + deathWeight × DPR
  + damageWeight × effectiveDamagePerRound
  + openingWeight × (openingKills - openingDeaths) / rounds
  + multiKillWeight × multiKillRounds / rounds
  + wallbangWeight × wallbangKills / rounds
```

### Trade

Trade 只描述团队交换网络，不负责奖励 lurk 空间本身。

| 指标 | 解释 | 价值方向 |
|---|---|---|
| `tradeKills` | 队友阵亡后及时补回敌人 | 正向 |
| `tradedDeaths` | 自己阵亡后被队友及时补回 | 正向，说明死亡可被团队交换 |
| `deaths` | 自己死亡总数，用于推导未被交易死亡 | 中间量 |
| `tradedOpeningDeaths` | 首死被队友补回 | 正向，保护 entry 的生命价值 |
| `strategicIsolationDeaths` | 不可交易但具有战略价值的孤立死亡 | 只用于减轻 Trade 负分 |

最终 Trade 惩罚不直接用 `deaths - tradedDeaths`，而是：

```text
effectiveUntradedDeaths =
  max(0, deaths - tradedDeaths - strategicIsolationDeaths)
```

`strategicIsolationDeaths` 必须由 MapControl 侧严格判定：死前有正的边际空间控制、控制的是关键路线/
包点/转点、队友客观无法补枪，且不是保枪或低胜率拖时间。它只修正 Trade 负分，不给 MapControl
额外正分，避免双重奖励。

### MapControl

MapControl 奖励玩家靠自身站位、枪线和可达路线创造的空间。道具创造的空间归 Utility。

| 指标 | 解释 | 价值方向 |
|---|---|---|
| `uniqueStrategicControlSeconds` | 只有该玩家存在时团队才能控制的高价值空间秒数 | 正向 |
| `contestedFrontierControlSeconds` | 敌我可能争夺的前线区域控制秒数 | 正向 |
| `routeDenialSeconds` | 玩家站位/枪线让敌方无法安全走某条关键路线的秒数 | 正向 |
| `teammateAdvanceUnits` | 队友利用该玩家控制的空间向前推进的 nav 距离 | 正向 |
| `firstControlEvents` | 首次拿到中路、香蕉道、A main、B apps 等关键区 | 正向 |

推荐 raw：

```text
mapControlRaw =
    0.35 × uniqueStrategicControlSeconds / rounds
  + 0.25 × contestedFrontierControlSeconds / rounds
  + 0.20 × routeDenialSeconds / rounds
  + 0.15 × teammateAdvanceUnits / rounds
  + 0.05 × firstControlEvents / rounds
```

工程实现中这些不同单位不会直接相加，而是先按 per-round cap 归一化：

```text
normalized = min(value / rounds, capPerRound) / capPerRound
```

实现来源应在 `cs2-demo-analysis-kit`：positions-1s + route/zone/nav + staticLineOfSight。
`rival-rating` 只消费最终事实信号，不拥有 nav、BVH 或 awpy 运行时。

### Utility

Utility 奖励道具创造的空间、压制和伤害。第一版保留现有结果型指标，最终升级为空间型指标。

| 指标 | 解释 | 价值方向 |
|---|---|---|
| `flashAssists` | 闪光直接帮助队友击杀 | 正向 |
| `effectiveEnemyFlashSeconds` | 敌人处在真实交战/威胁窗口中的有效致盲秒数 | 正向 |
| `teamFlashSuppressionSeconds` | 闪到队友并压制其交战/推进能力的秒数 | 负向 |
| `smokeProtectedCrossings` | 队友借烟穿过原本暴露枪线的次数或距离 | 正向 |
| `smokeSightlineDenialSeconds` | 烟切断关键静态枪线的秒数 | 正向 |
| `smokeIsolationSeconds` | 烟把敌人与包点/队友/退路隔离的秒数 | 正向 |
| `incendiaryPathDelayUnits` | 火焰让敌人绕路或延迟的 nav 距离/时间 | 正向 |
| `incendiaryDisplacementEvents` | 火逼敌人离开关键位置的事件数 | 正向 |
| `utilityDamage` | HE / 火等造成的有效道具伤害 | 正向 |

重要边界：如果 `effectiveDamage` 已包含道具伤害，必须在 analysis 层拆成 `weaponDamage` 和
`utilityDamage`，避免 Combat 与 Utility 重复计分。

### Clutch

Clutch 只看残局胜负是否超出静态期望，不重复奖励残局击杀数。

| 指标 | 解释 | 期望胜率 |
|---|---|---:|
| `vsOne.count/won` | 1v1 次数和胜利数 | 0.50 |
| `vsTwo.count/won` | 1v2 次数和胜利数 | 0.25 |
| `vsThree.count/won` | 1v3 次数和胜利数 | 0.10 |
| `vsFour.count/won` | 1v4 次数和胜利数 | 0.04 |
| `vsFive.count/won` | 1v5 次数和胜利数 | 0.01 |

```text
clutchRaw = Σ(won - count × expectation) / rounds
```

赢难局加分多，输难局扣分少；这比数残局击杀更抗刷。工程实现额外使用
`clutchCount / (clutchCount + 5)` 做小样本收缩。

### Objective

Objective 只奖励爆破目标动作，不吃包点附近击杀、控图或道具铺垫。

| 指标 | 解释 | 价值方向 |
|---|---|---|
| `plants` | 下包次数 | 小幅正向 |
| `defuses` | 拆包次数 | 正向 |
| `plantsConverted` | 下包后本回合最终获胜 | 小幅正向 |

Objective 权重最低，因为下包者常是战术链末端，噪声大；但有 `bombs.site` 和转化结果后，
它比早期纯下包计数更可信。

## 标准化、残差化与固定职业基准

裸 raw 相加会让高频 Combat 碾压低频账户。最终 RR 应使用 frozen pro baseline：

```text
raw_a       = accountRaw_a(signals)
z_a         = (raw_a - baseline.mean_a) / baseline.std_a
used_combat = z_combat
used_a      = residualize(z_a, z_combat)
composite   = Σ priorWeight_a × used_a
RR          = 1.0 + scale × composite
```

含义：

- 1.0 = 职业平均水平；
- Combat 是主干；
- 其他账户只保留超出 fragging 水平的正交团队贡献；
- 普通天梯玩家均值落在 0.8–0.9 是合理结果，表示距离职业基准还有差距；
- 友好化显示由产品层处理，不污染评分模型。

## 胜率模型的使用边界

胜率是 CS2 的真实目标函数，比 HLTV / ratingPro / WE 更适合作校准参考。但监督学习不能直接产出 RR。

推荐用途：

```text
round state + action/context → P(round win)
actionValue = P_after - P_before
```

它用于验证：

- 六账户方向是否正确；
- MapControl 是否稳定带来胜率增益；
- Utility 空间型指标是否优于旧的闪光秒数/道具伤害；
- 账户权重是否稳定；
- 是否奖励保枪、垃圾烟、无意义火、低胜率绕后。

最终权重可以做 shrink：

```text
finalWeight = 0.7 × priorWeight + 0.3 × empiricalWeight
```

这里的比例是治理策略，不是公式铁律。产品立场仍然优先于黑箱拟合。

## 工程归属

| 仓库 | 负责 |
|---|---|
| `cs2-demo-analysis-kit` | 从 demo / v2 ZIP 派生 AccountSignals、MapControlSignals、UtilitySpatialSignals |
| `@cs2dak/maps` | route、zone、nav 派生资产、staticLineOfSight / BVH、可视化调试 |
| `rival-rating` | 账户契约、先验权重、标准化/残差化、RR 计算 |
| RivalHub / 其他产品 | 展示、身份归并、赛季上下文、友好化解释 |

`rival-rating` 不应依赖 awpy，不应读取 `.dem`，不应拥有 nav/BVH 资产。

## 当前实现状态

已实现：

- HLTV 2.0 baseline：`computeRR` / `hltv-linear-v1`；
- 六账户 RR：`RRSignals` / `computeRRSixAccounts` / `rr-six-accounts`；
- MapControlSignals；
- Utility 空间型道具指标；
- TradeSignals 的 `strategicIsolationDeaths`；
- cohort 标准化 + Combat 残差化：`computeCohortAccountsRR`；
- frozen pro baseline 雏形：`computeFrozenProBaselineRR`。

待实现：

- 重新冻结六账户职业基准；
- 用职业样本验证/校准 MapControl 和 UtilitySpatial 的 raw 量级。
