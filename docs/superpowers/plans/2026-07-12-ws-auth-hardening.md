# Plan:WS 鉴权 + 前端密钥/默认 token 收紧

## 目标

收回 3 个安全债:

1. **前端 `lib/api.ts:1` 硬编码 `DEFAULT_TOKEN = 'nexus-default-token'`** — 静态替换进 Vite bundle,任何 clone 仓库的人无需启动 setup 就能"用默认 token 直连后端"。
2. **WS token 走 `?token=` URL query** — 进代理 access log、浏览器历史、错误堆栈。
3. **`desktop/SetupView.tsx:92` 复制 API key 尾 4 位到剪贴板** — 用户粘贴时把密钥前缀串错地方即等于泄漏密钥。

## 当前态(代码骨架)

- `frontend/src/lib/api.ts`:
  - `const DEFAULT_TOKEN = 'nexus-default-token'` 全局常量
  - `export const WS_TOKEN = (import.meta.env.VITE_NEXUS_WS_TOKEN as string) || DEFAULT_TOKEN`
  - 被 `useTauriWs.ts / useWebSocket.ts / ChatArea.tsx` 多处 import
- `frontend/src/hooks/useTauriWs.ts:79`:
  - 失败注入伪 error 帧,`error_code: 'ws_open_failed'`,`content: String(e)`,`retryable: true`
  - 当前 token 注入:`new URL(\`ws://${host}/api/ws?token=${encodeURIComponent(WS_TOKEN)}\`)`
- `frontend/src/components/ChatArea.tsx:299`:webSocket 客户端 URL 同样拼 `?token=`
- `frontend/src/components/desktop/SetupView.tsx`:
  - `:92` `onContextMenu={(e) => openContextMenuAt(e, apiKey ? '••••••' + apiKey.slice(-4) : '(空)', 'API 密钥')}` — 复制菜单文案把密钥末 4 位明文塞进去,触发复制 = 末 4 串走剪贴板
  - `:17` `saveModel` 无 `response.ok` 校验
- `nexus/backend/main.py:402`:
  - `if "token" not in websocket.query_params or not hmac.compare_digest(...)`: 服务端只认 query param
- 测试:`frontend/e2e/` 没有 WS 鉴权 e2e(`test_e2e_*` 是消息流式 + HITL,无 token 路径)。

## 实施步骤

### Phase 1:WS token 协议改 subprotocol(主要安全修复)

**WHY subprotocol 而不是 header**:浏览器 WS API **不**支持自定义 header(只有 `Sec-WebSocket-Protocol` + 标准 header);`Sec-WebSocket-Protocol` 在 RFC 6455 是允许的协商通道,服务端通过 `websocket.subprotocols` 拿到,使用前后仍走 `hmac.compare_digest` 校验,**不**进 URL,代理/历史/堆栈均不可见。

1. **后端** (`nexus/backend/main.py:402`)
   - 改读 `websocket.subprotocols`(list);若含 `nexus-v1.token=<value>`,先校验格式,再走 `hmac.compare_digest`
   - 仍然兼容旧 `?token=` 路径(1 个 minor 版本,打印 `DeprecationWarning` 日志),下个 major 版本移除
   - 后端 `accept` 时 `await websocket.accept(subprotocol="nexus-v1")`(让客户端能拿到对应 subprotocol)
   - 加配置 `NEXUS_WS_AUTH_QUERY_FALLBACK` 默认 `True`,关掉就走纯 subprotocol

2. **后端新增测试** `tests/test_ws_auth_subprotocol.py`
   - subprotocol 合法 → 通过
   - subprotocol 缺失 → 401 close(1011 policy violation)
   - subprotocol 格式错误 → 拒绝
   - hmac.compare_digest 长度差异 → 拒绝
   - query fallback 兼容路径仍可用

3. **前端** `frontend/src/hooks/useTauriWs.ts`
   - `new WebSocket(\`ws://${host}/api/ws\`, ['nexus-v1.token=' + WS_TOKEN])`(原生 WS subprotocols 数组)
   - 移除 URL 里 `?token=`
   - 失败帧不再 `String(e)`(见 Phase 3)

