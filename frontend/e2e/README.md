# Nexus 前端 E2E 测试

Playwright + Chromium + 真实 uvicorn 后端 + 真实 LLM。配置在
`frontend/playwright.config.ts`,串行执行(workers=1,避免并发污染数据库),
CI 必跑 + retries=2 兜底。

## 测试分组

### 10 条产品验收 spec(`frontend/e2e/`)

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

### 4 条 user-journey spec(`frontend/e2e/journey/`)

模拟人工视角的端到端旅程,**全走真 LLM**,**CI 必跑**:

| Spec | 用户旅程 |
| --- | --- |
| `journey-cold-start.spec.ts` | 新用户冷启动 → 首次回复 |
| `journey-multi-turn.spec.ts` | 多轮上下文累积与回显 |
| `journey-hitl-workflow.spec.ts` | HITL 工作流:触发 → 批准 → 流续接 |
| `journey-resilience.spec.ts` | 网络中断 → 重连 → 继续对话 |

`journey/` 目录内自带 `helpers.ts`,封装 journey 专用高层动作
(`sendSequence` / `expectContextRecall` / `killBackend` 等),
与上层 `e2e/helpers.ts` 底层选择器封装分层。

## 运行

```bash
cd frontend
npm run test:e2e                       # 全部 14 条
npm run test:e2e -- e2e/journey/        # 只跑 journey
npm run test:e2e -- e2e/chat-happy-path # 只跑单条
```

## 调试工具

`frontend/scripts/debug/` 是开发者排错工具,**不是测试**。需手动
`npx playwright test frontend/scripts/debug/<file>` 跑,不进 CI。
详见 [frontend/scripts/debug/README.md](../scripts/debug/README.md)。