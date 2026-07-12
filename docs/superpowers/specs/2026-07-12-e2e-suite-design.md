# Nexus "模拟人工" E2E 测试套件 — 设计

> 状态:approved(2026-07-12)
> 范围:Playwright E2E suite 重组 + 4 条 journey spec 新增 + 2 条 debug/diag 工具挪出

## 1. 目标与边界

**目标**:在用户视角下,验证 Nexus AI Gateway 从冷启动到日常使用的 4 条核心旅程,确保"模拟人工"路径上的每个关键节点都被覆盖。

**4 条 journey spec**(全部走真实 LLM,CI 必跑):

| Spec 文件名 | 用户故事 | 关键验证点 |
| --- | --- | --- |
| `journey-cold-start.spec.ts` | 新用户首次开 App → ChatView → 触发首次对话 | SetupView→ChatView 切换 / 4 个快捷 prompt 可点 / 首次 user+assistant 气泡 |
| `journey-multi-turn.spec.ts` | 重度用户同会话连发 3-5 条 → 后续回复引用前文 | 上下文累积 / 关键词回显 / "新会话"按钮清空 |
| `journey-hitl-workflow.spec.ts` | 敏感操作者触发 AGENTS.md 写入 → HITL 卡片出 → 批准 / 拒绝两种结局 | 批准流续接 / 拒结束 / Judge 输出不漏气泡 |
| `journey-resilience.spec.ts` | 用户聊天中 → 后端崩溃 → 重连后继续对话 | "正在连接本地助手" 文案 / "本地在线" 重连 / 重连后能发新问题 |

**不覆盖**(留给现有 10 条单点 spec):

- 设置页 CRUD — `settings.spec.ts`
- 微信通道绑定 / 解绑 — `wechat-channel.spec.ts`
- WS 鉴权协议契约 — `ws-auth-subprotocol.spec.ts`
- 含糊反问场景 — `clarification.spec.ts`
- LLM 拒答 UI 验证 — `reject-display.spec.ts`
- 单点 chat 主流程 — `chat-happy-path.spec.ts`
- 多轮主流程 — `multi-turn.spec.ts`
- HITL 真 LLM 路径 — `hitl-confirm.spec.ts`
- HITL mock 路径 — `hitl-confirm-mock.spec.ts`
- 重连基础验证 — `reconnect.spec.ts`

**debug/diag 工具挪出**:`debug-agnes-message.spec.ts` / `diag-ws-page.spec.ts` 是开发者排错工具,不是产品验收,挪到 `frontend/scripts/debug/`(非 Playwright testDir)。

## 2. 架构与组件

```
frontend/e2e/
├── helpers.ts                       # 现有,不动
├── journey/                         # 新增目录
│   ├── helpers.ts                   # 新增:journey 专用高层动作封装
│   ├── journey-cold-start.spec.ts   # 新增
│   ├── journey-multi-turn.spec.ts   # 新增
│   ├── journey-hitl-workflow.spec.ts# 新增
│   └── journey-resilience.spec.ts   # 新增
├── chat-happy-path.spec.ts          # 保留
├── multi-turn.spec.ts               # 保留
├── hitl-confirm.spec.ts             # 保留
├── hitl-confirm-mock.spec.ts        # 保留
├── reconnect.spec.ts                # 保留
├── clarification.spec.ts            # 保留
├── reject-display.spec.ts           # 保留
├── settings.spec.ts                 # 保留
├── wechat-channel.spec.ts           # 保留
└── ws-auth-subprotocol.spec.ts      # 保留

frontend/scripts/debug/              # 新增(非 Playwright 扫描)
├── debug-agnes-message.spec.ts      # git mv 自 e2e/
└── diag-ws-page.spec.ts             # git mv 自 e2e/
```

`playwright.config.ts` 不动,`testDir: './e2e'` 仍覆盖全部 12 条单点 + 4 条 journey。`frontend/scripts/debug/` 在 testDir 之外,不跑。

## 3. 数据流与执行模型

```
1. Playwright 启动 uvicorn (30000) + vite (30077)
   webServer.env 注入:
     MINIMAX_API_KEY: 来自 process.env
     ANTHROPIC_AUTH_TOKEN: 来自 process.env
     NEXUS_HOME: $TMPDIR/nexus-playwright-<pid>
     NEXUS_E2E_MOCK=0 (真 LLM;journey spec 走真 LLM,不走 mock)

2. workers=1, retries=2 (CI 时), timeout=90s (默认)
   每个 journey spec 顶层 test.setTimeout(180_000) — 真 LLM 1-2min 慢

3. journey spec 执行流程(伪代码):
   test('...', async ({ page }) => {
     test.setTimeout(180_000);
     await openHome(page);                    // 现有 helper
     // cold-start: 点击 prompt 或输入 + 等回复
     // multi-turn: 连发 3 条 + 验关键词回显
     // hitl-workflow: 触发写 AGENTS.md + 点批准/拒绝 + 验流续接或结束
     // resilience: 发一条 + killBackend() + 等离线 + restartBackend() + 等重连 + 再发
   });

4. 失败保留 trace + video + screenshot(已有 playwright.config 配置)
```

## 4. journey 专用 helpers(`e2e/journey/helpers.ts`)

**为什么单独一份**:现有 `helpers.ts` 偏底层(locator / 单次发送);journey 需要高层动作封装(连发 3 条 / 触发 HITL / 模拟网络中断)。放一起会污染单点 spec 的依赖面。

候选 helper(具体签名在 plan 阶段定):