4. **前端** `frontend/src/components/ChatArea.tsx`
   - 同样改 subprotocol

5. **前端** `frontend/src/lib/api.ts`
   - `const DEFAULT_TOKEN = 'nexus-default-token'` **删除**
   - `WS_TOKEN = import.meta.env.VITE_NEXUS_WS_TOKEN` 直接断言非空;首启动 setup 强制用户配置 `VITE_NEXUS_WS_TOKEN`(在 `setup/useBootstrap.ts` 检查)
   - 运行时检查 `WS_TOKEN === 'nexus-default-token'` 时 console.error 并 throw(防止误用)

6. **新增 e2e** `frontend/e2e/ws-auth-subprotocol.spec.ts`
   - 启后端,使用 Playwright 注入 `WS_TOKEN`,验证握手 101 + subprotocol echo
   - 故意填错 token,验证 close 401

### Phase 2:`SetupView.tsx` API 密钥处理收紧

1. **`SetupView.tsx:92`** — 复制菜单文案禁止拼密钥末 4 位。改成"已复制"(留 placeholder 提示用户密钥已落 ~/.nexus/models.json)。
2. **`SetupView.tsx:17` saveModel** — 检查 `response.ok`,4xx/5xx 用 toast 报错并保留 modal。
3. **新增 `secretMask`** 工具 `frontend/src/lib/secret.ts`
   - `maskKey(key: string): string` — 返回 `'••••••' + key.slice(-4)` 仅用于 UI 显示,**不进**复制/剪贴板/onContextMenu
   - Lint rule(可选):`grep -rn "apiKey.slice" frontend/src` 应只命中 `secret.ts` 的 maskKey 实现
4. **测试** `frontend/e2e/api-key-clipboard.spec.ts`
   - SetupView 右键 API key 字段,验证剪贴板内容**不含**任何密钥前缀(只含 `'已复制'`)

### Phase 3:WS 错误帧去泄漏

1. **`useTauriWs.ts:79`** — 失败时只注入 `error_code: 'ws_open_failed'`,**不要** `String(e)`;Rust 内部 stack/路径不进协议层。
2. **`useWebSocket.ts:76`** — `JSON.parse` 失败时直接 `throw new Error('ws protocol: malformed frame')` 进 React error boundary,而非透传字符串。

### Phase 4:文档与变更说明

- `CHANGELOG.md`:security 列 3 项
- `docs/operations/quality.md`:补 §11 "WS token 安全规约"
- `docs/protocol/wire.md` 新建:**列**所有 wire-level 行为(token 来源 / 错误码 / 重连策略 / heartbeat)

## 风险与回退

- **subprotocol 不兼容老客户端**:保留 query fallback 1 个 minor version,通过 feature flag `NEXUS_WS_AUTH_QUERY_FALLBACK=false` 可立即关闭旧路径。
- **`DEFAULT_TOKEN` 删除破坏 CI**:CI 必须显式设 `VITE_NEXUS_WS_TOKEN`;在 `frontend/.env.example` 写入,在 CI workflow 注入 dummy。
- **`maskKey` 重构影响别处**:搜 `apiKey.slice` 仅 SetupView 一处;替换工作量很小。

## 验收

- `ruff check .` / `pytest tests/ -q` 全绿
- `npm run lint` 0 error
- `npm run test:e2e` 全过(新增 2 个 spec)
- 手动 `grep -rn 'DEFAULT_TOKEN\|?token=' frontend/src` 仅剩 query fallback 兼容路径(被 feature flag 控制)
- 手动 `grep -rn 'apiKey.slice' frontend/src` 仅命中 `secret.ts`
- 安全 checklist:任何"密钥 / token / API key"字符串**不**出现在网络协议层 URL / log / clipboard / console

## 实施顺序(commit 拆分)

1. `feat(ws-auth): subprotocol-based token, query fallback deprecated`
2. `feat(setup): api-key clipboard safe + saveModel response.ok guard`
3. `refactor(ws): drop raw String(e) in error frame`
4. `chore(security): drop DEFAULT_TOKEN default, setup-time required`
5. `docs(security): wire protocol spec + quality.md §11`
6. `test(ws-auth): subprotocol coverage + e2e`