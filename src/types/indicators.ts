/**
 * RRIndicators — 指标层（Layer 0）
 *
 * 从单张 demo 提取的所有原始信号，是 RR 标量和 PRISM 八维画像的共同输入。
 *
 * 约定：
 *  - 暂时无法从当前 demo 格式计算的字段标注 `null`。
 *  - 对应的权重文件里把该信号的 weight 设 0 即可，零成本留空。
 *  - 百分比字段统一 0-100 刻度（与现有 kast/hsPercent 约定一致）。
 *  - Rate 类字段统一 per-round（除非字段名明确说明）。
 */
export interface RRIndicators {
  // ─── 元信息 ────────────────────────────────────────────────────────────
  steamId64: string;
  /** 该图选手实际参与的回合数（优先用真实轮数，退而用 kills+deaths 近似） */
  totalRounds: number;

  // ─── 基础输出 ───────────────────────────────────────────────────────────
  kills: number;
  deaths: number;
  assists: number;
  /** Kills Per Round */
  kpr: number;
  /** Deaths Per Round */
  dpr: number;
  /** Assists Per Round */
  apr: number;
  /** Average Damage Per Round */
  adr: number;
  /** Headshot % (0–100) */
  hsPercent: number;
  /** KAST % (0–100)：Kill/Assist/Survive/Trade 回合占比 */
  kast: number;
  /** 存活率 = (totalRounds - deaths) / totalRounds，0–1 */
  survivalRate: number;

  // ─── 多杀 ───────────────────────────────────────────────────────────────
  twoKillRounds: number;
  threeKillRounds: number;
  fourKillRounds: number;
  fiveKillRounds: number;
  /** (2K+3K+4K+5K回合) / totalRounds */
  multiKillRate: number;

  // ─── 首杀 / 突破（Entry vs Opening 拆分）────────────────────────────────
  firstKillCount: number;
  firstDeathCount: number;
  /** firstKills / totalRounds — 多常打赢首杀 */
  firstKillRate: number;
  /** firstDeaths / totalRounds — 多常当尖刀首先暴露 */
  firstDeathRate: number;
  /** (firstKillCount + firstDeathCount) / totalRounds — 参与首杀对枪的频率 */
  openingDuelRate: number;
  /**
   * firstKill / (firstKill + firstDeath) — 首杀对枪胜率
   * Opening 轴效率核心；Entry 轴关注参与度而非胜率
   */
  openingDuelWinRate: number;

  // ─── 补枪 ───────────────────────────────────────────────────────────────
  tradeKillCount: number;
  /** tradeDeath = 自己死后队友及时补回的次数 */
  tradeDeathCount: number;
  /** tradeKills / totalRounds */
  tradeKillRate: number;
  /** tradeDeaths / deaths — 死了多常被补（Entry 选手的生命价值指标） */
  tradeDeathRate: number;

  // ─── 残局 ───────────────────────────────────────────────────────────────
  clutchAttempts: number;
  clutchWins: number;
  /** clutchWins / clutchAttempts，0–1 */
  clutchWinRate: number;
  /** clutchAttempts / totalRounds — 多常成为最后一人 */
  clutchFrequency: number;
  /**
   * Σ N × won_N — 按对手数加权的残局积分
   * 1v3 赢 = 3 分，1v1 赢 = 1 分
   */
  clutchScore: number;
  /** clutchScore / totalRounds */
  clutchScoreRate: number;
  vsOne: { count: number; won: number };
  vsTwo: { count: number; won: number };
  vsThree: { count: number; won: number };
  vsFour: { count: number; won: number };
  vsFive: { count: number; won: number };

