# Nexus 空态简化与字号上调实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 spec `docs/superpowers/specs/2026-07-21-empty-state-simplification-design.md` 的 4 块改动 — EmptyState 砍状态卡 + 4 chip、Sidebar 6 条硬截断 + 字号上调、ChatView 删 ⌘K 按钮、StatusBar docstring 同步。

**Architecture:** 单一独立样式 / 组件微调批次。每个 commit 单一意图,按 spec §9 顺序;CSS 改动与组件改动分 commit;e2e 硬约束 `button.prompt-card` + "整理今天的待办" 全程保留。

**Tech Stack:** React 19 + Vite 8 + Tailwind v4 + Vitest + Playwright + Tauri 2

---

## 文件结构

本计划修改文件清单(全部已存在于仓库):

| 文件 | 角色 | 改动 |
|------|------|------|
| `frontend/src/components/ChatArea/EmptyState.tsx` | 首屏空态引导组件 | 砍 status-card + eyebrow,4 prompt 改 chip 形态,props 5→1 |
| `frontend/src/components/ChatArea/index.tsx` | 聊天区主体 | EmptyState 调用处 props 同步瘦身 |
| `frontend/src/components/desktop/hooks/useConversationCrud.ts:115` | 会话 CRUD hook | `limit=50 → 6` |
| `frontend/src/components/desktop/Sidebar.tsx:17` | 侧栏组件 | 注释 "低频入口走 ⌘K" 补全说明 + 删除 `onSubmit`-related 行 |
| `frontend/src/components/desktop/ChatView.tsx:46-67` | 聊天视图外壳 | 删 `.cmd-k-trigger` JSX + 删 `handleOpenCommandPalette`(若变孤儿) + 注释更新 |
| `frontend/src/components/desktop/StatusBar.tsx:1-15` | 底部状态条 | docstring 反向成立修订 |
| `frontend/src/components/desktop/styles/shell.css` | 桌面端样式 | 删 `.chat-status-bar .cmd-k-trigger{, kbd, hover}` + 侧栏 `.task-item`/`.recent-panel`/`.sidebar-version` 字号 11 → 12 + `.sidebar-footer` 同步 |
| `frontend/src/components/desktop/styles/chat.css` | 聊天区样式 | `.empty-state` 的 `.prompt-row` flex + `.prompt-card` chip 形态 |

**不修改**:`QUICK_PROMPTS` 4 项 / `CommandPalette.tsx` 组件 / `useKeyboardShortcuts` 注册。

---

## 关键复用

- **`tokens.css`** 已定义 `var(--font-xs/sm/base/md)` — chip 用 `var(--font-sm)`、desc 用 `var(--font-base)`、sidebar 字号用 `var(--font-xs)`(=12px)
- **`Button` / `OpenContextMenuAt`** — EmptyState 保留 `openContextMenuAt` 调用,行为不变
- **`useChatAreaActions.insertPrompt`** — EmptyState `onInsertPrompt` 仍指向此 hook,链路不变

---

## 红线(全程不破)

- `frontend/e2e/helpers.ts:42` — `button.prompt-card` className 保留
- `frontend/e2e/journey/journey-quick-prompts-and-history.spec.ts:51` — "整理今天的待办" 文本一字不改
- `QUICK_PROMPTS` 4 项不删
- CommandPalette 组件本体不动(快捷键 Cmd/Ctrl+K 全局生效)

---

## Tasks

### Task 1: EmptyState 砍 status-card + eyebrow + props 瘦身

**Files:**
- Modify: `frontend/src/components/ChatArea/EmptyState.tsx`(全文 106 行)
- Modify: `frontend/src/components/ChatArea/index.tsx:213-221`(EmptyState 调用处)

- [ ] **Step 1: 改写 EmptyState.tsx**

完整新文件(替换全文):

