# Nexus 前端全量重构（Claude 范式）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Nexus 前端从"自研 token CSS + 状态驱动视图"重构为"以 Claude 为设计标杆的现代化 agent 前端"——引入 shadcn/ui + Tailwind v4 组件体系、正式路由、三区布局（侧栏 / 对话流 / Artifacts 面板），同时 100% 保留既有 WebSocket 协议、后端契约与端到端测试契约。

**Architecture:** 保留现有已论证良好的分层（Zustand store slices、WsClient、useWsMessageRouter + 纯函数 wsHandlers、ChatArea hooks），仅将"视图层 / 样式层 / 导航层"替换为 Claude 范式。引入 react-router 管理视图；用 shadcn/ui 原语（Radix 封装）重建交互控件；设计 token 收敛到一套 CSS 变量（Tailwind v4 `@theme inline`），深色调延续项目既有的 `data-theme="dark"` 机制。Artifacts 面板作为可选右栏，由既有 `tool_result` / `final` 帧中带 artifact 标记的内容驱动。

**Tech Stack:** React 19 + TypeScript + Vite 8 + Tailwind CSS v4（`@tailwindcss/vite`）+ shadcn/ui（Radix primitives, `class-variance-authority`, `clsx`, `tw-animate-css`）+ react-router v7 + Zustand 5 + sonner（toast）+ react-markdown。

## Global Constraints

- **WS 协议契约不可改**：`StreamEvent.type` 联合类型（`thinking|chunk|final|done|tool_call|tool_result|error|...`）与标准流 `session_created → thinking? → chunk* → final → done` 必须原样保留；`useWsMessageRouter` 的 handler 表与 `wsHandlers` 纯函数不可改写语义。
- **鉴权机制不可改**：WS 子协议 `nxv1-<base64url>` 鉴权（`encodeWsTokenSubprotocol`），HTTP `Authorization: Bearer <VITE_NEXUS_WS_TOKEN>`；`getWsToken()` 缺失即抛错的逻辑保持。
- **E2E 契约优先**：`frontend/e2e/helpers.ts` 与 `frontend/e2e/journey/helpers.ts` 中的选择器（`.sidebar`、`.chat-area`、`.message-row`、`.nexus-desktop`、`model-switcher` 等）是 18 个 Playwright spec 的真相来源。**任何 DOM 变更若影响这些选择器，必须在同一任务内同步更新 helpers.ts**，禁止"先改 DOM 后补测试"。
- **TS strict 不可降级**：`tsconfig.app.json` 开了 `noUncheckedIndexedAccess` / `noUnusedLocals` / `verbatimModuleSyntax` / `erasableSyntaxOnly`。新增代码必须符合。
- **Vite 双 base**：Tauri 构建 `base: './'`、否则 `/app/`（FastAPI 挂载点）；`server.proxy` `/api` → `30000` 且 `ws:true` 保持。`resolve.alias` 中 `qrcode` 重定向浏览器版保持。
- **`.env.local` 只有 `VITE_NEXUS_WS_TOKEN`**，无默认值——保持强制注入。
- **样式体系单一化**：重构后全仓库只保留 Tailwind v4 + shadcn token 一套样式体系；删除 `ModelConfigModal.tsx`（唯一 Tailwind 使用点且为死代码）及 `index.css` 中冗余的 `.dark` / `prefers-color-scheme` 块。

---

## 当前状态（探查结论摘要）

