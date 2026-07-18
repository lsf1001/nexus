# Nexus 前端

Nexus 个人 AI 助手的前端界面。以 **Claude Desktop** 为设计对标进行了全量重构：
三区布局（左栏 / 对话流 / Artifacts 右栏）、shadcn/ui 组件体系、动态模型切换器、
Artifacts 作品面板。

## 技术栈

- **React 19** + **TypeScript**（strict）
- **Vite 8**（dev 监听 `:30077`；DMG webview `base='./'`，后端静态服务 `base='/app/'`）
- **Tailwind CSS v4**（CSS 变量设计 token，`data-theme` 驱动暗色）
- **shadcn/ui**（基于 Radix primitives，原语落在 `src/components/ui/`）
- **Zustand 5**（状态切片在 `src/store/slices/`）
- **react-router v7**（HashRouter，视图路由 + Splash/Setup 门控）
- **sonner**（toast）

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

## 目录结构

```
frontend/
├── src/
│   ├── components/
│   │   ├── ChatArea/        # 对话流：ChatBubble / Composer / wsHandlers / 思考折叠 / ToolCallCard
│   │   ├── desktop/         # 桌面壳：ShellLayout(三区) / Sidebar / PreferencesModal / ModelSwitcher / ArtifactsPanel / WechatPluginModal
│   │   ├── ui/              # shadcn/ui 原语（button / textarea / dialog / dropdown-menu / tooltip …）
│   │   └── __tests__/       # ChatBubble / WechatPluginModal 等组件测试
│   ├── hooks/               # useWebSocket / useWsConnection / useTauriWs / useGlobalShortcuts …
│   ├── lib/                 # config.ts(DEFAULT_MODEL / DEFAULT_API_BASE) / api.ts / ws/ / utils(cn)
│   ├── store/               # index.ts + slices/(conversations / ui / artifacts …) + selectors.ts
│   ├── styles/              # 设计 token（tokens / tokens-dark / 空间字体）
│   ├── App.tsx              # 路由根
│   └── main.tsx             # 入口（ThemeProvider + Toaster）
├── e2e/                     # Playwright 端到端（helpers.ts + *.spec.ts）
├── vitest.config.ts         # 单元测试配置（jsdom + `@` 别名）
└── vite.config.ts           # 端口 / 代理 / qrcode 别名
```

> 模型与 API base 的默认值集中在 `src/lib/config.ts`，不再散落硬编码。
> 旧 `ModelConfigModal.tsx`（死代码）已删除，模型选择改由 `PreferencesModal` 直连 store。

## 测试

```bash
npm run test:vitest        # 单元测试（vitest：纯函数 + RTL + jsdom，不依赖真实后端）
npm run test:vitest:watch  # watch 模式
npm run test:unit          # 遗留 node --test（*.test.cjs）
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
- `artifact` 内容标记（`<-- artifact … -->` 包裹）由 `wsHandlers` 探测并推入 Artifacts 面板，**不改动 `StreamEvent` 联合类型**
- 连接断开后自动指数退避重连