```tsx
/**
 * 空态视图:h1 + 描述 + 4 个横向 chip 提示(2026-07-21 简化)。
 *
 * 砍掉旧版的 status-card(4 行状态信息已在 StatusBar / ChatView 顶栏 / Sidebar
 * 重复显示,造成首屏过载)与 eyebrow(12px 上小字幕对桌面端过小,直接 h1 上场)。
 *
 * 输入框已统一到底部 Composer(ChatArea 层渲染),本组件只负责引导内容。
 *
 * Props 收敛到 1 项:只需要把 prompt 文本注入 textarea。其他状态字段(modelName /
 * connectionState / activeConversationTitle / conversationCount)在 EmptyState
 * 内不再使用,由调用方保留用于其他视图。
 */

import { openContextMenuAt } from '../../lib/useContextMenuTrigger';
import { QUICK_PROMPTS } from './constants';

export interface EmptyStateProps {
  onInsertPrompt: (text: string) => void;
}

export function EmptyState({ onInsertPrompt }: EmptyStateProps) {
  return (
    <div className="empty-state flex w-full max-w-3xl flex-col items-center gap-10 px-6 py-16">
      <h1 className="hero-title-2xl text-balance text-center font-semibold tracking-tight text-foreground">
        今天想让我帮你做什么？
      </h1>
      <p className="max-w-xl text-center text-base leading-relaxed text-muted-foreground">
        Nexus 会在后台理解任务、选择模型、整理上下文和记录必要信息。
        你只需要把事情交给它。
      </p>
      <div className="prompt-row flex flex-wrap items-center justify-center gap-2">
        {QUICK_PROMPTS.map((prompt) => (
          <button
            key={prompt.title}
            type="button"
            className="prompt-card"
            onClick={() => onInsertPrompt(prompt.prompt)}
            onContextMenu={(e) =>
              openContextMenuAt(e, `${prompt.title}\n${prompt.prompt}`, '速记')
            }
          >
            {prompt.title}
          </button>
        ))}
      </div>
    </div>
  );
}
```

关键变更:
- 砍 `<div className="eyebrow ...">个人任务助手</div>`
- 砍 `<div className="status-card ...">...</div>`(整段含 4 row + 右键菜单)
- h1 / p 升级:`hero` 包裹 div 砍,`h1` / `p` 直接放,`p` 字号 `text-sm`(13px)→ `text-base`(14px)
- `prompt-grid grid-cols-2` → `prompt-row flex flex-wrap justify-center`
- `prompt-card` className **保留**(e2e 红线),但移除 `rounded-xl border bg-card px-4 py-3 text-left text-sm font-medium` 等 Tailwind 类 — 新形态完全交给 CSS(下个 Task 加 `.prompt-card` chip 规则)。保留 `transition` 不写,在 CSS 一次性给。

- [ ] **Step 2: 改 ChatArea 调用处 `frontend/src/components/ChatArea/index.tsx:213-221`**

旧:
```tsx
{isIdle ? (
  <EmptyState
    modelName={modelName}
    connectionState={connectionState}
    activeConversationTitle={activeConversationTitle}
    conversationCount={conversationCount}
    onInsertPrompt={insertPrompt}
    onSubmit={send}
  />
) : (
```

新:
```tsx
{isIdle ? (
  <EmptyState onInsertPrompt={insertPrompt} />
) : (
```

注:`modelName / connectionState / activeConversationTitle / conversationCount` 在 ChatArea 顶部仍被读取(`useStore` + props),不要删 — 仅删传参给 EmptyState 的那 4 行。

- [ ] **Step 3: 跑 lint / tsc / vitest**

```bash
cd frontend && npm run lint && npx tsc --noEmit && npm run test:vitest
```

期望:0 error / 0 type error / vitest 全过(若 vitest 报错 EmptyState props 不匹配,改对应测试)。

- [ ] **Step 4: 手动检查 — 跑 dev server 看 EmptyState**

```bash
cd frontend && npm run dev
```

打开浏览器(`http://127.0.0.1:30077`),进入空态(首次启动或新建对话后),确认:
- 无 eyebrow "个人任务助手"
- 无 status-card 4 行
- 4 个 prompt 排成一行(或换行),class 为 `prompt-card`

注:目前 `prompt-card` 还没样式(下一步加),视觉上会是裸 button 文本 — 这是预期中间态。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ChatArea/EmptyState.tsx frontend/src/components/ChatArea/index.tsx
git commit -m "refactor(empty-state): 砍状态卡 + eyebrow + props 5→1,4 chip 横向布局"
```

---

### Task 2: chip 形态 CSS

**Files:**
- Modify: `frontend/src/components/desktop/styles/chat.css`(定位 `.empty-state` / `.prompt-grid` / `.prompt-card`)

- [ ] **Step 1: 在 chat.css 找到现有 `.prompt-card` / `.prompt-grid` / `.empty-state` 规则**

```bash
grep -n "prompt-card\|prompt-grid\|empty-state" frontend/src/components/desktop/styles/chat.css
```

- [ ] **Step 2: 替换 `.prompt-card` + `.prompt-grid` 规则**

如果现有规则用 `.prompt-grid`,改为 `.prompt-row`(因 EmptyState.tsx 已改 className)。完整替换块(粘到 chat.css 内合适位置,优先放原规则处):

```css
/* 空态 prompt chip(2026-07-21 简化:砍状态卡后,4 个 chip 横向 chip-row,
   取代原 2×2 卡片网格。macOS Spotlight 风) */
