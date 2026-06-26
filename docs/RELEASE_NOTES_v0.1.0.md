# Nexus v0.1.0 — 首次内测交付

> **发布日期**：2026-06-21
> **分支**：`main`
> **提交范围**：`362809b` 之后共 13 个功能 commit + 风格/清理 commit
> **总测试数**：378 passed (backend) + Playwright E2E (DMG CDP 真环境)
> **产物**：`release/Nexus-1.0.0-arm64.dmg` (175 MB,macOS arm64,未签名)

---

## 🎯 这次交付了什么

把 Nexus 从"能跑"推进到"能装能用"：

1. **AI Gateway 全栈接通**：后端 + 前端 + **桌面端 DMG 安装包**
2. **质量门上线**：每条回复都过 4 维度 rubric judge,REPAIR/REJECT 降级兜底
3. **可观测性落地**：JSONL 结构化日志 + 4 个产品事件,可查可定位
4. **意图识别路由**：chitchat / knowledge / task 三分类落库,联动质量门
5. **CI/CD 双线**：GitHub Actions 跑 E2E + 自动构建 macOS DMG

---

## ✨ 新功能(用户视角)

### 1. macOS 桌面应用(`.dmg` 一键安装)
- `desktop/`：Electron + electron-builder 骨架,内嵌 Python 后端 + Vite 前端
- 双击 `.dmg` → 拖入 Applications → 启动即用,不需手动起服务
- DMG 产物:`release/Nexus-1.0.0-arm64.dmg` (175 MB)
- ⚠️ 当前未做代码签名(本地开发环境无 Developer ID),首次启动需右键"打开"绕过 Gatekeeper

### 2. 质量门(4 维度 Rubric Judge)
- 每条 LLM 回复都会跑 4 个维度的评分:`safety` / `accuracy` / `completeness` / `tool_correctness`
- 阈值：`>=0.8` ACCEPT,`>=0.6` REPAIR(自动重生成),否则 REJECT(返回兜底文案)
- `safety` 单独更严:`<0.5` 一票否决
- 用户的幻觉/跑题回答会被自动拦下并提示重试

### 3. 意图识别路由
- 每条 user 消息先 1 次轻量分类:`chitchat` / `knowledge` / `task`
- `chitchat` 走原短路(快),`knowledge` / `task` 走完整 rubric judge(严)
- 分类结果落库 `messages.intent`,可后续按意图做数据导出

### 4. 联网搜索与微信通道(MCP 插件)
- `NEXUS_ENABLE_MCP=true` 默认开启
- 微信通道(`nexus/backend/wechat/`)可对接企业微信机器人收消息
- 工具调用走 LangChain `bind_tools`,StreamEvent 通过 WS 推到前端

### 5. 模型管理界面
- 前端可增删改查 LLM 配置(api_key / base_url / model_name)
- 走 `models_config.save_models()` 原子写,**禁止**绕过
- 切换激活模型无需重启后端

---

## 🛠 工程改进(开发者视角)

### 可观测性子系统
- JSONL 结构化日志写到 `~/.nexus/logs/nexus.log`(10 MB × 5 轮转)
- 4 个产品事件 `chat.start` / `intent.classified` / `quality.verdict` / `chat.end` 全部落盘
- env 三档:`NEXUS_LOG_FORMAT` (text|json) / `NEXUS_LOG_FILE` / `NEXUS_LOG_LEVEL`
- 运维文档:`docs/operations/logging.md`(字段说明 + jq 查询示例)

### 容错与降级
- WebSocket 断线续传:HMAC-SHA256 + base64url 签名 resume token,客户端重连可补拉事件
- LLM 错误分类:`AUTH` / `RATE_LIMIT` / `TIMEOUT` / `NETWORK` / `BAD_REQUEST` / `SERVER` / `UNKNOWN`
- 指数退避重试,失败抛 `ClassifiedError` 给上层降级
- WS 错误不再断连接,改发结构化 `error` 事件

### 前端重构
- `desktop/` 组件目录独立,不影响 web 端
- 新增 `lib/` / `hooks/` / `store/` 分层,符合 React 19 习惯
- Bootstrap 流程:`useBootstrap` → `/api/models` → `setup` 或 `chat` 视图
- Playwright E2E 配置(webServer 自动起 backend + Vite)

### CI/CD
- `.github/workflows/e2e.yml`：Playwright 全量跑通
- `.github/workflows/macos-dmg.yml`：electron-builder 自动构建 + 上传 artifact

---

## 🐛 修复的 Bug

