# Nexus 前端 E2E 测试

Playwright + Chromium + 真实 uvicorn 后端 + 真实 LLM。配置在
`frontend/playwright.config.ts`,串行执行(workers=1,避免并发污染数据库),
CI 必跑 + retries=2 兜底。

## 测试分组

### 9 条产品验收 spec(`frontend/e2e/`)

| Spec | 覆盖 |
| --- | --- |
| `chat-happy-path.spec.ts` | 单轮 user→assistant 主流程 |
| `multi-turn.spec.ts` | 3 条连发,验证顺序与滚到底 |
| `reconnect.spec.ts` | 编程式 WS 重连断言(`__nexusAppSockets`) |
| `hitl-confirm.spec.ts` | HITL 真 LLM 路径:写 AGENTS.md → 批准 |
| `hitl-confirm-mock.spec.ts` | HITL mock 路径(`NEXUS_E2E_MOCK=1`) |
| `clarification.spec.ts` | 含糊反问场景 |
| `reject-display.spec.ts` | LLM 拒答 UI 验证 |
| `settings.spec.ts` | 设置页 CRUD |
| `wechat-channel.spec.ts` | 微信通道绑定 / 解绑 |
| `ws-auth-subprotocol.spec.ts` | WS 鉴权协议契约 |

### 9 条 user-journey spec(`frontend/e2e/journey/`)

模拟人工视角的端到端旅程。**默认全走真 LLM**,mock 模式(`auth_401` /
`stop-mid-stream` / `quick-prompts-and-history` 三条)需显式
`NEXUS_E2E_MOCK=1`;**CI 必跑**。

| Spec | 用户旅程 | LLM |
| --- | --- | --- |
| `journey-cold-start.spec.ts` | 新用户冷启动 → 首次回复 | 真 |
| `journey-multi-turn.spec.ts` | 多轮上下文累积与回显 | 真 |
| `journey-hitl-workflow.spec.ts` | HITL 工作流:触发 → 批准 → 流续接 | 真 |
| `journey-resilience.spec.ts` | 网络中断 → 重连 → 继续对话(CI-only) | 真 |
| `journey-quick-prompts-and-history.spec.ts` | 4 个 QUICK_PROMPTS + Sidebar 历史切换 | mock |
| `journey-stop-mid-stream.spec.ts` | 流期间 send-button disabled + 流结束恢复 | mock |
| `journey-input-edge-cases.spec.ts` | 空 / emoji / 多语言 输入边界 | 真 |
| `journey-auth-401.spec.ts` | 模型密钥失效兜底(需 `NEXUS_E2E_SCENARIO=auth_401`) | mock |
| `journey-wechat-bound-receive.spec.ts` | 微信通道绑定状态切换(`/bind` mock) | 真后端 + route mock |

`journey-wechat-bound-receive` 是 plan Task 15 降级版:仅覆盖绑定卡
"未绑定 → 已绑定"反应性,收消息半段因后端无标准 inbound 端点暂留待后续。

### 不在 journey 套件里的功能(由 vitest 覆盖)

- **聊天消息里绝对路径 click-to-open + 图片内联缩略图**(2026-07-14 加)
  → `frontend/src/lib/__tests__/remarkPathLinkify.test.ts` (6 用例)
  + `frontend/src/components/__tests__/ChatBubble.test.tsx` (3 用例)
  点击直达 Preview/Finder 与 file→file 缩略图加载都是浏览器 / Electron
  WKWebView 原生行为(file 协议 → macOS handler,file→file 默认 allow),
  不在 Nexus 代码路径上;可控层(AST → DOM)由 vitest 100% 覆盖。

## 运行

```bash
cd frontend
npm run test:e2e                       # 全部 18 条
npm run test:e2e -- e2e/journey/        # 只跑 journey
npm run test:e2e -- e2e/chat-happy-path # 只跑单条

# 跑 mock 类 spec(默认 scenario = allow_nexus_write)
NEXUS_E2E_MOCK=1 npm run test:e2e -- e2e/journey/journey-auth-401
# 显式切到 auth_401 场景
NEXUS_E2E_MOCK=1 NEXUS_E2E_SCENARIO=auth_401 \
  npm run test:e2e -- e2e/journey/journey-auth-401
```

## 调试工具

`frontend/scripts/debug/` 是开发者排错工具,**不是测试**。需手动
`npx playwright test frontend/scripts/debug/<file>` 跑,不进 CI。
详见 [frontend/scripts/debug/README.md](../scripts/debug/README.md)。