.empty-state .prompt-row {
  width: 100%;
  max-width: 720px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
}
.empty-state .prompt-card {
  border: 1px solid var(--line);
  background: var(--paper);
  color: var(--ink);
  border-radius: 999px;
  padding: 8px 16px;
  font-size: var(--font-sm);
  font-weight: 500;
  white-space: nowrap;
  transition: background 0.15s ease, border-color 0.15s ease;
}
.empty-state .prompt-card:hover {
  background: var(--paper-2);
  border-color: var(--line-2);
}
.empty-state .prompt-card:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: 2px;
}
```

注:`text-base` Tailwind 类已被 EmptyState.tsx 写入 `<p>`,但 `tokens.css` 把 Tailwind 的 text-base 映射为 `1rem`(16px)— 这里要 14px,**不要用 text-base**,EmptyState 已改 `text-base`。等等,让我重新核:

`Tailwind v4 text-base = 1rem = 16px`。但用户要求 desc 从 13 → 14px。要 14px 必须用 `text-sm` (=0.875rem=14px) 或者写 `[14px]` 任意值,**不能**用 `text-base`。

**修正**:EmptyState.tsx 第 25 行 `text-base` 改为 `text-sm`。Tailwind v4 `text-sm = 0.875rem = 14px`(与 `var(--font-base)` 等价)。同步把空态 `desc` 字号契约写在这里:

CSS 内**只**管 `.prompt-card` chip 形态(`.empty-state .prompt-card`),不再写 desc 字号(由 Tailwind class `text-sm` 控)。

**修改本 Step 的最终 CSS 块**:

```css
/* 空态 prompt chip(2026-07-21 简化:砍状态卡后,4 个 chip 横向 chip-row,
   取代原 2×2 卡片网格。macOS Spotlight 风) */
.empty-state .prompt-row {
  width: 100%;
  max-width: 720px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
}
.empty-state .prompt-card {
  border: 1px solid var(--line);
  background: var(--paper);
  color: var(--ink);
  border-radius: 999px;
  padding: 8px 16px;
  font-size: var(--font-sm);
  font-weight: 500;
  white-space: nowrap;
  transition: background 0.15s ease, border-color 0.15s ease;
}
.empty-state .prompt-card:hover {
  background: var(--paper-2);
  border-color: var(--line-2);
}
.empty-state .prompt-card:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: 2px;
}
:root[data-theme="dark"] .empty-state .prompt-card {
  background: var(--paper-2);
}
:root[data-theme="dark"] .empty-state .prompt-card:hover {
  background: var(--paper-3);
}
```

**同时回改 EmptyState.tsx 的 desc 行**(`text-base` → `text-sm`),把 Task 1 第 25 行:

```tsx
<p className="max-w-xl text-center text-base leading-relaxed text-muted-foreground">
```

改为:

```tsx
<p className="max-w-xl text-center text-sm leading-relaxed text-muted-foreground">
```

(`text-sm` = 14px,符合 spec §4.5 "desc 14px"。)

- [ ] **Step 3: 跑 lint / tsc**

```bash
cd frontend && npm run lint && npx tsc --noEmit
```

期望:0 error。

- [ ] **Step 4: 手动核 — dev server 看 chip 形态**

```bash
cd frontend && npm run dev
```

打开浏览器看空态,确认:
- 4 chip 排成一行(或窄屏换行),圆角胶囊形,白底深字
- hover 背景变浅灰
- focus 时有 outline 焦点环
- 暗色主题下 chip 背景 = `var(--paper-2)`(深灰)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/desktop/styles/chat.css frontend/src/components/ChatArea/EmptyState.tsx
git commit -m "style(empty-state): prompt-card 改 chip 形态 + 横向 flex-row"
```

---

### Task 3: Sidebar 对话列表 6 条硬截断