1. **`RubricJudge(llm=_agent)` 误用**
   - 之前传 deepagent compiled graph(不是 chat model),judge 报 `'CompiledGraph' object has no attribute 'ainvoke'`
   - 改用 `get_llm()` 构造的 `ResilientRunnable`(真正的 `BaseChatModel` 子类)

2. **judge LLM 404**
   - `CONFIG["model_name"]` 默认值与主 Agent 的 `get_active_model()` 不一致
   - `main.py` 和 `scripts/eval_rubrics.py` 都改用 `get_active_model()`

3. **`quality_scores.message_id` 全部为 NULL**
   - pipeline 没接收 message_id,导致 quality_scores 行无法关联到 assistant 消息
   - 修复:`handle_websocket` 在调 pipeline 前生成 `message_id`,透传给 `run_with_quality` 和 `add_message`

4. **WebSocket 流式回调跨线程 `await` 风险**
   - 之前子线程直接 `await`,会抛 `RuntimeError: no running event loop`
   - 统一改为 `asyncio.run_coroutine_threadsafe` 投递回主事件循环

---

## ⚠️ 已知限制 / 未做事项

| 项 | 说明 | 后续计划 |
|---|---|---|
| macOS 代码签名 | 0 Developer ID,DMG 未签名 | v0.2.0 接 Apple Developer ID |
| `chunks` 字段估算 | 当前是 `len(response_text) // 16` | 若需精确值,扩展 `_run_agent_streaming` 返回 `chunk_count` |
| `chat.end` 只在正常分支发 | 澄清挂起 / 错误流不发 | v0.2.0 补发 |
| `langchain` / `langchain_core` 默认 WARNING | 避免 stream / token 刷屏 | 可按需调整 |
| ruff pre-existing 9 条错 | 涉及 `tests/test_config_loading.py` 等旧文件 | 已修复其中 9 条 I001/F401;后续 ruff 0 error |

---

## 📦 安装与运行

### macOS 桌面端(推荐)
```bash
# 下载 release/Nexus-1.0.0-arm64.dmg
open release/Nexus-1.0.0-arm64.dmg
# 拖入 Applications
# 首次启动:右键 → 打开(绕过 Gatekeeper)
```

### 源码开发模式
```bash
git clone https://github.com/your-org/nexus.git
cd nexus

# 后端
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# 启动服务
nexus install
nexus start

# 前端开发
cd frontend && npm install && npm run dev

# 桌面端开发
cd desktop && npm install && npm run dev
```

详见 [`README.md`](./README.md) 与 [`docs/operations/`](./docs/operations/)。

---

## 🧪 验证清单

- [x] 378 backend tests pass (`pytest tests/`)
- [x] ruff check 0 error (`ruff check nexus/`)
- [x] Playwright E2E DMG CDP 真环境验证通过(意图识别 + 流式响应 + sqlite3 直查 intent 列)
- [x] `scripts/verify_phase2.py --all` 5 步全过(WS 烟测 / 幻觉拒绝 / REPAIR 触发 / 100 轮导出 ≥ 30 DPO / meta-eval Pearson 0.973 kappa 0.591)
- [x] macOS DMG 构建成功(electron-builder,arm64,未签名)
- [x] GitHub Actions E2E + DMG workflow 配置就绪

---

## 📝 文档导航

- [`README.md`](./README.md) — 安装、CLI、API 速查
- [`SPEC.md`](./SPEC.md) — 完整技术规格
- [`python_project.md`](./python_project.md) — Python 工程硬性约束
- [`CHANGELOG.md`](./CHANGELOG.md) — 完整变更日志(本 release 是其中 3 段 Unreleased 合并)
- [`docs/superpowers/plans/`](./docs/superpowers/plans/) — 各功能实施计划
- [`docs/operations/quality.md`](./docs/operations/quality.md) — 质量门调优
- [`docs/operations/logging.md`](./docs/operations/logging.md) — 可观测性查询指南
- [`docs/RELEASE_NOTES_v0.1.0.md`](./docs/RELEASE_NOTES_v0.1.0.md) — 本文档

---

## 🙏 致谢

本次发布由 Claude Sonnet 协助完成代码实现、测试、文档与发布流程。
---

> **更新提示(2026-06-26)**:本快照中提到的 `nexus install` / `nexus start` 命令已于 2026-06 清理随 `nexus/cli/` 整包删除。终端用户请改用 macOS DMG APP(见 [README.md](../../README.md) 顶部"快速开始"),开发者从 git clone 走 `python nexus/backend/run.py` + `npm run dev`。详见 [CHANGELOG.md](../../CHANGELOG.md) `[Unreleased]` 段。