- 技术栈已含 `tailwindcss@^4.3.0` + `@tailwindcss/vite`，但 `index.css` 仅 `@import "tailwindcss"` 且 `@theme` 只定义 3 色，约等于未启用。
- 样式 99% 为自研 token CSS：`tokens.css` + `shell.css`(810) + `chat.css`(1090) + `views.css`(749) + `responsive.css` + `preferences-modal.css`。语义类名（`.sidebar`/`.chat-area`/`.message-row`/`.nexus-desktop`/`model-switcher`）。
- 死代码：`ModelConfigModal.tsx`（362 行，全仓库无 import，含 4 处硬编码 `https://api.minimaxi.com/v1`，用 `confirm()` 弹窗）。
- 硬编码散落：`'MiniMax-M3'` 默认模型多处、`PreferencesModal.MODEL_OPTIONS` 写死 3 个且与后端 `/api/models` 不同源、`'https://api.minimaxi.com/v1'` 散落。
- `PreferencesModal` 控件用 `defaultValue`/`defaultChecked`，**未接 store**（改了无效）。
- `store/index.ts` 注释引用不存在的 `./selectors.ts`。
- 根目录 debug 脚本（`check*.mjs`/`debug*.mjs`/`sweep-*.mjs` 等）应迁 `scripts/debug/`。
- README 严重过时（引用 `ChatArea.tsx` 顶层、`ws://...?token=` 旧方案、错误 npm 脚本）。
- WS 层、store slices、ChatArea hooks 分层良好，**保留不改语义**。

## 设计对标（Claude 范式，精简）

1. **三区布局**：左栏（New chat / Search / Recents / Starred / Account）→ 中央对话流 → 右侧可选 Artifacts 面板（生成代码/HTML/SVG/markdown 时自动出现）。
2. **顶部模型切换器**：可在对话中途切换模型，上下文保留。
3. **底部 Composer**：文本域 + 发送/停止 + 附件(上传) + 思考开关 + 风格选择。
4. **消息三层结构**：用户输入块（无边框、加粗、左侧 1px 浅竖线）/ 模型响应块（极浅背景 #FAFAFA 级差）/ 悬停工具栏（复制 / 引用 / 重试，紧邻内容右上角，300ms 淡出）。
5. **代码块**：低饱和蓝灰语法高亮 + 右上角"已复制"微气泡。
6. **Artifacts**：把"对话"与"作品"分离，右侧面板可迭代、可复制、可导出。
7. **极简克制**：首屏 EmptyState 精心设计（4 个 QUICK_PROMPTS），降低认知负荷，地球色系、低对比、留白。

---

## Phase 0 — 分支与基线

### Task 0.1: 创建特性分支并锁定基线

- [ ] **Step 1: 建分支**

```bash
cd /Users/yxb/projects/nexus
git checkout -b refactor/frontend-claude
git push -u origin refactor/frontend-claude
```

- [ ] **Step 2: 记录基线测试数（用于回归门）**

```bash
cd frontend && npm install
npm run lint            # 记录当前 ruff 等价（前端用 tsc -b / eslint）
npx tsc -b --noEmit     # 必须 0 error 基线
npx vitest run          # 记录当前约 30 个单测通过数
npx playwright test     # 记录当前 18 个 e2e 通过数（需后端 30000 在跑）
```

- [ ] **Step 3: Commit**

```bash
git commit --allow-empty -m "chore: baseline for Claude-style frontend refactor"
```

---

## Phase 1 — 设计系统基座（Tailwind v4 + shadcn + token 收敛）

### Task 1.1: 安装依赖与路径别名

**Files:**
- Modify: `frontend/vite.config.ts`
- Modify: `frontend/tsconfig.app.json`, `frontend/tsconfig.json`
- Modify: `frontend/package.json`（新增 devDeps）

**Interfaces:** 提供 `@/*` → `./src/*` 别名与 Tailwind v4 插件，供后续所有任务 import。

- [ ] **Step 1: 安装依赖**

```bash
cd frontend
npm install tailwindcss @tailwindcss/vite class-variance-authority clsx tailwind-merge tw-animate-css
npm install -D @types/node lucide-react
npx shadcn@canary init
# 交互选择: Style=new-york, Base color=neutral(贴近 Claude 地球色), CSS variables=yes
# 生成 components.json / src/index.css 变量 / src/lib/utils.ts
```

- [ ] **Step 2: 写 `frontend/vite.config.ts`（激活 Tailwind v4 + 别名）**

```ts
import path from "path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  // 既有 server.proxy / base 逻辑保持
});
```

- [ ] **Step 3: 写 `frontend/tsconfig.app.json` 追加 paths**

```jsonc
{
  "compilerOptions": {
    "baseUrl": ".",
    "paths": { "@/*": ["./src/*"] }
  }
}
```

