# Nexus 前端设计事实基线

> 当前代码 = 事实基线。本文档汇总 Nexus 前端的"唯一权威设计"，所有 UI / 视觉 /
> 路由 / 测试契约决策先回到这里，看 Nexus 当前能力是否支撑。日期化的旧设计稿
> （2026-06 / 2026-07 期间多轮回退的 Claude Desktop 重设计、灰阶主题、shadcn 切
> 换等）已清理，决策可追溯 Git 历史。

---

## 1. 产品定位

- 个人 AI 助理（OpenClaw 形态），**无账户 · 本地运行**
- 唯一分发渠道：macOS DMG（`release/Nexus-<version>-arm64.dmg`，当前 `v1.5.4`）
- 用户数据唯一持久目录：`~/.nexus/`（`models.json` / `nexus.db` / `logs/` / `AGENTS.md` / `skills/`）
- 设计语言：**借鉴 WorkBuddy / Claude Desktop 的视觉密度但不复刻**（紧凑 22px 顶栏 / 14px 底栏 / 720px 主区限宽 / ⌘K 命令面板）

---

## 2. 布局总览

### 2.1 整体形态

三栏桌面布局 — Sidebar / ChatArea / ArtifactsPanel(可折叠,默认折叠回退两栏):

```
┌──────────────────────────────────────────────────────────────────┐
│  22px 顶栏(chat-status-bar)                                       │  ← data-tauri-drag-region
├──────────┬──────────────────────────────┬────────────────────────┤
│          │                              │                        │
│ Sidebar  │  ChatArea(主区,max 760px)    │  ArtifactsPanel        │
│ 260px    │   - EmptyState(空态)         │  (可折叠,默认折叠)     │
│  - Logo  │   - MessageList(对话流)      │   - Head(filename)     │
│  - 搜索  │   - Composer(输入框)         │   - Tabs(Code/Md/      │
│  - 会话  │   - ToolCallCard              │     SVG/HTML)          │
│  - 设置  │     ·→ 在右侧查看(file 类)   │   - Body(渲染器)       │
│          │                              │   - Foot(meta)         │
├──────────┴──────────────────────────────┴────────────────────────┤
│  14px 底栏(status-bar,online/connecting/offline)                  │
└──────────────────────────────────────────────────────────────────┘
```

ArtifactsPanel 默认折叠(`artifactsCollapsed=true`),只有 ToolCallCard 联动(file-class
工具 + result ≥ 30 字符)或 ⌘+\ 快捷键才会展开。窄屏(≤768px)折叠 Sidebar 与 Artifacts,
主区占满。

低频入口(记忆 / 工具 / 微信 / 星标 / 删除等)由 ⌘K 命令面板 / Sidebar 行内按钮承担,
**不常驻侧栏**。

### 2.2 关键尺寸

| 元素 | 尺寸 |
|------|------|
| Sidebar 宽度 | 260px |
| ChatArea 主区列宽 | `minmax(320px, 1fr)`(先压缩,保证右栏可见) |
| ArtifactsPanel 列宽 | `minmax(240px, 380px)`(最小 240,最大 380) |
| 顶栏高度 | 22px(`data-tauri-drag-region`,让位 macOS traffic lights) |
| 底栏高度 | 14px(IDE 风格状态点 + local 提示) |
| Sidebar 顶部 drag 区 | 38px |
| 主区垂直 padding | 12px / 16px / 24px(按内容层级) |

### 2.3 视图（react-router v7 + HashRouter）

| 路径 | 视图 | 说明 |
|------|------|------|
| `/` | 重定向到 `/chat` 或 `/setup` | bootstrap 路由门控 |
| `/chat` | `ChatView` | 主对话流（默认） |
| `/setup` | `SetupView` | 模型未配置时强制进入 |
| `/preferences`（modal） | `PreferencesModal` | 设置弹窗（Provider + 界面 + 关于） |
| ⌘K | `CommandPalette` | 全局命令面板（搜索会话 / 切模型 / 触发 HITL） |

### 2.4 路由门控（bootstrap）

- `useBootstrap.ts` 在应用挂载时拉 `/api/bootstrap`：返回 `{ configured, ws_token, ... }`
- `configured=false` → 重定向 `/setup`，禁止进入 `/chat`
- `configured=true` → `/chat` 正常渲染，模型选择可用
- WS 连接：拿到 token 后用子协议 `Sec-WebSocket-Protocol: nxv1-<base64url(token)>` 建连

