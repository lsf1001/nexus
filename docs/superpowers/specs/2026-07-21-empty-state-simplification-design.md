# Nexus 空态简化与字号上调设计

> 单一设计文档：覆盖 2026-07-21 用户截图反馈"这些字太小了,再看看这些功能有没有必要"
> 的全部前端改动。所有改动已与当前代码基线对齐,见"代码现状"一节。
>
> 路线图:本文 → 用户 review → writing-plans 写实现计划 → subagent-driven 执行。

---

## 1. 背景

2026-07-20 用户在新装 DMG Nexus.app 截图(已确认 `v1.5.4` 正确)中发现:

- **侧栏左下角 `设置 v1.5.4` / `online` 指示** 整体视觉偏小
- **顶栏右上 `命令 ⌘K` 按钮** 占位偏大、文案"命令"多余(macOS 用户只看 `⌘K`)
- **首屏 EmptyState 的 4 个 prompt 卡片 + "任务状态"卡** 把首屏占满,
  字号偏小(13px 卡片 / 12px 状态卡),且状态卡 4 行(助手 / 连接 / 当前会话 /
  最近任务 50 条)大部分字段已在别处重复显示

**用户反馈原文**:"这些字太小了,再看看这些功能有没有必要"。

**Path 选择**:用户提供三个候选路径(A 修细节 / B 砍状态卡 / C 砍状态卡 + 改 chip + 删 ⌘K),
用户回复"3"(选 C,最激进的方案)。

**3 个澄清回答(用户拍板)**:

| 决策 | 用户回答 |
|------|---------|
| 任务状态卡去留 | 全砍(推荐) |
| 侧栏对话列表上限 | 6 条硬截断 |
| 顶部 ⌘K 按钮处理 | **删掉整个按钮**(不是改文案) |

---

## 2. 代码现状(事实基线)

### 2.1 EmptyState 当前形态

文件:`frontend/src/components/ChatArea/EmptyState.tsx`(106 行)。

- 三块渲染:**hero**(eyebrow / h1 / desc) → **prompt-grid**(`grid-cols-2`,
  4 个 `button.prompt-card`,`text-sm` 13px) → **status-card**(`text-xs`
  12px,4 行 row + 右键菜单)
- 字号共 3 档:12px / 13px / 16px(desc)
- 接收 props:`modelName / connectionState / activeConversationTitle /
  conversationCount / onInsertPrompt`(onSubmit 已 unused,传参但没调用)
- 砍掉 status-card 后,3 个 props(`modelName / connectionState /
  conversationCount`)在 EmptyState 内**完全无用**——只剩
  `activeConversationTitle` 没出现于当前 status-card(实际渲染"新任务(未保存)"),
  也无用。**结论:EmptyState props 大幅瘦身,只保留 `onInsertPrompt`**

### 2.2 ChatView 当前形态

文件:`frontend/src/components/desktop/ChatView.tsx`。

- 顶部 status bar(22px):左侧当前会话标题 + 右侧 `.cmd-k-trigger`(命令 ⌘K)
- 注释明示:`- 22px 顶栏(从 36 收):左侧当前标题 + 右侧 ⌘K 入口
  (替代已删的本地在线 pill / ThemeToggle)`(行 46)

### 2.3 Sidebar 当前形态

文件:`frontend/src/components/desktop/Sidebar.tsx`。

- `useConversationCrud` 调用 `/api/sessions?limit=50`(行 115)— 当前列表 50 条全渲染
- 已用 `useAppVersion()` 显示 `v1.5.4`(2026-07-20 commit 51 完成)
- 字号 `--font-2xs`(11px)用于对话项

### 2.4 StatusBar 当前形态

