# Nexus 前端

Nexus 个人 AI 助手的前端界面。设计上**借鉴 WorkBuddy / Claude 的视觉密度
但不复刻**：紧凑 22px 顶栏 / 14px 底栏 / 720px 主区限宽 / ⌘K 命令面板。
**无账户 · 本地运行**，所有用户数据只在 `~/.nexus/`。

## 设计基线

完整设计事实（布局 / 视觉 token / 中间件链 / Tauri 配置 / 路由 / 测试契约）
见 **[`docs/designs/frontend.md`](../../docs/designs/frontend.md)**。本文档只
讲项目结构与开发命令。

> 不要直接复制"Claude Desktop 截图"或"WorkBuddy 截图"来决策——
> 所有 UI 决策先回到 [`docs/designs/frontend.md`](../../docs/designs/frontend.md)
> 的事实基线，看 Nexus 当前能力是否支撑。

## 技术栈

- **React 19** + **TypeScript**（strict）
- **Vite 8**（dev 监听 `:30077`；DMG webview `base='./'`，后端静态服务 `base='/app/'`）
- **Tailwind CSS v4**（CSS 变量设计 token，`data-theme` 驱动暗色）
- **Zustand 5**（状态切片在 `src/store/slices/`）
- **react-router v7**（HashRouter，视图路由 + Splash/Setup 门控）

## 启动

```bash
npm install
npm run dev          # 开发模式 :30077
npm run build        # tsc -b && vite build
npm run lint         # eslint
npm run preview      # vite preview
```

> 开发服务默认监听 **30077**。后端地址通过 `VITE_API_TARGET` 指定，默认 `http://localhost:30000`。

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `VITE_API_TARGET` | `http://localhost:30000` | 后端 HTTP/WS 地址（开发期 Vite 代理目标） |
| `VITE_NEXUS_WS_TOKEN` | `nexus-default-token` | 前端编译期 WS 鉴权 token，必须与后端 `NEXUS_WS_TOKEN` 一致 |
| `VITE_TAURI` | - | `tauri build` 触发 `beforeBuildCommand` 注入 `true`，让 `vite.config.ts` 切 `base='./'` |

## 目录结构

```
frontend/
├── src/
│   ├── components/
│   │   ├── ChatArea/        # 对话流：ChatBubble / Composer / MessageList / wsHandlers / 思考折叠 / ToolCallCard
│   │   ├── desktop/         # 桌面壳：ShellLayout(两列) / Sidebar / ChatView / DesktopShell /
│   │   │                    #           CommandPalette(⌘K) / PreferencesModal / StatusBar /
│   │   │                    #           ModelSelector / useBootstrap / useGlobalShortcuts
│   │   └── __tests__/       # 组件测试
│   ├── hooks/               # useWsConnection / useWsMessageRouter / useChatStream / useChatSend ...
│   ├── lib/                 # config.ts(DEFAULT_MODEL / DEFAULT_API_BASE) / api.ts / models.ts
│   ├── store/               # index.ts + slices/(sessions / conversationMessages / models / uiPrefs) + selectors
│   ├── styles/              # 设计 token 与 desktop 视觉系统
│   ├── App.tsx              # 路由根
│   └── main.tsx             # 入口
├── e2e/                     # Playwright 端到端（helpers.ts + *.spec.ts）
├── vitest.config.ts         # 单元测试配置（jsdom + `@` 别名）
└── vite.config.ts           # 端口 / 代理 / base 切换
```

> 模型与 API base 的默认值集中在 `src/lib/config.ts`，不再散落硬编码。
> 旧 `ModelSwitcher.tsx` / `ArtifactsPanel.tsx`（已被两列布局取代）已删除；
> 低频入口（记忆 / 工具 / 微信）通过 ⌘K 命令面板进入。

## 测试

```bash
npm run test:vitest        # 单元测试（vitest：纯函数 + RTL + jsdom，不依赖真实后端）
npm run test:vitest:watch  # watch 模式
npm run test:e2e           # Playwright E2E（需前后端均启动）
npm run test:e2e:ui        # Playwright UI 模式
npm run test:e2e:report    # 查看 E2E 报告
```

> 单元测试产物不入库。E2E 需先启动后端（`:30000`）与前端（`:30077`）。

## WebSocket 协议

前端通过 `ws://<host>/api/ws` 与后端建立长连接。**鉴权走 `Sec-WebSocket-Protocol`
子协议 `nxv1-<base64url(token)>`**，token **不再拼入 URL**（避免落入 access log / 浏览器历史）。

事件顺序（标准流）：

```
client send: { content, session_id? }
server send: session_created → thinking? → chunk* → final → done
```

- `session_created` 携带 `session_id`，前端用于后续同会话追问
- `chunk` 增量内容，累加应等于 `final.content`
- `thinking` 仅在模型支持思维链时出现
- `confirmation_request` 在 HITL 路径出现，前端弹 `<ConfirmationCard>`，回传 `interruptId / eventId`
- 连接断开后自动指数退避重连