---

## 3. 视觉 Token

> 设计 Token 集中在 [`frontend/src/index.css`](../../frontend/src/index.css)。**深色由
> `data-theme="dark"` 驱动**（写到 `<html>` 与 `.nexus-desktop`，不写 `.dark` 类）。
> Tailwind 的 `dark:` 工具类通过 `@custom-variant dark` 响应 `data-theme`。

### 3.1 Token 分层

| 层级 | 用途 | Tailwind 工具类 | 语义 CSS 引用 |
|------|------|----------------|---------------|
| shadcn 核心 | `bg-background` / `text-foreground` / `border-border` 等 | ✓ | （HSL 三元组） |
| 品牌 | `--ink` / `--paper` / `--line` / `--space-*` / `--font-*` / `--sidebar-*` / `--focus-ring` | × | shell / chat / views.css 的 `var()` |

### 3.2 浅色 / 深色

浅色 token 挂 `:root`；深色覆盖用 `:root[data-theme="dark"]`（源码顺序在后，自动覆盖 light）。完整定义见 `index.css:19-159`。

### 3.3 字体

```
--font-sans: "Geist Variable", "SF Pro Display", "PingFang SC", "Avenir Next",
             ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
             "Segoe UI", "PingFang SC", "Hiragino Sans GB", sans-serif;
--font-mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
```

字号 token：`--font-2xs` 12px / `--font-xs` 13px / `--font-sm` 14px / `--font-base` 16px / `--font-md` 18px / `--font-lg` 22px / `--font-xl` 30px / `--font-2xl` 40px（基础档对齐 Tailwind 16px 基线）。v1.5.4 起所有字号 token 改写为 `calc(Npx * var(--fs))`，由 `useFontScaleRoot` 注入 `--fs` multiplier 在 `0.875 / 1 / 1.25` 三档线性缩放；Cmd+= / Cmd+- / Cmd+0 与设置页 radio 同步。

### 3.4 圆角 + 间距

- 圆角：`--r-sm` 9px / `--r-md` 12px / `--r-lg` 16px / `--r-xl` 20px / `--r-2xl` 28px
- 间距：`--space-1` 4px → `--space-7` 48px（4/8/12/16/24/32/48）

---

## 4. 核心组件

| 组件 | 路径 | 职责 |
|------|------|------|
| `DesktopShell` | `components/desktop/DesktopShell.tsx` | 应用根：路由 + 全局错误边界 + `data-tauri-drag-region` 注入 |
| `ShellLayout` | `components/desktop/ShellLayout.tsx` | 三栏 grid 布局（260px + minmax(320px,1fr) + minmax(240px,380px);折叠态回退两栏） |
| `Sidebar` | `components/desktop/Sidebar.tsx` | 多会话 + 搜索 + 新对话 + 设置入口 |
| `ChatView` | `components/desktop/ChatView.tsx` | 主对话容器（空态 / MessageList / Composer 切换） |
| `ChatArea` | `components/ChatArea/index.tsx` | 对话流核心（含 EmptyState / MessageList / Composer） |
| `Composer` | `components/ChatArea/Composer.tsx` | 输入框 + 发送 + 停止按钮 |
| `MessageList` | `components/ChatArea/MessageList.tsx` | 消息渲染（user / assistant / thinking 折叠 / tool_call） |
| `ModelSelector` | `components/ChatArea/ModelSelector.tsx` | 输入框上方模型选择器（chip + dropdown） |
| `CommandPalette` | `components/desktop/CommandPalette.tsx` | ⌘K 全局命令面板 |
| `PreferencesModal` | `components/desktop/PreferencesModal.tsx` | 设置弹窗（Provider 发现/导入 + 界面 + 关于） |
| `StatusBar` | `components/desktop/StatusBar.tsx` | 14px 底栏状态条 |
| `MemoryPanel` | `components/desktop/MemoryPanel.tsx` | ⌘K 调出的记忆面板 |
| `ArtifactsPanel` | `components/Artifacts/ArtifactsPanel.tsx` | 右栏产物面板（默认折叠,⌘+\ 展开;Code/Md/SVG/HTML 四种渲染器） |

### 4.1 快捷键