| Helper | 行为 | 适用 journey |
| --- | --- | --- |
| `sendSequence(page, contents[], options?)` | 连发多条,等所有回复到位(返回各条回复) | multi-turn |
| `expectContextRecall(page, keywords[])` | 断言最后一条 assistant 含所有关键词 | multi-turn |
| `triggerHitlApprove(page, prompt)` | 发 prompt,等 .confirm-card 出,点 .confirm-approve,等流完 | hitl-workflow |
| `triggerHitlReject(page, prompt)` | 发 prompt,等 .confirm-card 出,点 .confirm-reject,等流结束 | hitl-workflow |
| `killBackend()` | 用 child_process 杀 uvicorn(30000 端口) | resilience |
| `restartBackend()` | 拉起 uvicorn,等 /health 通 | resilience |

**约束**:`killBackend` / `restartBackend` 必须复用 Playwright 已启动的 webServer(不要单独 spawn),否则端口冲突。实现:读 `playwright.config.ts` 的 webServer 命令,或更简洁地用 `pkill -f uvicorn.nexus.backend.main:app` 杀 + 等 /health 通。

## 5. 错误处理与重试策略

- **真 LLM 行为不稳定**(沿用 hitl-confirm.spec.ts:69-73 经验):
  - 用**确定性 prompt 模板**:写文件用 "用 edit_file 把 X 改为 Y, old_string='___NEVER_MATCH_42___', new_string='e2e_marker_xxx'" — LLM 几乎 100% 触发 write_file。
  - 拒绝路径用 "向 ~/.nexus/AGENTS.md 追加敏感内容" — 触发 HITL 拒。
- **CI 不稳**:`playwright.config.ts` 已有 `retries: process.env.CI ? 2 : 0`,journey 复用,无配置改动。
- **超时**:
  - spec 顶层 `test.setTimeout(180_000)`(对比现有 90_000)
  - expect polling interval:`[1s, 2s, 3s, 5s]`(现有默认是 `[500ms, 1s, 2s]`,journey 调宽避免假超时)
- **killBackend 失败**:resilience spec 用 try/catch,若后端没起来,killBackend 直接 throw 结束 test,不进入下一段。
- **状态污染**:journey 与现有 10 条单点 spec 共用 `NEXUS_HOME`,workers=1 串行,不会并发污染。但 journey-resilience 的 killBackend 会真正杀掉 webServer,后续 spec 全部要重启 — 由 Playwright `webServer` 配置的 `reuseExistingServer: !process.env.CI` 兜底。

## 6. 测试与验证

- **单元层**:`journey/helpers.ts` 自身不做单测(集成测试覆盖)。若 `sendSequence` 内部逻辑复杂(轮询 / 错误恢复),再用 vitest 测。
- **集成层**:4 条 journey spec 自身就是验证,跑通即交付。
- **冒烟**:重构后首次跑 14 条 spec(10 单点 + 4 journey)全过 → 验收。

## 7. 迁移与回滚

| Step | 操作 | 风险 |
| --- | --- | --- |
| 1 | 新建 `e2e/journey/` 目录 + 4 条 journey spec + `journey/helpers.ts` | 零风险(纯新增) |
| 2 | `git mv frontend/e2e/debug-agnes-message.spec.ts frontend/scripts/debug/` | 低风险(路径变化,git 跟踪历史保留) |
| 3 | `git mv frontend/e2e/diag-ws-page.spec.ts frontend/scripts/debug/` | 低风险 |
| 4 | 新建 `frontend/scripts/debug/README.md` 说明用法 | 零风险 |
| 5 | 新建 `frontend/e2e/README.md` 解释 10 单点 + 4 journey 角色 | 零风险 |
| 6 | `CHANGELOG.md` 加 "test(e2e): 4 条 journey spec + debug 工具挪出" 条目 | 零风险 |
| 7 | `playwright.config.ts` 不动 | 零风险 |

**回滚**:`git revert <commit>` 即可。

## 8. 文档更新

- 新建 `frontend/e2e/README.md` — 解释 10 条单点 + 4 条 journey 的角色和适用场景。
- 新建 `frontend/scripts/debug/README.md` — 说明 debug/diag 工具怎么用、为什么不在 e2e/。
- 更新 `CHANGELOG.md` — 加 §"test(e2e): 4 条 journey spec + debug 工具挪出 (2026-07-12)"。
- 更新 `frontend/e2e/journey/helpers.ts` 顶部 docstring — 说明 journey helpers 与 `e2e/helpers.ts` 的边界。

## 9. 风险与开放问题

- **真 LLM 时间**:4 条 journey 全跑完,乐观估计 8-12 分钟(CI 必跑时间翻倍)。如果 CI 配额吃紧,可考虑给 journey 加 `@slow` tag + CI 跑前 2 条 + nightly 跑后 2 条。本 spec **不强制**这一点 — 留给实施 plan 决定。
- **LLM 行为漂移**:journey 用的 prompt 是经验性"几乎 100% 触发",但不保证永远。如果某天 LLM 改了行为,journey spec 会间歇性失败 — 届时回到 prompt 工程。本 spec 接受这个风险。
- **`reuseExistingServer: !process.env.CI`**:resilience spec 的 killBackend 会把 webServer 杀掉,本地 reuseExistingServer=true 会让后续 spec 直接连被杀掉的 server → 全 fail。**实施时必须确认本地 dev 环境 resilience 跑完后,后续 spec 会触发 Playwright 重启 webServer,或人为重启。**