**Files:**
- Modify: `frontend/src/components/desktop/hooks/useConversationCrud.ts:115`(改 limit)
- Modify: `frontend/src/components/desktop/Sidebar.tsx`(可选,改 `.recent-panel` 滚动行为)

- [ ] **Step 1: 改 `useConversationCrud.ts:115`**

旧:
```ts
const response = await apiFetch('/api/sessions?limit=50');
```

新:
```ts
const response = await apiFetch('/api/sessions?limit=6');
```

- [ ] **Step 2: 检查 Sidebar `.recent-panel` 是否需 CSS 调整**

```bash
sed -n '1625,1650p' frontend/src/components/desktop/styles/shell.css
```

若现有 `.recent-panel` 已含 `overflow-y: auto` + `max-height`,**不动**。
若没有,加(粘到合适位置,挨着 `.recent-panel`):

```css
.sidebar .recent-panel {
  max-height: calc(100vh - 280px);
  overflow-y: auto;
}
```

注:`calc(100vh - 280px)` 是粗估(让列表占据顶部品牌 + 搜索 + 新对话按钮 + 底部 footer 之外的空间)。精确值在浏览器手动调。如果当前已有更精确规则,**不动**,只确保列表不会无限增长。

- [ ] **Step 3: 跑 vitest**

```bash
cd frontend && npm run test:vitest
```

期望:全过(`useConversationCrud` 若有单测,断言仍是"加载后会话列表",6 条不影响)。

- [ ] **Step 4: 手动核 — dev server 看 Sidebar**

启动 dev server,确认:
- 数据库已存 ≥6 条会话时,Sidebar 只渲染前 6 条
- 若数据库 <6 条,显示全部
- 滚动条正常工作(若有 ≥7 条)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/desktop/hooks/useConversationCrud.ts frontend/src/components/desktop/styles/shell.css
git commit -m "refactor(sidebar): 对话列表 50→6 硬截断 + recent-panel 限高"
```

---

### Task 4: Sidebar 字号 11 → 12(同步 footer)

**Files:**
- Modify: `frontend/src/components/desktop/styles/shell.css`(改 `.task-item` / `.sidebar-version` / `.sidebar-footer` 等字号)

- [ ] **Step 1: 定位当前 11px 字号规则**

```bash
grep -n "font-2xs\|font-size: 11px\|font-size: var(--font-2xs)" frontend/src/components/desktop/styles/shell.css
```

预期命中:
- `.task-item`(行 143 附近)
- `.sidebar-version`(行 1560 附近)
- `.sidebar-footer`(行 1551 附近)

- [ ] **Step 2: 替换字号 token**

把以下出现的 `--font-2xs`(11px)→ `--font-xs`(12px):

- `.task-item` 整块字号
- `.task-item-body strong` / `.task-item-body span`(如有显式字号)
- `.sidebar-version` 字号
- `.sidebar-footer` 字号
- `.empty-tasks strong` / `.empty-tasks span`(空态"还没有对话"块,如适用)

**精确替换**(以 `sed -i '' 's/var(--font-2xs)/var(--font-xs)/g' frontend/src/components/desktop/styles/shell.css` 一把梭,只针对 sidebar 子树):

若 grep 命中行均位于 `.sidebar` 子树内,可一次性 sed 替换文件内所有 `var(--font-2xs)` → `var(--font-xs)`。否则手动逐行替换。

- [ ] **Step 3: 跑 lint / tsc / vitest**

```bash
cd frontend && npm run lint && npx tsc --noEmit && npm run test:vitest
```

期望:全过。

- [ ] **Step 4: 手动核 — dev server 看 Sidebar 字号**

确认对话列表 / 设置按钮 / `v1.5.4` / "还没有对话" 字号全部明显增大(肉眼可见,11 → 12px),且不破布局(264px sidebar 宽度仍能装下"设置 + v1.5.4" 一行)。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/desktop/styles/shell.css
git commit -m "style(sidebar): 字号 11→12px(token --font-2xs → --font-xs)"
```

---

### Task 5: ChatView 删 ⌘K 按钮

**Files:**
- Modify: `frontend/src/components/desktop/ChatView.tsx:46-67`(JSX + 注释)
- Modify: `frontend/src/components/desktop/styles/shell.css`(删 `.cmd-k-trigger` 全套规则)