- [ ] **Step 4: 验证 `cn` 工具存在**

`frontend/src/lib/utils.ts` 应含：
```ts
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
export function cn(...inputs: ClassValue[]) { return twMerge(clsx(inputs)); }
```

- [ ] **Step 5: 冒烟测试**

```bash
npx tsc -b --noEmit && npm run dev   # 访问 :30077 应正常
```

- [ ] **Step 6: Commit**

```bash
git add frontend && git commit -m "feat(ui): bootstrap Tailwind v4 + shadcn token system + @ alias"
```

### Task 1.2: Claude 对齐的设计 token（收敛自研 CSS 变量）

**Files:**
- Modify: `frontend/src/index.css`（替换既有 `@theme` 3 色 + 删除 `.dark`/`prefers-color-scheme` 冗余）
- Delete: `frontend/src/components/desktop/styles/tokens.css`（并入 index.css 变量体系）
- Modify: `frontend/src/components/desktop/styles/shell.css` `chat.css` `views.css`（首轮仅改 token 引用，结构后续任务迁移）

**Interfaces:** 暴露 Tailwind 工具类 `bg-background text-foreground border-border` 等；深色调由 `data-theme="dark"` 驱动（兼容现有 `useDarkModeRoot`）。

- [ ] **Step 1: 写 `frontend/src/index.css` 顶部 token（Tailwind v4 + `@custom-variant` 复用 `data-theme`）**

```css
@import "tailwindcss";
@import "tw-animate-css";

@custom-variant dark (&:where([data-theme=dark], [data-theme=dark] *));

:root {
  --background: 0 0% 100%;
  --foreground: 220 14% 11%;
  --muted: 220 14% 96%;
  --muted-foreground: 220 9% 46%;
  --card: 0 0% 100%;
  --border: 220 13% 91%;
  --input: 220 13% 91%;
  --primary: 24 9% 18%;          /* Claude 近黑中性 */
  --primary-foreground: 0 0% 98%;
  --accent: 220 14% 96%;
  --accent-foreground: 220 14% 11%;
  --ring: 220 13% 60%;
  --radius: 0.75rem;
  /* 保留既有品牌色名以减小迁移面 */
  --color-ink: 220 14% 11%;
  --color-paper: 0 0% 100%;
  --color-line: 220 13% 91%;
}

:root[data-theme="dark"] {
  --background: 0 0% 7%;
  --foreground: 0 0% 92%;
  --muted: 0 0% 12%;
  --muted-foreground: 0 0% 58%;
  --card: 0 0% 9%;
  --border: 0 0% 16%;
  --input: 0 0% 16%;
  --primary: 0 0% 92%;
  --primary-foreground: 0 0% 9%;
  --accent: 0 0% 14%;
  --accent-foreground: 0 0% 96%;
  --ring: 0 0% 40%;
  --color-ink: 0 0% 92%;
  --color-paper: 0 0% 7%;
  --color-line: 0 0% 16%;
}

@theme inline {
  --color-background: hsl(var(--background));
  --color-foreground: hsl(var(--foreground));
  --color-muted: hsl(var(--muted));
  --color-muted-foreground: hsl(var(--muted-foreground));
  --color-card: hsl(var(--card));
  --color-border: hsl(var(--border));
  --color-input: hsl(var(--input));
  --color-primary: hsl(var(--primary));
  --color-primary-foreground: hsl(var(--primary-foreground));
  --color-accent: hsl(var(--accent));
  --color-accent-foreground: hsl(var(--accent-foreground));
  --color-ring: hsl(var(--ring));
  --radius-lg: var(--radius);
  --radius-md: calc(var(--radius) - 2px);
  --radius-sm: calc(var(--radius) - 4px);
}

@layer base {
  body { background-color: hsl(var(--background)); color: hsl(var(--foreground)); }
}
```

- [ ] **Step 2: 删除 `tokens.css`，将其唯一职责（颜色/间距/圆角/阴影/焦点环）并入上方变量**

