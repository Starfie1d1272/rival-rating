# AGENTS.md

This file provides guidance to Codex when working in this repository.

## 1. Project Overview

- `rival-rating` 是 `@rivalhub/rival-rating`，一个无框架依赖、无副作用的 CS2 选手评分计算库。
- 技术栈：TypeScript + NodeNext ESM + Vitest，包管理器为 pnpm。
- 定位：消费上游派生后的事实信号，输出 HLTV 2.0 baseline、RR 账户评分和 PRISM 八维风格画像。

## 2. Commands

- 安装依赖：`pnpm install`
- 跑全部测试：`pnpm test`
- 监听测试：`pnpm test:watch`
- 类型检查：`pnpm typecheck`
- 单文件测试：`pnpm vitest run src/rr/compute.test.ts`
- 单文件测试：`pnpm vitest run src/rr/models/cohort-accounts.test.ts`
- 单文件测试：`pnpm vitest run src/prism/zscore.test.ts`

## 3. Architecture

- 类型契约在 `src/types/`，权重 JSON 在 `src/weights/`，所有系数应外置到版本化 JSON。
- HLTV 2.0 baseline 在 `src/rr/compute.ts` / `src/rr/models/hltv-linear-v1.ts`，RR 账户模型在 `src/rr/models/`。
- PRISM 计算在 `src/prism/`，详细模型边界见 `docs/rr.md` 和 `docs/hltv-2-baseline.md`。

## 4. Conventions

- 保持纯计算库边界：函数只消费入参并返回结果，不读取文件、不连数据库、不访问网络。
- TypeScript 使用 `strict: true`、`exactOptionalPropertyTypes`、`noUncheckedIndexedAccess`；索引访问必须显式处理 `undefined`。
- 公式形状尽量稳定，调参优先改 `src/weights/*.json`，不要把魔法系数散落在源码里。
- RR 主模型最终为六账户：Combat / Trade / MapControl / Utility / Clutch / Objective。
- PRISM 是 cohort 风格画像，不是评分本体；不要把 PRISM 输出混进 RR 主评分。

## 5. Hard Constraints

- 不要把本库改成应用层：禁止引入 Next.js、数据库、server action、API route 或 UI 依赖。
- 不要在本库读取 `.dem`，不要依赖 awpy，不要拥有 nav/BVH；地图空间信号由 `cs2-demo-analysis-kit` / `@cs2dak/maps` 派生后传入。
- 不要把 HLTV 2.0 baseline 重新命名为 RR 主模型；`computeRR` 当前是兼容遗留命名的 baseline。
- 不要把胜率模型、HLTV、ratingPro 或 WE 当成最终输出标签；它们只能用于验证和小幅校准。
- 不要向系统 Python 或 conda base 安装包；本仓库一般不需要 Python。

## 6. Gotchas

- `pnpm lint` 不存在；验证优先用 `pnpm typecheck` 和 `pnpm test`。
- HLTV 2.0 baseline 权重在 `src/weights/hltv-2-baseline-v1.json`，RR 主权重在 `src/weights/rr-six-accounts-v1.json`。
- RR 主实现是 `src/rr/models/six-accounts.ts`；不要恢复旧 `value-accounts-v2-lite` 命名。
- `package.json` exports 直接指向 `src/index.ts` 和 `src/weights/*`；改导出面时要同步检查消费方。
- 新增未追踪文件不会出现在普通 `git diff -- <path>` 里；清理或提交前用 `git status --short --untracked-files=all` 复核。