- [ ] **Step 1: 在 ChatView.tsx 找到 `handleOpenCommandPalette` 是否仍被使用**

```bash
grep -n "handleOpenCommandPalette\|cmd-k-trigger\|nexus:open-command-palette" frontend/src/components/desktop/ChatView.tsx
```

预期:
- `handleOpenCommandPalette` 函数定义(若仅 `.cmd-k-trigger` 用,变孤儿)
- 事件监听器 `useEffect` 监听 `nexus:open-command-palette` 自定义事件

若 `handleOpenCommandPalette` 还被 useEffect 用于监听别处触发的事件(侧栏右键菜单等),**保留函数,仅删 button JSX**。
若只用 button,**整个删函数** + 它的 useEffect。

- [ ] **Step 2: 改 ChatView.tsx JSX(行 56-67)**

旧块:
```tsx
<header className="chat-status-bar" data-tauri-drag-region>
  <span className="chat-status-topic" title={currentConv?.title || '新任务'}>
    {currentConv?.title || '新任务'}
    {currentConv?.channel === 'wechat' && <span className="chat-status-channel">· 微信通道</span>}
  </span>
  <div className="chat-status-actions">
    <button
      type="button"
      className="cmd-k-trigger"
      aria-label="打开命令面板 (快捷键 Cmd+K / Ctrl+K)"
      title="命令面板"
      onClick={handleOpenCommandPalette}
    >
      <span>命令</span>
      <kbd>⌘K</kbd>
    </button>
  </div>
</header>
```

新块:
```tsx
<header className="chat-status-bar" data-tauri-drag-region>
  <span className="chat-status-topic" title={currentConv?.title || '新任务'}>
    {currentConv?.title || '新任务'}
    {currentConv?.channel === 'wechat' && <span className="chat-status-channel">· 微信通道</span>}
  </span>
</header>
```

注:删 `<div className="chat-status-actions">` 整个块。若后续要加新 actions,直接新建 wrapper。

- [ ] **Step 3: 改 ChatView.tsx 注释(行 46-49)**

旧注释:
```
*   - 22px 顶栏(从 36 收):左侧当前标题 + 右侧 ⌘K 入口(替代已删的本地在线 pill / ThemeToggle)
```

新注释:
```
*   - 22px 顶栏(从 36 收):左侧当前标题(右侧 ⌘K 入口已于 2026-07-21 砍掉,快捷键 Cmd/Ctrl+K 仍全局生效)
```

- [ ] **Step 4: 若 `handleOpenCommandPalette` 变孤儿,删函数**

```tsx
// 整段 useState + useEffect + handleOpenCommandPalette 都删
// 仅留: 监听 nexus:open-command-palette 事件的部分(若其他组件仍触发该事件)
```

判定方法:在仓库 grep `nexus:open-command-palette`:

```bash
grep -rn "nexus:open-command-palette" frontend/src/
```

若有 ≥2 处 dispatch,保留监听;若只有 ChatView.tsx 一处,删监听 + 函数。

- [ ] **Step 5: 删 `shell.css` 内 `.chat-status-bar .cmd-k-trigger*` 全套规则**

定位:
```bash
grep -n "cmd-k-trigger\|chat-status-actions" frontend/src/components/desktop/styles/shell.css
```

预期命中 5 处(行 368 / 385 / 390 / 404 + `chat-status-actions` 容器规则)。

删除规则(整段从 `.chat-status-bar .cmd-k-trigger {` 到下一个空行 / 下一个 class 选择器),包括:
- `.chat-status-bar .cmd-k-trigger`
- `.chat-status-bar .cmd-k-trigger:hover`
- `.chat-status-bar .cmd-k-trigger kbd`
- `.nexus-desktop[data-theme="dark"] .chat-status-bar .cmd-k-trigger kbd`
- `.chat-status-actions`(若仅给 cmd-k 用,删;若注释写"保留供将来扩展",**保留空规则**,但内容改为 `/* 暂未使用,留给后续扩展(2026-07-21) */`)

- [ ] **Step 6: 跑 lint / tsc / vitest**

```bash
cd frontend && npm run lint && npx tsc --noEmit && npm run test:vitest
```

期望:全过。

- [ ] **Step 7: 手动核 — dev server**