- [ ] **Step 3: 在 `useDarkModeRoot` 中保留写 `data-theme` 逻辑（不变）；验证 `index.css` 中不再有 `.dark {` 与 `@media (prefers-color-scheme)` 独立块**

- [ ] **Step 4: 测试 token 契约（复用既有 `tokens-dark.test.ts` / `tokens-space-font.test.ts`，断言变量存在）**

```bash
npx vitest run tokens
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/index.css frontend/src/components/desktop/styles && git commit -m "feat(ui): consolidate design tokens into Tailwind v4 CSS-variable system"
```

### Task 1.3: 引入核心 shadcn 原语 + 主题/Toast 提供商

**Files:**
- Create: `frontend/src/components/ui/{button,input,textarea,dialog,dropdown-menu,scroll-area,tooltip,separator,tabs,sonner}.tsx`（shadcn add 生成）
- Create: `frontend/src/components/theme-provider.tsx`（包裹 `data-theme` 同步，复用 store `darkMode`）
- Modify: `frontend/src/main.tsx`（挂 `ThemeProvider` + `Toaster`）

**Interfaces:** 后续 ChatArea / Sidebar 直接 `import { Button } from "@/components/ui/button"`。

- [ ] **Step 1: 拉取原语**

```bash
npx shadcn@canary add button input textarea dialog dropdown-menu scroll-area tooltip separator tabs sonner
```

- [ ] **Step 2: 写 `frontend/src/components/theme-provider.tsx`**

```tsx
import { useEffect } from "react";
import { useStore } from "@/store"; // 复用既有 uiPrefs.darkMode

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const darkMode = useStore((s) => s.uiPrefs.darkMode);
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", darkMode ? "dark" : "light");
  }, [darkMode]);
  return <>{children}</>;
}
```

- [ ] **Step 3: 在 `main.tsx` 挂载**

```tsx
import { ThemeProvider } from "@/components/theme-provider";
import { Toaster } from "@/components/ui/sonner";
// 在 ErrorBoundary 内、App 外层包 ThemeProvider，并渲染 <Toaster />
```

- [ ] **Step 4: 验证**

```bash
npx tsc -b --noEmit
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ui frontend/src/components/theme-provider.tsx frontend/src/main.tsx && git commit -m "feat(ui): add shadcn primitives + theme/toast providers"
```

---

## Phase 2 — 路由与三区外壳（Claude 布局）

### Task 2.1: 引入 react-router 视图层

**Files:**
- Create: `frontend/src/router.tsx`
- Modify: `frontend/src/App.tsx`（Splash/Setup 门控后渲染 `<RouterProvider>`）
- Modify: `frontend/src/components/desktop/DesktopShell.tsx`（`view: 'setup'|'chat'` 状态驱动 → 路由驱动）

**Interfaces:** 路由表：`/chat`、`/chat/:sessionId`、`/settings`、`/search`、`/projects`（占位）。

- [ ] **Step 1: 安装**

```bash
npm install react-router-dom@^7
```

- [ ] **Step 2: 写 `router.tsx`**，将 `SetupView` 作为 `/setup` 路由守卫（未配置模型时重定向），`ChatView` 作为 `/chat` 主体，`PreferencesModal` 经 `/settings` 或弹层呈现。

- [ ] **Step 3: `App.tsx` 在 Tauri `runtime-status` 就绪后渲染 `RouterProvider`，未就绪仍 `SplashView`。**

- [ ] **Step 4: 更新 `e2e/helpers.ts` 中若依赖 `.nexus-desktop` 挂载点的选择器，确保路由切换后仍可定位（DOM 契约不变）。**

- [ ] **Step 5: 验证**

```bash
npx tsc -b --noEmit && npm run dev
```

- [ ] **Step 6: Commit**

```bash
git commit -m "feat(nav): introduce react-router for view routing (Claude three-region shell)"
```

### Task 2.2: 重建 Sidebar（Claude 左栏）

**Files:**
- Rewrite: `frontend/src/components/desktop/Sidebar.tsx`（保留 `.sidebar` 类名与 `data-testid`）
- Create: `frontend/src/components/desktop/SidebarSearch.tsx`（Search 入口 → `/search`）
- Reuse: `frontend/src/components/desktop/hooks/useConversationCrud.ts`（不变）