  // ─── 狙击 ───────────────────────────────────────────────────────────────
  awpKills: number;
  /** awpKills / totalRounds */
  awpKillsPerRound: number;
  /** awpKills / kills，0–1 — AWP 作为主要武器的风格指标 */
  awpKillRate: number;
  /** (AWP + SSG) kills */
  sniperKills: number;
  /** sniperKills / kills，0–1 */
  sniperKillRate: number;
  /**
   * AWP 2K+ 回合数 / totalRounds
   * null 直到武器经济快照可用（需事后重跑 demo 才能精确拿到）
   */
  awpMultiKillRate: number | null;
  /**
   * AWP 对枪实际胜率（需击杀 tick 时的装备快照）
   * null — Layer 1 eco 校准阶段再开启
   */
  awpDuelWinRate: number | null;

  // ─── 道具 ───────────────────────────────────────────────────────────────
  utilityDamage: number;
  utilityDamagePerRound: number;
  flashAssistCount: number;
  flashAssistPerRound: number;
  /**
   * 致盲敌方总秒数（从 blinds.json 聚合，v1 数据源）
   * v2 起可直接用 enemyFlashDurationSeconds 替代
   */
  blindDurationTotal: number;
  blindDurationPerRound: number;
  /**
   * 致盲敌方总秒数（来自 playerStats v2 直接字段，比聚合更准）
   * null — 等 cs2-demo-exporter v2 产出后填入；激活前权重设 0
   */
  enemyFlashDurationSeconds: number | null;
  enemyFlashDurationPerRound: number | null;
  /**
   * 致盲己方队友总秒数（负向风险信号）
   * null — 等 cs2-demo-exporter v2 产出后填入；激活前权重设 0
   */
  teamFlashDurationSeconds: number | null;
  teamFlashDurationPerRound: number | null;
  grenadeCount: number;
  grenadeCountPerRound: number;

  // ─── 当前 RR 空间信号（PRISM 可选画像输入）──────────────────────────────
  uniqueStrategicControlSecondsPerRound?: number | null;
  contestedFrontierControlSecondsPerRound?: number | null;
  routeDenialSecondsPerRound?: number | null;
  teammateAdvanceUnitsPerRound?: number | null;
  firstControlEventsPerRound?: number | null;
  effectiveEnemyFlashSecondsPerRound?: number | null;
  teamFlashSuppressionSecondsPerRound?: number | null;
  smokeProtectedCrossingsPerRound?: number | null;
  smokeSightlineDenialSecondsPerRound?: number | null;
  smokeIsolationSecondsPerRound?: number | null;
  incendiaryPathDelayUnitsPerRound?: number | null;
  incendiaryDisplacementEventsPerRound?: number | null;

  // ─── 经济上下文（Layer 1 eco 加权输入）─────────────────────────────────
  /** 从 player-economies.json 聚合；type='eco' 回合数 */
  ecoRoundCount: number;
  forceRoundCount: number;
  fullBuyRoundCount: number;
  /** type='pistol' 回合数 */
  pistolRoundCount: number;
  /** 该图全程平均装备价值 */
  avgEquipmentValue: number;

  // ─── 死亡原因分类（v2 playerStats 新增）──────────────────────────────
  /**
   * 被击杀死亡回合数（不含炸弹/跌落）
   * null — 等 cs2-demo-exporter v2 产出后填入；激活前权重设 0
   */
  combatDeathCount: number | null;
  /**
   * 被炸弹炸死回合数（说明位置/旋转失误，survival 轴负向信号）
   * null — 等 cs2-demo-exporter v2 产出后填入；激活前权重设 0
   */
  bombDeathCount: number | null;
  /**
   * 穿墙击杀数（锐利度风格标签）
   * null — 等 cs2-demo-exporter v2 产出后填入；激活前权重设 0
   */
  wallbangKillCount: number | null;

  // ─── Layer 2 占位（数据量 ~1000 张图后再填）──────────────────────────
  /** Σ ΔP(round win) per kill，即 Round Swing 总分 */
  roundSwingTotal: number | null;
  /** roundSwingTotal / kills */
  roundSwingPerKill: number | null;
}