打开浏览器看顶栏:右上无 ⌘K 按钮,左侧仍显示当前会话标题。按 `Cmd+K`(mac)或 `Ctrl+K` 验证命令面板仍能弹出。

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/desktop/ChatView.tsx frontend/src/components/desktop/styles/shell.css
git commit -m "chore(chatview): 删顶栏 ⌘K 按钮(快捷键 Cmd/Ctrl+K 保留)"
```

---

### Task 6: 同步 StatusBar / Sidebar / ShellLayout 注释

**Files:**
- Modify: `frontend/src/components/desktop/StatusBar.tsx:9-14`(docstring)
- Modify: `frontend/src/components/desktop/Sidebar.tsx:18`(注释)
- Modify: `frontend/src/components/desktop/ShellLayout.tsx:23`(注释,如适用)

- [ ] **Step 1: 改 StatusBar.tsx docstring**

定位:
```bash
grep -n "EmptyState 任务状态\|不显示.*模型" frontend/src/components/desktop/StatusBar.tsx
```

旧(行 9-14):
```ts
/**
 * 底栏状态条 — WorkBuddy 极简 IDE 风格。
 *
 * 设计：20px 高单行，WorkBuddy IDE 状态条风格（等宽数字 / 连接点 / 极简文本）。
 * 钉在 chat-area-wrap 底部，主对话区 flex grow 占满剩余高度。
 *
 * 显示字段：
 *   - 连接状态点（online / connecting / offline 三色）
 *   - 右侧 spacer + "local" 提示
 *
 * **不显示**模型名 — EmptyState 任务状态卡片里已经有"助手: <model>"，
 * 重复显示浪费状态条空间。暂不显示 token 计数（input_tokens /
 * output_tokens）—— 后端未下发，留待接入。
 */
```

新:
```ts
/**
 * 底栏状态条 — WorkBuddy 极简 IDE 风格。
 *
 * 设计：20px 高单行，WorkBuddy IDE 状态条风格（等宽数字 / 连接点 / 极简文本）。
 * 钉在 chat-area-wrap 底部，主对话区 flex grow 占满剩余高度。
 *
 * 显示字段：
 *   - 连接状态点（online / connecting / offline 三色）
 *   - 右侧 spacer + "local" 提示
 *
 * **2026-07-21 重定位**：EmptyState 任务状态卡已砍,StatusBar 是模型 + 连接
 * 在主界面的唯一可见位置 — 后续如需显示模型名,应在此处加,不再回到 EmptyState。
 * 暂不显示 token 计数（input_tokens / output_tokens）—— 后端未下发，留待接入。
 */
```

- [ ] **Step 2: 改 Sidebar.tsx:18 注释**

旧:
```
 * 记忆 / 工具 / 技能走 ⌘K 命令面板，不常驻侧栏。
```

新:
```
 * 记忆 / 工具 / 技能走 ⌘K 命令面板(快捷键 Cmd/Ctrl+K,UI 无按钮入口),不常驻侧栏。
```

- [ ] **Step 3: 改 ShellLayout.tsx:23 注释(若适用)**

```bash
grep -n "⌘K\|命令面板\|低频入口" frontend/src/components/desktop/ShellLayout.tsx
```

若注释含"低频入口由 ⌘K 命令面板"字样,改为"低频入口由 ⌘K 命令面板(快捷键 Cmd/Ctrl+K,UI 无按钮入口)"。

- [ ] **Step 4: 跑 lint / tsc**

```bash
cd frontend && npm run lint && npx tsc --noEmit
```

期望:0 error。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/desktop/StatusBar.tsx frontend/src/components/desktop/Sidebar.tsx frontend/src/components/desktop/ShellLayout.tsx
git commit -m "docs(desktop): StatusBar / Sidebar / ShellLayout 注释同步 ⌘K UI 入口已删"
```

---

### Task 7: 端到端验证

- [ ] **Step 1: 全套 lint + tsc + vitest**

```bash
cd frontend && npm run lint && npx tsc --noEmit && npm run test:vitest
```

期望:0 error / 0 type error / vitest 全过。

- [ ] **Step 2: e2e 烟测 — `button.prompt-card` + "整理今天的待办" 仍命中**

```bash
cd frontend && npm run test:e2e -- --grep "quick|prompts|empty"
```

期望:全过(快速 prompt / history / 空态相关 e2e 用例)。若 `整理今天的待办` 文本 fail,说明 Tailwind 类名覆盖了文本,回查 EmptyState.tsx 第 38 行 `{prompt.title}` 是否仍正确绑定。