**Interfaces:** 顶部 New chat（→ `/chat`）、Search、Recents 列表（来自 `useConversationCrud`）、Starred（store 扩展占位）、底部 Account/版本号。

- [ ] **Step 1: 用 shadcn `Button`/`ScrollArea`/`DropdownMenu` 重建 Sidebar；保留扁平等宽 task-item + 当前态左竖条（视觉延续 Claude）。**

- [ ] **Step 2: 保留 `e2e` 选择器 `.sidebar`、`.task-item`、当前态 `.task-item--current`（或 `data-current`）。**

- [ ] **Step 3: 单测 `Sidebar.test.tsx` 仍通过（调整 import 路径）。**

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(shell): rebuild Sidebar as Claude-style left rail (new chat/search/recents)"
```

### Task 2.3: 三区 Shell 布局 + 顶部模型切换器

**Files:**
- Rewrite: `frontend/src/components/desktop/ShellLayout.tsx`（grid: sidebar | chat | artifacts）
- Rewrite: `frontend/src/components/desktop/ModelSwitcher.tsx`（顶部模型切换器，可中途换模型；保留 `model-switcher` 类/id）
- Create: `frontend/src/components/desktop/ArtifactsPanel.tsx`（右栏，默认隐藏，有 artifact 时出现）

**Interfaces:** `ModelSwitcher` 调用 store `setModelName`（来自 `/api/models`，非写死）；`ArtifactsPanel` 接收 `artifact` 状态（Phase 3 接入）。

- [ ] **Step 1: `ShellLayout` 用 CSS grid 三列，右栏 `ArtifactsPanel` 条件渲染（保留 `.chat-area` 容器契约）。**

- [ ] **Step 2: `ModelSwitcher` 改为读取 `/api/models` 动态列表（消灭 `PreferencesModal.MODEL_OPTIONS` 写死）；选中即 `setModelName`，可中途切换。**

- [ ] **Step 3: `ModelSwitcher.test.tsx` 仍通过。**

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(shell): three-region Claude layout + top model switcher (dynamic from /api/models)"
```

---

## Phase 3 — 对话体验（Claude 消息范式 + Artifacts）

### Task 3.1: 重建 ChatBubble（三层结构 + 悬停工具栏 + 代码块微气泡）

**Files:**
- Rewrite: `frontend/src/components/ChatBubble.tsx`（保留 `.message-row` / `data-role` 契约，`React.memo` + 相等比较器保留）
- Reuse: `frontend/src/lib/remarkPathLinkify.ts`、`frontend/src/lib/useContextMenuTrigger.ts`
- Reuse: `frontend/src/components/ChatArea/ToolCallCard.tsx`

**Interfaces:** props 不变（`message: Message`）；新增 hover 工具栏（复制/引用/重试）与思考块折叠；代码块用 shadcn 风格 + 复制微气泡。

- [ ] **Step 1: 用户块——无边框、`font-semibold`、左侧 1px `border-l`；助手块——`bg-muted`（≈#FAFAFA 级差）。**

- [ ] **Step 2: 悬停工具栏：`group-hover` 显隐，复制后 300ms 淡出"已复制"微气泡（复用 `useToast` 或 sonner）。**

- [ ] **Step 3: `ChatBubble.test.tsx`（含 thinking 变体）仍通过；必要时更新选择器至 `data-testid`。**

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(chat): rebuild ChatBubble with Claude three-layer structure + hover toolbar"
```

### Task 3.2: 重建 Composer（上传 / 思考开关 / 风格）

**Files:**
- Rewrite: `frontend/src/components/ChatArea/Composer.tsx`（保留发送/停止切换、`input` 状态契约）
- Create: `frontend/src/components/ChatArea/ComposerToolbar.tsx`（附件 / 思考 toggle / 风格 select）
- Reuse: `frontend/src/components/ChatArea/hooks/useChatSend.ts`、`useChatStream.ts`

**Interfaces:** 输出 `onSend(content)`、`onStop()`；思考开关绑定 `uiPrefs.showThinking`。

- [ ] **Step 1: 用 shadcn `Textarea` + `Button` + `Tooltip` 重建；附件按钮预留（本期不接真实上传，仅 UI + 禁用态，避免超范围）。**

- [ ] **Step 2: 思考 toggle 绑定 store `showThinking`。**

- [ ] **Step 3: `Composer.test.tsx` / `EmptyState.test.tsx` 仍通过。**

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(chat): rebuild Composer with attach/thinking-toggle/style controls"
```