文件:`frontend/src/components/desktop/StatusBar.tsx`(代码上文未读,但代码图
索引有行 11-13 docstring:`"EmptyState 任务状态卡片里已经有'助手: <model>',
重复显示浪费状态条空间"` — **当 EmptyState 状态卡被砍,这段 docstring 注释
会反向成立**,必须同步修订,否则误导后续开发者。

### 2.5 CommandPalette 当前形态

文件:`frontend/src/components/desktop/CommandPalette.tsx`。

- 顶栏按钮删后,**快捷键 Cmd/Ctrl+K 仍全局生效**(走 `useKeyboardShortcuts`
  hook,CommandPalette 组件本身不动)
- Sidebar.tsx:18 + ShellLayout.tsx:23 注释明示"低频入口走 ⌘K 命令面板"
  — 删按钮后,这些注释变成"唯一可见入口 = 快捷键"

### 2.6 e2e 硬绑定(红线)

`frontend/e2e/helpers.ts:42`、`journey/journey-redesign.spec.ts:75`、
`journey/journey-quick-prompts-and-history.spec.ts:47,51` 都用:

```ts
page.locator('button.prompt-card', { hasText: '整理今天的待办' })
```

**硬约束**:

- `button.prompt-card` className 必须保留
- "整理今天的待办" 文本一字不改
- `QUICK_PROMPTS` 4 项全留(不能砍到 3 个)

---

## 3. 设计目标

1. **字号 +1 档**:所有 EmptyState 文字从 12/13 → 13/14(token `var(--font-sm)` /
   `var(--font-base)`)
2. **砍冗余**:状态卡 4 行删除(底部 StatusBar 已有"online"/"local";
   模型名由用户主动去 ModelSelector 看;当前会话标题在 ChatView 顶栏;
   50 条"最近任务"这个数字本身没意义)
3. **横向 chip**:4 个 prompt 改单行 chip 形态(`flex row + wrap + justify-center`),
   macOS Spotlight 风格,焦点更聚拢
4. **侧栏收敛**:对话列表上限 50 → 6,溢出隐藏滚动条
5. **砍顶栏 ⌘K 按钮**:用户从界面找不到 ⌘K 入口,只能靠快捷键 — 这是用户明确
   选择的权衡(若日后想恢复,在侧栏底部加 ⚙ 旁边的搜索图标即可,留扩展位)
6. **e2e 不破**:所有 prompt-card 选择器和"整理今天的待办"文本保持兼容

---

## 4. 设计详述

### 4.1 EmptyState 重构

**结构变化**(前后对比):

```
旧:
[ eyebrow "个人任务助手" ]
[ h1 "今天想让我帮你做什么？" ]
[ p desc ]
[ prompt-grid grid-cols-2 4 cards ]
[ status-card 4 rows + 右键菜单 ]

新:
[ h1 "今天想让我帮你做什么？" ]   ← 直接上 h1,eyebrow 砍
[ p desc ]                         ← desc 略上调 14 → 15px(text-sm 实际为 13)
[ prompt-row flex + chip × 4 ]     ← 横向 chip
```

**Props 收敛**:

```ts
// 旧
export interface EmptyStateProps {
  modelName: string;
  connectionState: 'connecting' | 'online' | 'offline';
  activeConversationTitle: string | null;
  conversationCount: number;
  onInsertPrompt: (text: string) => void;
  onSubmit: (text: string) => void;
}

// 新
export interface EmptyStateProps {
  onInsertPrompt: (text: string) => void;
}
```

调用方(ChatArea.tsx)同步瘦身 — 砍掉 4 个 prop 传参。

**chip 形态**(CSS 草图):

```css
.empty-state .prompt-row {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--space-2);
  max-width: 720px;
}
.empty-state .prompt-card {
  /* 保留 className,改名 "card" 实际是 "chip" 语义 */
  border: 1px solid var(--line);
  border-radius: 999px;          /* 圆角 chip */
  padding: 8px 16px;
  font-size: var(--font-sm);     /* 13px → 13,与原一致,但视觉更"按钮" */
  font-weight: 500;
  background: var(--paper);
  color: var(--ink);
  transition: hover bg + border;
}
```

注:`prompt-card` className **保留**(e2e 硬约束),新 CSS 把它画成 chip 形态。
不改 `onClick={onInsertPrompt}` 行为,右键菜单触发也保留(`openContextMenuAt`
拼"速记")。

### 4.2 ChatView 顶栏瘦身

**旧**(22px):
```
[ 当前会话标题 ]                                    [ 命令 ⌘K ]
```

**新**(22px 不变,但右侧空):
```
[ 当前会话标题 ]
```

**改动**:

- 删 `<button className="cmd-k-trigger">` 整个块(ChatView.tsx 行 59-66)
- 同步删 `.chat-status-bar .cmd-k-trigger` 相关 CSS(`shell.css` 行 367-407)
- `useKeyboardShortcuts` hook 注册的 Cmd/Ctrl+K 仍全局生效,
  CommandPalette 组件本体不变 — 只是 UI 上没有可见入口
- 注释 `Sidebar.tsx:18` + `ShellLayout.tsx:23` 中"低频入口走 ⌘K" 改为
  "低频入口走 ⌘K 命令面板(快捷键 Cmd/Ctrl+K,UI 无按钮入口)"

### 4.3 Sidebar 对话列表 6 条硬截断

**改动**:

- `useConversationCrud` 内 `apiFetch('/api/sessions?limit=50')` 改为
  `limit=6`(后端已支持 query param,不变 schema)
- 渲染侧 `.conv-list` 加 `overflow-y: auto; max-height: <计算值>` 让第 7+
  条不可见 + 滚动(预期:264px sidebar 宽度 × 11→12px 字号,首屏约 6-7 条)
- 字号上调:`.sidebar .conv-item` 由 `var(--font-2xs)` 11px 改
  `var(--font-xs)` 12px(整一档)

### 4.4 Sidebar 字号整体上调

| 元素 | 旧 | 新 |
|------|---|---|
| `.sidebar .brand` | 14px | 14px(不动) |
| `.sidebar .new-btn` | 13px | 13px(不动) |
| `.sidebar .search` | 12px | 12px(不动) |
| `.sidebar .conv-item` | 11px | **12px** |
| `.sidebar .footer`(设置 / v1.5.4) | 11px | **12px** |

设置按钮和 v1.5.4 标签一并上调到 12px,统一节奏。

### 4.5 EmptyState 字号整体上调

| 元素 | 旧 | 新 |
|------|---|---|
| h1 | 28px(`hero-title-2xl`) | 28px(不动) |
| desc | `text-sm` 13px | **`text-base` 14px** |
| prompt chip | `text-sm` 13px | `text-sm` 13px(不动 — chip 13px 视觉够大) |

**整体原则**:正文相关一律 +1 档(token:xs→sm、sm→base);标题不动;
chip 这种"按钮" 13px 已经够大,不动。

### 4.6 StatusBar docstring 同步修订

旧注释行 11-13(EmptyState 任务状态卡片里已经有'助手: <model>',
重复显示浪费状态条空间)— 状态卡被砍后,**StatusBar 仍是模型 + 连接的
唯一可见位置**,docstring 注释失去意义,改为:

```ts
/**
 * StatusBar — 桌面端底部状态条(2026-07-21 重定位)。
 *
 * 显示当前连接状态(online/connecting/offline)+ 运行模式(local),
 * 是模型 + 连接在主界面的唯一可见位置 — EmptyState 不再重复显示。
 */
```

---

## 5. 不在范围内(显式排除)

- **Prompt 数量 4 → 3**:用户未要求,`QUICK_PROMPTS` 保持 4 项
- **CHANGELOG / SPEC.md 同步**:本次是样式微调,不影响功能,CHANGELOG
  用一行 `style: 空态简化 + 字号上调` 即可(本 spec 不写 CHANGELOG 文案,
  留给 commit 阶段)
- **重打 DMG**:本任务结束时跑 `bash scripts/build_dmg.sh` 验证
- **字体族调整**:`tokens.css` 已全 token 化,无需再动
- **状态卡"只留 1 行" / "7 条 + 展开"**:用户已选"全砍 + 6 条硬截断"

---

## 6. 文件清单

### 修改

1. `frontend/src/components/ChatArea/EmptyState.tsx` — 砍 status-card +
   eyebrow + props 瘦身 + chip 形态
2. `frontend/src/components/ChatArea/constants.ts` — **不动**(e2e 硬绑定)
3. `frontend/src/components/desktop/ChatView.tsx` — 删 `.cmd-k-trigger`
4. `frontend/src/components/desktop/Sidebar.tsx` — `limit=50 → 6` +
   注释修订
5. `frontend/src/components/desktop/hooks/useConversationCrud.ts:115` —
   `limit=50 → 6`
6. `frontend/src/components/desktop/StatusBar.tsx` — docstring 同步
7. `frontend/src/components/desktop/styles/shell.css` — 删
   `.chat-status-bar .cmd-k-trigger*` 相关规则 + 侧栏字号 11 → 12
8. `frontend/src/components/desktop/styles/chat.css` — EmptyState
   `.prompt-card` chip 形态 + `.empty-state .prompt-row` flex

### 删除(代码)

- ChatView.tsx `.cmd-k-trigger` JSX 块
- shell.css `.chat-status-bar .cmd-k-trigger{, kbd, hover}` 全套规则
- EmptyState.tsx `.status-card` JSX 块

### 不删 / 保留

- `CommandPalette.tsx` 组件本体(快捷键 Cmd/Ctrl+K 仍生效)
- `useKeyboardShortcuts` 注册
- `QUICK_PROMPTS` 4 项

---

## 7. 验证(必跑,顺序)

1. `cd frontend && npm run lint` — 0 error
2. `cd frontend && npx tsc --noEmit` — 0 error
3. `cd frontend && npm run test:vitest` — 全过
4. `cd frontend && npm run test:e2e -- --grep "quick|prompts|empty"` —
   `button.prompt-card` + "整理今天的待办" 必须仍命中
5. `cd frontend && npm run build` — 无警告
6. `bash scripts/build_dmg.sh` — 版本号不动,本任务是样式调整,
   DMG 文件名仍为 `Nexus-1.5.4-arm64.dmg`(若想升版号走单独 commit)
7. 挂载 DMG → 启动 → 截图核对:
   - 首屏 EmptyState 显示 4 个 chip + h1 + desc,**无状态卡**
   - 侧栏对话列表 6 条封顶,字号明显比之前大
   - 顶栏右侧**无** ⌘K 按钮,但按 Cmd+K 仍能弹出命令面板

---

## 8. 风险点

1. **删 ⌘K 按钮 = 用户失去 UI 入口**。可恢复方案:在 Sidebar footer
   加一个 🔍 按钮调 CommandPalette(本任务**不做**,用户已选"删掉",
   若反悔在 plan 阶段补回)。SPEC 阶段已显式记下此权衡。
2. **`onInsertPrompt` chip 改后行为不变**。e2e 走
   `.prompt-card` selector + click() → onClick → onInsertPrompt 文本
   进 textarea — chip 形态不破坏这条链。
3. **sidebar 6 条硬截断是 UI 截断**,不是 API 截断。后端仍返回 6 条,
   用户看不到的会话**没法在 UI 上访问**(除非 Cmd+K 搜索)。这也是
   显式权衡,SPEC 阶段写入。

---

## 9. 提交策略

1. `refactor(empty-state): 砍状态卡 + 4 chip 横向 + props 瘦身`
2. `refactor(sidebar): 对话列表 6 条硬截断 + 字号 11→12`
3. `chore(chatview): 删顶栏 ⌘K 按钮(快捷键 Cmd/Ctrl+K 保留)`
4. `docs(statusbar): 同步 docstring — EmptyState 不再重复`

---

## 10. 设计已完成 — 请用户 review

接下来:等用户在本文上回复 OK / 改 X / 撤回 ⌘K 删除等。
通过后调 `superpowers:writing-plans` 出实现 plan。