| 组合 | 行为 |
|------|------|
| ⌘N / Ctrl+N | 新建对话 |
| ⌘K / Ctrl+K | ⌘K 命令面板（聚焦搜索） |
| ⌘/ / Ctrl+/ | 聚焦 composer 输入框 |
| **⌘\ / Ctrl+\** | **折叠/展开右栏 Artifacts 面板** |
| Esc | 关闭最上层 modal |

### 4.2 已删除的旧组件（仅供历史参考）

- `ArtifactsPanel.tsx` — 右侧三栏布局已废，删除
- `ModelSwitcher.tsx` — 旧版侧栏/顶栏模型切换，删除（由 `ModelSelector` 取代）

---

## 5. 状态管理（Zustand 5）

```
src/store/
├── index.ts          # 组合 store
└── slices/
    ├── sessions.ts            # 会话列表 + 当前 sessionId
    ├── conversationMessages.ts # 当前会话消息流
    ├── models.ts              # 模型配置（来自 ~/.nexus/models.json）
    ├── uiPrefs.ts             # 界面偏好（showThinking / darkMode / starredIds）
    └── selectors.ts           # 复用 selector
```

约定：
- 切片按职责拆分，**不放** view-state（如 modal open）这种临时态进 store
- 持久化偏好走 `uiPrefs.ts`（localStorage），其余切片内存持有

---

## 6. WebSocket 协议

### 6.1 鉴权子协议（必读）

**token 走 `Sec-WebSocket-Protocol: nxv1-<base64url(token)>`**，**不再拼入 URL**：

```ts
const protocols = [`nxv1-${base64urlEncode(token)}`];
const ws = new WebSocket(`ws://${host}/api/ws`, protocols);
```

WHY：避免 token 落入 nginx access log / 浏览器历史 / 异常堆栈。

### 6.2 事件序列

标准流：

```
client send: { content, session_id? }
server send: session_created → thinking? → chunk* → final → done
```

HITL 流（中间件 `path_aware_hitl` 抛 GraphInterrupt）：

```
... → confirmation_request { interruptId, eventId, toolCall, preview }
   ↓ 前端弹 <ConfirmationCard>
client send: { interruptId, decision: "approve" | "reject" }
   ↓ 后端 resume