- [ ] **Step 3: 全量 build**

```bash
cd frontend && npm run build
```

期望:0 error,无警告。

- [ ] **Step 4: 重打 DMG**

```bash
bash scripts/build_dmg.sh
```

期望:产出 `release/Nexus-1.5.4-arm64.dmg`(版本号不变)。

- [ ] **Step 5: 视觉验证**

挂载 DMG → 拖入 `/Applications` → 启动 Nexus.app → 截图核对:
- 首屏 EmptyState 显示 h1 + desc + 4 chip,**无状态卡,无 eyebrow**
- chip 圆角胶囊形,白底深字,字号 13px
- 侧栏对话列表 ≤6 条,字号 12px
- 侧栏底部 `设置 v1.5.4` 字号 12px
- 顶栏**无** ⌘K 按钮,只剩当前会话标题
- 按 Cmd+K 仍弹命令面板

- [ ] **Step 6: 暗色主题复测**

切到暗色主题(设置 → 主题),重看 EmptyState / Sidebar / 顶栏:
- chip 背景 = `var(--paper-2)`(深灰)
- 字号不变(token 自动走 dark 分支)
- ⌘K 快捷键仍生效(若有需求测,按 Cmd+K 看 CommandPalette 暗色态正常)

- [ ] **Step 7: 跑后端测试 + ruff**

```bash
source .venv/bin/activate && pytest tests/ -q && ruff check nexus/
```

期望:全过(本任务不改后端,仅防回归)。

- [ ] **Step 8: Commit — 验证日志**

无新代码改动,无需 commit。若验证发现 bug,在对应 Task 末尾修复并 amend(本计划禁止 --amend 已有 commit,改用新增 commit "fix: ...")。

---

## 提交顺序(最终汇总)

按 spec §9:

1. `refactor(empty-state): 砍状态卡 + eyebrow + props 5→1,4 chip 横向布局`(Task 1)
2. `style(empty-state): prompt-card 改 chip 形态 + 横向 flex-row`(Task 2)
3. `refactor(sidebar): 对话列表 50→6 硬截断 + recent-panel 限高`(Task 3)
4. `style(sidebar): 字号 11→12px(token --font-2xs → --font-xs)`(Task 4)
5. `chore(chatview): 删顶栏 ⌘K 按钮(快捷键 Cmd/Ctrl+K 保留)`(Task 5)
6. `docs(desktop): StatusBar / Sidebar / ShellLayout 注释同步 ⌘K UI 入口已删`(Task 6)
7. 验证无 commit,DMG 在 release/ 目录(不入 git)

---

## 自审 checklist(Plan 完成时跑一次)

- [x] Spec §3 目标 5 项 → 5 个 Task 覆盖(EmptyState / chip / sidebar / ⌘K / 字号)
- [x] Spec §6 文件清单 8 项 → Task 1-6 全覆盖
- [x] e2e 红线 `button.prompt-card` + "整理今天的待办" — Task 1 Step 1 显式保留 className + 不改 `{prompt.title}`
- [x] `QUICK_PROMPTS` 4 项 — constants.ts 未列入 Modify 文件清单
- [x] CommandPalette.tsx 未列入 Modify 文件清单
- [x] 无 "TBD" / "TODO" / "待补" / "类似 Task N" 占位 — 全文用具体代码块
- [x] Tailwind 类 `text-base` 在 Task 2 Step 2 已修正为 `text-sm`(避免与用户要求的 14px 不一致)
- [x] StatusBar docstring 修订内容已具体写出

---

## 风险与回滚

- **chip 视觉不符预期**:若用户嫌 chip 太"扁"或太"按钮",调整 `padding: 8px 16px` → `padding: 10px 18px`,或加 `font-size: var(--font-base)`(=14px)
- **删 ⌘K 按钮导致用户找不到命令面板**:短期无解,只能靠用户口述"Cmd+K";长期方案见 spec §8 风险点 1 — 在 Sidebar footer 加 🔍 按钮
- **6 条硬截断隐藏了重要会话**:用户只能 Cmd+K 搜索;若用户投诉,在 SettingsView 加 "会话列表上限" 配置项(本期不做)

---

## 完成后

- 截图反馈用户,确认视觉与 spec 一致
- 若用户要求,跑 CHANGELOG.md 加一行 `## 1.5.5 / Unreleased - style: 空态简化 + 字号上调`