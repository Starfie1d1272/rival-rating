# rival-rating

**RR (Rival Rating)** 标量引擎 + **PRISM** 八维风格画像。

RivalHub 专用评分体系，独立于 HLTV 自行建立。

## 架构

```
demo → RRIndicators（指标层 Layer 0）
            ↓
    ┌───────┴────────┐
    RR 标量           PRISM 八维画像
  绝对刻度            赛季内 z-score
  1.00=联赛均值       风格指纹 + 水平着色
  跨赛季可比          冷启动收缩
```

### RR 标量

| 层级 | 算法 | 状态 |
|---|---|---|
| Layer 1 | 上下文加权（eco 乘子 + 情境权重） | ✅ 基础公式已实现，eco 乘子待校准 |
| Layer 2 | Round Swing / WPA（ΔP 逐杀） | 🔒 待 ~1000 张图后开启 |

### PRISM 八维

| 维 | 说明 | α（风格比重） |
|---|---|---|
| 火力 Firepower | 纯输出，不看生存 | 0.40 |
| 首杀 Opening | 首杀对枪赢下来 | 0.60 |
| 残局 Clutch | 1vX 残局胜率 | 0.55 |
| 狙击 Sniping | AWP 风格标签 | 0.85 |
| 生存 Survival | 活下来/低死亡率 | 0.20 |
| 道具 Utility | 投掷物贡献 | 0.70 |
| 补枪 Trading | 补枪、护队友 | 0.60 |
| 突破 Entry | 开路尖刀，首先暴露 | 0.70 |

**双编码**：形状（轴半径）= 风格，颜色 = RR 百分位（水平）。

## 权重版本

- `rr-v1.json` — RR Layer 1 基础系数（HLTV 2.0 逆向公式过渡版）
- `prism-v1.json` — PRISM 八维 α 值 + 信号配置

所有可调数字外置在权重文件，公式形状稳定。替换系数只需换文件并升版本号。

## 开发

```bash
pnpm install
node_modules/.bin/vitest run   # 跑测试
node_modules/.bin/tsc --noEmit # 类型检查
```

## OCR 外部字段（保留在 RivalHub）

- `ratingPro` — 完美平台 RatingPro（OCR 摄入）
- `we` — 完美平台 RS（OCR 摄入）

两个字段是"第三方摄入数据"，不挂 RR 品牌，原样保留。