### Task 3.3: EmptyState 精修 + Artifacts 接入

**Files:**
- Modify: `frontend/src/components/ChatArea/EmptyState.tsx`（保留 4 个 QUICK_PROMPTS，Claude 极简风）
- Modify: `frontend/src/components/ChatArea/hooks/wsHandlers.ts` 与 `useWsMessageRouter.ts`：在 `tool_result` / `final` 中识别 artifact 标记，写入 store 新 slice `artifacts`（不破坏既有语义，仅追加）
- Create: `frontend/src/store/slices/artifacts.ts`
- Modify: `frontend/src/components/desktop/ArtifactsPanel.tsx` 渲染 artifact（代码高亮 / markdown / SVG）

**Interfaces:** `artifacts: Artifact[]`；`ArtifactsPanel` 订阅该 slice；当非空时右栏显示。

- [ ] **Step 1: 定义 `Artifact` 类型（`kind: 'code'|'markdown'|'svg'|'html'`, `content`, `title?`），在 `wsHandlers.final` 中若 `message.artifact` 存在则 `pushArtifact`。**

- [ ] **Step 2: `ArtifactsPanel` 用 `react-markdown` + 语法高亮渲染；无 artifact 时不渲染（保持 `.chat-area` 全宽契约用于 e2e）。**

- [ ] **Step 3: 单测覆盖 `wsHandlers.final` artifact 分支（新增 `wsHandlers.artifact.test.tsx`）。**

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(chat): wire Artifacts right-panel from tool_result/final frames"
```

---

## Phase 4 — 功能对齐与交互

### Task 4.1: HITL / 澄清 / 微信通道迁移到新控件

**Files:**
- Rewrite: `frontend/src/components/ChatArea/ConfirmationCard.tsx`、`ClarificationForm.tsx`、`ErrorBanner.tsx`（用 shadcn `Dialog`/`Button`）
- Reuse: `frontend/src/components/WechatPluginModal.tsx`（保留 `qrcode` 逻辑，换壳 shadcn `Dialog`）
- Reuse: `frontend/src/components/desktop/channels/ChannelInbox.tsx`

**Interfaces:** 行为契约不变（DOM `data-testid` 保留供 e2e `hitl-confirm`/`clarification`/`wechat-channel` 用）。

- [ ] **Step 1: 三组件换 shadcn 外壳，保留交互与 `pendingConfirmation` / `pendingClarification` 状态流。**

- [ ] **Step 2: 跑 `npx playwright test hitl-confirm clarification wechat-channel` 全绿。**

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(chat): migrate HITL/clarification/wechat to shadcn primitives (behavior preserved)"
```

### Task 4.2: Preferences / Setup 真正接 store + 删除死代码

**Files:**
- Rewrite: `frontend/src/components/desktop/PreferencesModal.tsx`（`pref-model` 接 `setModelName`、思考/深色接 `setShowThinking`/`toggleDarkMode`；模型来源 `/api/models`）
- Rewrite: `frontend/src/components/desktop/SetupView.tsx`（首启配置；消灭硬编码 `'https://api.minimaxi.com/v1'`、`'MiniMax-M3'`，改读 `src/lib/config.ts`）
- Delete: `frontend/src/components/ModelConfigModal.tsx`（死代码 + 唯一 Tailwind 点）
- Create: `frontend/src/lib/config.ts`（`DEFAULT_API_BASE`、`DEFAULT_MODEL`、`WS_ENDPOINT` 等中央常量）

