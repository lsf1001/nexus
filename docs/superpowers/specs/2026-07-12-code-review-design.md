# Nexus 全栈代码审查设计

- 日期: 2026-07-12
- 作者: 主代理
- 状态: 待用户审阅

## 背景

Nexus 仓库最近 21 个 commit 集中在 fact-check 流水线,核心代码已经稳定一段时间。
CLAUDE.md 第 1.2 条明确"单文件 ≤ 800 行",实际看到 `nexus/backend/api/ws/streaming.py` 已经 785 行,
`frontend/src/components/ChatArea.tsx` 已经 813 行,接近红线。

在动手做下一批功能前,需要一份全栈代码审查,识别**当前代码库**的可优化点,
并为其中高价值项产出可执行 plan,作为后续 sprint 的输入。

## 目标

1. 广度优先扫一遍后端 + 前端所有源代码文件(后端 35 个 Python / 前端 94 个 TS/TSX)
2. 覆盖四个维度:代码质量 / 架构与可维护性 / 性能与并发 / 安全与可靠性
3. 输出一份报告 + 3-5 个高价值发现项的 plan 文档
4. 不改任何代码,不在本次任务中实施 plan

## 范围

### 包含
- `nexus/backend/**/*.py` (35 个文件, 4062 行)
- `frontend/src/**/*.{ts,tsx}` (94 个文件, 15223 行)
- `desktop/src/**/*.{ts,tsx}` (Tauri 前端)
- `tests/` 抽查与代码质量有关的测试模式

### 不包含
- `experiments/` (探索性代码,与产品无关)
- `docs/` 文档审阅
- `data/`、`release/`、`node_modules/`、`.venv/` 等构建/产物
- `desktop/src-tauri/src/*.rs` (Rust 代码,非本次主目标;若有严重安全问题会作为附录)
- 自动修改任何源文件

## 方法

### 执行层

主代理串行扫后端(35 文件量小,上下文可控),派 3 个 Explore 子代理并行扫前端三块。
所有发现汇总到一份报告。

### 维度映射

| 维度 | 检查方法 | 严重度判据 |
|---|---|---|
| 代码质量 | ruff check + mypy + 人工看违规模式 | 违反 python_project.md 硬条款 = 高;模糊命名 = 中 |
| 架构与可维护性 | 文件大小 / 单一职责 / 依赖祸合 / 抽象层次 | 单文件>800 行 = 高;职责不清 = 中;抽象过度 = 低 |
| 性能与并发 | 同步 I/O / 锁粒度 / SQL 查询 / React 重渲染 | 明显 N+1 / 同步阻塞异步循环 = 高 |
| 安全与可靠性 | 鉴权 / 注入 / 资源泄漏 / 错误处理 | 鉴权绕过 / 路径穿越 / 资源未释放 = 高 |

### 高价值项筛选标准

同时满足:
- 严重度 ≥ 中
- 修复范围 ≤ 单文件 ≤ 200 行
- 不破坏既有公共 API

## 产出

### 1. 报告

- 路径: `docs/superpowers/reports/2026-07-12-code-review.md`
- 内容:
  - 概览(代码规模、最近 commit 焦点)
  - 按维度分组的所有发现
  - 每个发现:文件:行号、严重度、问题描述、修复建议
  - 高价值项清单(指向 plan 文件)

### 2. Plan 文档

- 路径: `docs/superpowers/plans/2026-07-12-<topic>.md`(3-5 个)
- 每个 plan:
  - 问题复述
  - 修复目标
  - 文件级任务分解
  - 测试要求
  - 验收标准

## 执行步骤

1. **后端扫描** (主代理)
   - `api/ws/streaming.py`(785 行,接近红线)
   - `main.py`(562 行)
   - `db.py`(503 行)
   - `api/ws/handlers.py`(501 行)
   - `llm/wrapper.py`(487 行)
   - 其余按目录扫:`api/`、`agents/`、`channels/`、`middleware/`、`quality/`、`fact_check/`、`rubrics/`、`routes/`

2. **前端并行扫描** (3 个子代理)
   - 子代理 1: `frontend/src/components/ChatArea.tsx`(813 行)+ ModelConfigModal + WechatPluginModal
   - 子代理 2: `frontend/src/components/desktop/`(SetupView/Sidebar/Shell/Settings/ContextMenu)
   - 子代理 3: `frontend/src/hooks/` + `store/` + `lib/` + 其他 components(ChatBubble/WechatPlugin)

3. **desktop 浅扫** (主代理)
   - `desktop/src/` 看是否有 Tauri 前后端衔接问题

4. **汇总报告** (主代理)

5. **高价值项出 plan** (主代理,3-5 个)

## 验收

- [ ] 报告已写入 `docs/superpowers/reports/2026-07-12-code-review.md`
- [ ] 报告包含四个维度的发现清单
- [ ] 3-5 个 plan 已写入 `docs/superpowers/plans/2026-07-12-*.md`
- [ ] 没有自动修改任何源代码
- [ ] 报告不依赖未做的工作(无 placeholder)

## 风险

- **执行时间**:后端 35 文件 + 前端 94 文件 + 汇总,预计 30-60 分钟
- **漏检风险**:广度优先,可能漏掉深度 bug;后续按 plan 修复时再深度挖
- **agent 标准不一**:3 个前端子代理可能用不同严重度标尺;主代理汇总时统一

## 不做

- 不改任何代码
- 不动测试
- 不审 `experiments/`、`docs/`、`data/`、`release/`
- 不审 Rust 代码(除非严重安全问题)
- 不实施 plan(后续 sprint 单独跑)