... → final → done
```

### 6.3 帧类型

| 帧 | 字段 | 说明 |
|----|------|------|
| `session_created` | `session_id` | 首次建连或新会话 |
| `thinking` | `content` | 模型思考过程（仅支持的模型） |
| `chunk` | `content` | 增量流式内容 |
| `confirmation_request` | `interruptId`, `eventId`, `toolCall`, `preview` | HITL 弹窗 |
| `final` | `content`, `message_id` | 完整回复 |
| `done` | - | 流结束 |
| `error` | `code`, `message` | 错误 |

### 6.4 重连

- `useWsConnection` 自动指数退避重连
- `connection.py` 后端通过 resume token 续接未完成的流（断线后用户无感）

---

## 7. Tauri 2 桌面壳

### 7.1 路径与角色

- `desktop/src-tauri/`：Rust 主程序（WebSocket relay + 窗口管理 + sidecar 拉起）
- `desktop/src/`：打包时从 `frontend/dist/` 复制的 SPA 静态产物
- `scripts/build_dmg.sh`：完整 build 流程（PyInstaller onedir → Rust `cargo tauri build` → hdiutil 打 DMG）

### 7.2 Sidecar

- Tauri 2 通过 `externalBin` 拉起 Python sidecar（PyInstaller onedir 单二进制）
- sidecar 启动 FastAPI 后端（默认 `:30000`，DMG 内修改为 loopback）
- 前端通过 WebSocket relay 与 sidecar 通信，**不再走 HTTP 跨域**

### 7.3 macOS chrome

- `data-tauri-drag-region` 属性：标记可拖拽区（顶栏 / Sidebar 顶部 38px）
- 自动 no-drag：所有 button / input / textarea / select / `[role=button]` / `.task-item` / `.recent-panel` / `.empty-tasks`
- 实现见 `frontend/src/index.css:355-370`

### 7.4 开发期 fallback

- `launcher.py`（pywebview + uvicorn 后台线程）**仅作 dev/legacy fallback**，**不用于打 DMG**
- 生产 DMG 路径必须走 Tauri 2 + Python sidecar

---

## 8. 后端中间件链（前端需理解的部分）

> 完整后端设计见 [`SPEC.md`](../../SPEC.md)。前端只需理解这些 hook 何时触发：

```
[quality_gate → path_aware_hitl → dynamic_identity → force_tool]
```

| 中间件 | 前端表现 |
|--------|----------|
| `path_aware_hitl` | 工具调用目标命中"项目源码"时，前端收到 `confirmation_request` → 弹 `<ConfirmationCard>` |
| `quality_gate` | AGENTS.md 写入拦截，对前端透明 |
| `dynamic_identity` | 标题栏模型名实时同步当前驱动模型（不硬编码） |
| `force_tool` | knowledge 类问题自动 patch 检索工具，对前端透明 |

---

## 9. 测试契约

### 9.1 选择器约定（前端 e2e / 组件测试必须遵守）

| 选择器 | 含义 |
|--------|------|
| `.prompt-card` | 空态 4 个快捷 prompt |
| `.empty-state-composer` | 空态大输入框 |
| `textarea.message-input` | 普通 composer 输入框（对话中） |
| `.message-row.is-user` | user 气泡 |
| `.message-row.is-assistant` | assistant 气泡 |
| `.thinking-toggle` | 思考块折叠按钮 |
| `.thinking-content` | 思考块展开内容 |
| `.tool-call-card` | ToolCallCard 组件 |
| `.sidebar-search input` | 侧栏搜索框 |
| `.task-item` | 侧栏会话条目 |
| `.model-switcher-chip` | 顶栏 / 输入框上方模型 chip |
| `.theme-toggle` | 顶栏主题切换 |
| `.stop-button` | 停止按钮（Composer 内部） |
| `.chat-status-bar` | 顶栏 |
| `.wechat-plugin-modal` | 微信扫码绑定弹窗 |
| `.wechat-card` | 微信入口卡片 |
| `.channel-view` | 通道视图容器 |
| `.confirmation-card` | HITL 弹窗 |
| `.status-bar` | 14px 底栏状态条 |
| `.empty-state` | 空态根容器 |
| `.empty-state-send` | 空态发送按钮 |

### 9.2 单元测试

```bash
cd frontend
npm run test:vitest            # vitest：纯函数 + RTL + jsdom，不依赖真实后端
npm run test:vitest:watch      # watch 模式
```

### 9.3 E2E

```bash
cd frontend
npm run test:e2e               # Playwright（需前后端均启动）
npm run test:e2e:ui            # UI 模式
npm run test:e2e:report        # 查看报告
```

E2E 用 mock LLM（`NEXUS_E2E_MOCK=1`）跑稳态，真实 LLM 仅在 `journey-redesign.spec.ts` 部分场景使用。完整 journey 列表见 [`frontend/e2e/README.md`](../../frontend/e2e/README.md)。

### 9.4 关键回归用例

- `ws-auth-subprotocol` — 鉴权走子协议，不走 URL
- `hitl-confirm-mock` — HITL 三态路由：approve / reject / 中断后重连
- `router-context.test.tsx` — `RequireModelConfigured` 上下文转发
- `journey-redesign.spec.ts` — 10 个用户旅程（空态 / 新对话 / 多轮 / 工具调用 / 思考折叠 / 搜索 / 切模型 / 主题 / 微信 / 停止）

---

## 10. 开发约定

- **TypeScript strict 必开**，所有生产代码必须有显式返回类型
- **import 顺序**：React → 第三方 → 本地（`@/` 别名）
- **状态切片**：view-state 不入 store
- **样式**：CSS 变量 token + Tailwind v4 utility，**禁用**写裸 hex（除少数硬编码例外，例：toggle 激活色 `#2563eb` 避免打包 APP 中失效）
- **测试**：每个新功能先写测试，红 → 绿 → 重构
- **commit**：Conventional Commits，`feat` / `fix` / `refactor` / `docs` / `test` / `chore`

---

## 11. 文档同步规则

- 日期化的旧设计稿（`docs/superpowers/specs/2026-06-*`、`2026-07-17-*` 等）已清理
- 当前方向变更（如切回三栏、加新视图）**先改本文档**，再改代码
- SPEC.md / README.md / frontend/README.md 引用本文档为"事实基线"
- 任何跟本文档冲突的实现 = bug，先改文档对齐意图，再修代码

---

*最后更新：2026-07-20（统一权威设计基线）*