**Interfaces:** `config.ts` 暴露常量，供 SetupView/PreferencesModal/conversations 初始化复用。

- [ ] **Step 1: 写 `src/lib/config.ts` 集中常量；`SetupView`/`conversations.ts:32`/`PreferencesModal` 全部引用之。**

- [ ] **Step 2: `PreferencesModal` 所有控件接 store（消除 `defaultValue`/`defaultChecked` 假交互）。**

- [ ] **Step 3: 删除 `ModelConfigModal.tsx`；全局 grep 确认无残留引用。**

- [ ] **Step 4: `PreferencesModal`/Setup 相关单测仍通过。**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(config): centralize constants, wire Preferences to store, delete dead ModelConfigModal"
```

---

## Phase 5 — 清理、测试、文档

### Task 5.1: 修复残留引用 + 根目录 debug 脚本迁移

**Files:**
- Modify: `frontend/src/store/index.ts`（删除对不存在 `./selectors.ts` 的注释引用）
- Bash: 将根目录 `check*.mjs`/`debug*.mjs`/`sweep-*.mjs`/`repro-*.mjs`/`test-*.mjs` 移入 `scripts/debug/`

- [ ] **Step 1: 删除 `store/index.ts` 中 `./selectors.ts` 注释（该文件不存在）。**

- [ ] **Step 2: `git mv` 根目录调试脚本至 `scripts/debug/`，更新其中相对路径引用（如有）。**

- [ ] **Step 3: Commit**

```bash
git commit -m "chore: fix dangling selectors.ts ref, relocate debug scripts"
```

### Task 5.2: 全量回归（vitest + playwright + tsc）

- [ ] **Step 1: `npx tsc -b --noEmit` 0 error**

- [ ] **Step 2: `npx vitest run` 全部通过（约 30）**

- [ ] **Step 3: 后端起 30000，`npx playwright test` 全部通过（18 个 spec）**

- [ ] **Step 4: 若有选择器断裂，回到对应 Phase 任务同步修复 `e2e/helpers.ts`。**

- [ ] **Step 5: Commit**

```bash
git commit -m "test: full regression green after Claude-style refactor"
```

### Task 5.3: 文档重写

**Files:**
- Rewrite: `frontend/README.md`（路径/WS 子协议鉴权/`npm run` 脚本对齐现状）
- Modify: `AGENTS.md` / `SPEC.md` 前端章节（技术栈 Tailwind v4 + shadcn + react-router；删除对 `ChatArea.tsx` 顶层 / `ModelConfigModal` 的过时引用）

- [ ] **Step 1: README 重写，标注新结构、新脚本、WS subprotocol 鉴权。**

- [ ] **Step 2: AGENTS.md 更新技术栈与目录说明。**

- [ ] **Step 3: Commit**

```bash
git commit -m "docs: rewrite frontend README + sync AGENTS/SPEC"
```

---

## 自审清单（Self-Review）

1. **契约覆盖**：WS 协议（Phase 1 保留层）、E2E 选择器（每任务同步）、TS strict（每任务 tsc）、双 base/Vite proxy（Task 1.1 保持）——均已落到具体任务。
2. **占位符扫描**：无 TBD/TODO；每个代码步骤给出实际片段或明确"复用既有文件 X"。
3. **类型一致性**：`Artifact` 类型在 Task 3.3 定义并在 `artifacts` slice / `ArtifactsPanel` 一致使用；`config.ts` 常量在 Task 4.2 统一引用。
4. **风险点**：Phase 2 路由化可能触碰 e2e 挂载点 → Task 2.1 Step 4 强制同步 helpers.ts；Phase 3 Artifacts 为追加语义、不改既有 `final`/`tool_result` 行为 → 不破坏契约。

## 执行说明

- 每完成一个任务跑对应测试并 commit（频繁提交，便于回滚）。
- 任一 Phase 边界（尤其 Phase 1 结束、Phase 2 结束）需保证 `npm run dev` 可用 + 关键单测绿，再进下一 Phase。
- 若 Playwright 因 DOM 变更失败，先修 `e2e/helpers.ts` 选择器，禁止改测试期望值绕过。
