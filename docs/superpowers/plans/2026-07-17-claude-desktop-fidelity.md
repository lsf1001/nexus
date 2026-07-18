# 高保真 Claude Desktop 重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Nexus 桌面端 UI 从"偏好抽屉 + 微信通道 + 品牌块 sidebar"形态重构为高保真 Claude Desktop 形态:sidebar 极简(无品牌块/无 +新对话/无搜索/无 section 标题/无微信底栏),task-item 3px 竖条当前态,主区无 topbar 状态条,空状态只一行 hero + 大输入框,设置改成居中模态框,微信通道 UI 整轮删除(后端协议保留)。

**Architecture:** 分 6 步推进 — (1) PreferencesModal 替换 PreferencesDrawer 居中模态; (2) Sidebar 极简重写 + 3px 竖条当前态; (3) 主区删 chat-status-bar 顶部条; (4) EmptyState 删 prompt-grid/status-card; (5) 整轮删微信 UI(WechatPluginModal / channels/ 目录 / useChannelStatusPolling / 2 个 e2e); (6) 4 个老 e2e selector 更新 + 锁测试改写 + 新增 3px 竖条视觉锁测试; (7) tokens.css 删 --wechat token + tokens-dark.test.ts 锁测试改写; (8) 全栈验证 + CHANGELOG + DMG 重打。

**Tech Stack:** Vite + React 19 + Tailwind CSS 4 + Vitest(锁测试)+ Playwright(e2e)+ TypeScript 严格模式。

**Spec:** `docs/superpowers/specs/2026-07-17-claude-desktop-fidelity-design.md`

---

## File Structure

| 文件 | 责任 |
|-----|------|
| `frontend/src/components/desktop/PreferencesModal.tsx` | 新建 — 居中模态偏好(无 tab,5 行 setting-row) |
| `frontend/src/components/desktop/styles/preferences-modal.css` | 新建 — 模态样式 + 180ms 缩放进场动画 |
| `frontend/src/components/desktop/PreferencesDrawer.tsx` | 删除 |
| `frontend/src/components/desktop/styles/preferences-drawer.css` | 删除 |
| `frontend/src/components/desktop/Sidebar.tsx` | 重写 — 删 brand/new-task/search/section-title/footer-link,只留 flat task-list + 3px 竖条当前态 |
| `frontend/src/components/desktop/DesktopShell.tsx` | 改 — 删 wechatConnected / onOpenPreferences 参数化;清理 L67/88/103 注释 |
| `frontend/src/components/desktop/ShellLayout.tsx` | 同步删 onOpenPreferences 参数 |
| `frontend/src/components/desktop/ChatView.tsx` | 删 chat-status-bar + L53 channel === 'wechat' 条件分支 |
| `frontend/src/components/desktop/SetupView.tsx` | 删 L77 同款 chat-status-bar + 改 L71 注释 |
| `frontend/src/components/ChatArea/EmptyState.tsx` | 删 prompt-grid / status-card,只留 hero + 大输入框 |
| `frontend/src/components/ChatArea/constants.ts` | 删 QUICK_PROMPTS |
| `frontend/src/components/desktop/hooks/useGlobalShortcuts.ts` | 删 .wechat-plugin-modal-overlay,改 .preferences-drawer-overlay → .preferences-modal-overlay |
| `frontend/src/components/desktop/hooks/useGlobalShortcuts.test.ts` | 改 L64 onFocusSearch 测试 |
| `frontend/src/components/WechatPluginModal.tsx` | 删除 |
| `frontend/src/components/__tests__/WechatPluginModal.test.ts` | 删除 |
| `frontend/src/components/desktop/channels/ChannelViewBase.tsx` | 删除 |
| `frontend/src/components/desktop/channels/ChannelInbox.tsx` | 删除 |
| `frontend/src/hooks/useChannelStatusPolling.ts` | 删除 |
| `frontend/src/store/slices/channels.ts` | 删 channelInbox / addChannelInbox / clearChannelInbox(保留 pendingConfirmation) |
| `frontend/src/components/ChatArea/hooks/wsHandlers.ts` | 删 handleChannelMessage(保留 handleToolConfirm) |
| `frontend/src/components/desktop/styles/tokens.css` | 删 --wechat: #4a4a4a / #b5b5b5 |
| `frontend/src/components/desktop/styles/shell.css` | 删 .sidebar-brand / .btn-new-task / .sidebar-search / .sidebar-section-title / .sidebar-footer / .chat-status-bar / .prompt-grid / .prompt-card / .status-card |
| `frontend/src/components/desktop/styles/chat.css` | 同上补充删除 |
| `frontend/src/components/desktop/styles/views.css` | 删 .setup-view 双栏 + L546-580 .wechat-copy-inline 等微信规则 |
| `frontend/src/components/desktop/styles/responsive.css` | 删 mobile sidebar 3 列布局 |
| `frontend/src/main.tsx` | preferences-drawer.css → preferences-modal.css |
| `frontend/src/components/desktop/__tests__/Sidebar.test.tsx` | 删 wechatConnected 引用 + 新结构断言 |
| `frontend/src/components/desktop/styles/__tests__/a11y-polish.test.ts` | 改新 modal 契约 |
| `frontend/src/components/desktop/styles/__tests__/shell-sidebar-brand.test.ts` | 删品牌相关,改测 sidebar 结构 |
| `frontend/src/components/desktop/styles/__tests__/product-polish.test.ts` | 删 wechat 相关 + --wechat 断言 |
| `frontend/src/styles/__tests__/tokens-dark.test.ts` | 删 L139 'wechat' 字面 + L48-54 旧色值注释 |
| `frontend/src/components/desktop/styles/__tests__/task-item-current-rail.test.ts` | 新建 — 锁测试 3px 竖条 + ::before 伪元素断言 |
| `frontend/e2e/settings.spec.ts` | 改测模态框(.preferences-modal-overlay) |
| `frontend/e2e/wechat-channel.spec.ts` | 删除 |
| `frontend/e2e/journey/journey-wechat-bound-receive.spec.ts` | 删除 |
| `frontend/e2e/journey/journey-redesign.spec.ts` | 改 L62/L36 .chat-status-bar / L77/L24 .prompt-card / L258/L31 .sidebar-search input selector |
| `frontend/e2e/journey/journey-quick-prompts-and-history.spec.ts` | 改 L47/71 .prompt-card + .btn-new-task selector |
| `frontend/e2e/chat-happy-path.spec.ts` | 改 L27 button.btn-new-task selector |
| `frontend/e2e/helpers.ts` | 改 L42 .prompt-card 锁定 selector |
| `CHANGELOG.md` | 第十四轮 entry |
| `release/Nexus-1.3.0-arm64.dmg` | 重打 |

---

## Task 1: PreferencesModal 替换 PreferencesDrawer(居中模态)

**Files:**
- Create: `frontend/src/components/desktop/PreferencesModal.tsx`
- Create: `frontend/src/components/desktop/styles/preferences-modal.css`
- Delete: `frontend/src/components/desktop/PreferencesDrawer.tsx`
- Delete: `frontend/src/components/desktop/styles/preferences-drawer.css`
- Modify: `frontend/src/main.tsx`(import path 改名)
- Modify: `frontend/src/components/desktop/DesktopShell.tsx`(导入 PreferencesModal)
- Modify: `frontend/src/components/desktop/hooks/useGlobalShortcuts.ts`(selector 改名)

- [ ] **Step 1: 创建 PreferencesModal.tsx**

```tsx
// frontend/src/components/desktop/PreferencesModal.tsx
import { useEffect, useRef } from 'react';

export type PreferencesTab = 'general';

export interface PreferencesModalProps {
  open: boolean;
  onClose: () => void;
}

const MODEL_OPTIONS = [
  { value: 'MiniMax-M3', label: 'MiniMax-M3 (推荐)' },
  { value: 'MiniMax-M2', label: 'MiniMax-M2' },
  { value: 'claude-opus-4-8', label: 'Claude Opus 4.8' },
];

export function PreferencesModal({ open, onClose }: PreferencesModalProps): JSX.Element | null {
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open && dialogRef.current) {
      dialogRef.current.focus();
    }
  }, [open]);

  if (!open) return null;

  return (
    <div
      className="modal-overlay preferences-modal-overlay"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      role="presentation"
    >
      <div
        ref={dialogRef}
        className="preferences-modal"
        role="dialog"
        aria-modal="true"
        aria-label="偏好"
        tabIndex={-1}
      >
        <header className="preferences-modal-header">
          <h2>偏好</h2>
          <button
            type="button"
            className="preferences-modal-close"
            onClick={onClose}
            aria-label="关闭偏好"
          >
            ✕
          </button>
        </header>
        <div className="preferences-modal-body">
          <div className="setting-row">
            <label htmlFor="pref-model">当前模型</label>
            <select id="pref-model" defaultValue="MiniMax-M3">
              {MODEL_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>
          <div className="setting-row">
            <label>数据与隐私</label>
            <span className="setting-row-meta">本机保存 (~/.nexus/)</span>
          </div>
          <div className="setting-row">
            <label htmlFor="pref-thinking">显示思考过程</label>
            <input id="pref-thinking" type="checkbox" defaultChecked />
          </div>
          <div className="setting-row">
            <label htmlFor="pref-dark">深色模式</label>
            <input id="pref-dark" type="checkbox" defaultChecked />
          </div>
          <div className="setting-row">
            <label>高级设置</label>
            <span className="setting-row-meta">稍后开放</span>
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 创建 preferences-modal.css**

```css
/* frontend/src/components/desktop/styles/preferences-modal.css
 * 第十四轮:从 preferences-drawer(右滑)改为 preferences-modal(居中模态)。
 * 蒙层复用 .modal-overlay 基础样式,新类名 .preferences-modal-overlay。 */

.modal-overlay.preferences-modal-overlay {
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
}

.nexus-desktop[data-theme="dark"] .modal-overlay.preferences-modal-overlay {
  background: rgba(0, 0, 0, 0.7);
}

.preferences-modal {
  width: min(480px, 92vw);
  max-height: 88vh;
  background: var(--paper);
  color: var(--ink);
  border-radius: 16px;
  border: 1px solid var(--line);
  box-shadow: var(--shadow-lg);
  display: flex;
  flex-direction: column;
  animation: preferences-modal-in 180ms ease-out;
  outline: none;
}

@keyframes preferences-modal-in {
  from { opacity: 0; transform: scale(0.96) translateY(8px); }
  to   { opacity: 1; transform: scale(1) translateY(0); }
}

.preferences-modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 24px 14px;
  border-bottom: 1px solid var(--line);
}

.preferences-modal-header h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--ink);
}

.preferences-modal-close {
  background: none;
  border: 0;
  font-size: 16px;
  color: var(--ink-2);
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 6px;
}
.preferences-modal-close:hover {
  background: var(--paper-2);
  color: var(--ink);
}

.preferences-modal-body {
  padding: 8px 24px 24px;
  overflow-y: auto;
}

.preferences-modal-body .setting-row {
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: center;
  gap: 16px;
  padding: 14px 0;
  border-bottom: 1px solid var(--line);
}
.preferences-modal-body .setting-row:last-child {
  border-bottom: 0;
}

.preferences-modal-body .setting-row label {
  font-size: 13px;
  color: var(--ink);
  font-weight: 500;
}

.preferences-modal-body .setting-row-meta {
  font-size: 12px;
  color: var(--ink-3);
}

.preferences-modal-body select,
.preferences-modal-body input[type="checkbox"] {
  font-size: 13px;
  color: var(--ink);
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 6px 10px;
}
```

- [ ] **Step 3: 更新 `frontend/src/main.tsx` import**

把:
```ts
import './components/desktop/styles/preferences-drawer.css';
```
改为:
```ts
import './components/desktop/styles/preferences-modal.css';
```

- [ ] **Step 4: 更新 DesktopShell.tsx import + 类型**

找到 PreferencesDrawer 相关 import,改为:

```tsx
import { PreferencesModal } from './PreferencesModal';
```

(具体 import 位置以原 DesktopShell.tsx 为准,但 PreferencesDrawer 必须替换为 PreferencesModal)

- [ ] **Step 5: 删除 PreferencesDrawer.tsx 和 preferences-drawer.css**

```bash
git rm frontend/src/components/desktop/PreferencesDrawer.tsx
git rm frontend/src/components/desktop/styles/preferences-drawer.css
```

- [ ] **Step 6: 更新 useGlobalShortcuts.ts selector 链**

找到 `closeTopModal` 函数(约 L79-83),selector 列表:
- 旧:`'.wechat-plugin-modal-overlay, .preferences-drawer-overlay, .model-config-modal-overlay, .context-menu'`
- 新:`'.preferences-modal-overlay, .model-config-modal-overlay, .context-menu'`

- [ ] **Step 7: 跑测试验证不崩**

```bash
cd frontend && npm run test:vitest -- --run --reporter=verbose
```

预期:可能会有失败,因为 Sidebar 还引着 PreferencesDrawer。继续下一步。

- [ ] **Step 8: 提交**

```bash
git add frontend/src/components/desktop/PreferencesModal.tsx \
        frontend/src/components/desktop/styles/preferences-modal.css \
        frontend/src/components/desktop/PreferencesDrawer.tsx \
        frontend/src/components/desktop/styles/preferences-drawer.css \
        frontend/src/main.tsx \
        frontend/src/components/desktop/DesktopShell.tsx \
        frontend/src/components/desktop/hooks/useGlobalShortcuts.ts
git commit -m "feat(desktop): 偏好改居中模态 PreferencesModal

- 新建 PreferencesModal.tsx + preferences-modal.css
- 删除 PreferencesDrawer.tsx + preferences-drawer.css
- useGlobalShortcuts selector .preferences-drawer-overlay → .preferences-modal-overlay

第十四轮 Claude Desktop 高保真重构步骤 1/6"
```

---

## Task 2: Sidebar 极简重写 + 3px 竖条当前态

**Files:**
- Modify: `frontend/src/components/desktop/Sidebar.tsx`(整文件覆盖)
- Modify: `frontend/src/components/desktop/DesktopShell.tsx`(删 wechatConnected props)
- Modify: `frontend/src/components/desktop/styles/shell.css`(删 5 个老类名)
- Create: `frontend/src/components/desktop/styles/__tests__/task-item-current-rail.test.ts`

- [ ] **Step 1: 重写 Sidebar.tsx**

```tsx
// frontend/src/components/desktop/Sidebar.tsx
import type { Conversation } from '../../types';
import type { DesktopView } from './DesktopShell';

export interface SidebarProps {
  conversations: Conversation[];
  currentConversationId: string | null;
  onSelectConversation: (conv: Conversation) => void;
  onDeleteConversation: (id: string) => void;
  onNewTask: () => void;
  onOpenPreferences: () => void;
}

/**
 * 左侧栏 — 第十四轮:高保真 Claude Desktop 极简版
 *   - 无品牌块、无 +新对话按钮、无搜索 input、无 section 标题、无微信底栏
 *   - 顶部 38px 让位 macOS traffic lights
 *   - task-item 扁平列表,当前态左 3px 竖条
 *   - 底部一行 Nexus v1.3.0 版本号
 */
export function Sidebar({
  conversations,
  currentConversationId,
  onSelectConversation,
  onDeleteConversation,
  onNewTask,
  onOpenPreferences,
}: SidebarProps): JSX.Element {
  const sortedConversations = [...conversations].sort((a, b) => {
    const ta = new Date(a.updatedAt || a.createdAt).getTime();
    const tb = new Date(b.updatedAt || b.createdAt).getTime();
    return tb - ta;
  });

  const renderTask = (conv: Conversation): JSX.Element => {
    const active = conv.id === currentConversationId;
    const updated = new Date(conv.updatedAt || conv.createdAt);
    const title = conv.title || '新对话';

    const handleSelect = (): void => {
      onSelectConversation(conv);
    };

    return (
      <div
        key={conv.id}
        role="button"
        tabIndex={0}
        className={`task-item ${active ? 'is-current' : ''}`}
        onClick={handleSelect}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            handleSelect();
          }
        }}
        aria-current={active ? 'true' : undefined}
        aria-label={title}
      >
        <div className="task-item-body">
          <strong>{title}</strong>
          <span>
            {updated.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })}
          </span>
        </div>
        <div className="task-actions">
          <button
            aria-label={`删除对话 ${title}`}
            className="delete-btn"
            onClick={(event) => {
              event.stopPropagation();
              onDeleteConversation(conv.id);
            }}
            type="button"
          >
            ×
          </button>
        </div>
      </div>
    );
  };

  return (
    <aside className="sidebar">
      {/* 整列可拖(Tauri 2) */}
      <div className="sidebar-drag" data-tauri-drag-region />

      <div className="sidebar-task-list" aria-label="对话列表">
        {sortedConversations.length === 0 ? (
          <div className="empty-tasks">
            <strong>还没有对话</strong>
            <span>从右侧输入框开始,把事情交给 Nexus。</span>
            <button type="button" className="empty-tasks-cta" onClick={onNewTask}>
              + 开始新对话
            </button>
          </div>
        ) : (
          sortedConversations.map(renderTask)
        )}
      </div>

      <div className="sidebar-footer-version">
        <span>Nexus v1.3.0</span>
      </div>
    </aside>
  );
}
```

注意:`PreferencesDrawer` 类型的 import 不再需要(`PreferencesTab` 也删),改用 `PreferencesModal` 那个文件的命名空间,但本任务不触发 PreferencesModal props,只触发 `onOpenPreferences: () => void`。

- [ ] **Step 2: 更新 DesktopShell.tsx 调 Sidebar 的 props**

找到 `<Sidebar ... />` 渲染处:
- 删 `wechatConnected={...}` 和 `wechatInboxCount={...}` props
- `onOpenPreferences` 改成无参(`onOpenPreferences()`)

- [ ] **Step 3: 更新 shell.css — 删 5 个老类名 + 加新规则**

先 grep 当前 shell.css 看 `.sidebar-brand / .btn-new-task / .sidebar-search / .sidebar-section-title / .sidebar-footer / .task-item` 各定义在哪几行,然后:

删:`.sidebar-brand` / `.sidebar-brand-mark` / `.sidebar-brand-text` / `.sidebar-settings-btn` / `.btn-new-task` / `.sidebar-search` / `.sidebar-section` / `.sidebar-section-title` / `.conversation-count` / `.sidebar-footer` / `.footer-link` / `.footer-link--wechat` / `.wechat-inbox-badge` / `.channel-tag-inline` 全部规则

加:`.sidebar-drag` 38px 高(让位 macOS chrome)+ `.task-item::before` 伪元素竖条 + `.sidebar-footer-version` 底栏

新规则片段:

```css
.sidebar {
  /* 调整:grid-template-rows 改为 "38px minmax(0, 1fr) auto" */
}

.sidebar-drag {
  height: 38px;
  flex-shrink: 0;
}

.sidebar-task-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px 0;
}

.task-item {
  position: relative;
  padding: 8px 14px 8px 17px;
  cursor: pointer;
  border-radius: 0;
}
.task-item::before {
  content: '';
  position: absolute;
  left: 0;
  top: 6px;
  bottom: 6px;
  width: 3px;
  background: transparent;
  border-radius: 2px;
}
.task-item.is-current::before {
  background: var(--ink);
}
.task-item:hover {
  background: var(--paper-2);
}

.sidebar-footer-version {
  padding: 10px 18px 12px;
  font-size: 11px;
  color: var(--ink-3);
  border-top: 1px solid var(--line);
}
```

(具体删除边界以 grep 结果为准,务必逐块删而非一锅端)

- [ ] **Step 4: 新增视觉锁测试 `task-item-current-rail.test.ts`**

```ts
// frontend/src/components/desktop/styles/__tests__/task-item-current-rail.test.ts
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const SHELL_CSS = readFileSync(
  join(__dirname, '..', 'shell.css'),
  'utf-8'
);

describe('task-item 当前态 3px 竖条视觉锁', () => {
  it('::before 伪元素有 background + position + width 3px', () => {
    expect(SHELL_CSS).toMatch(/\.task-item::before\s*\{[^}]*position:\s*absolute/);
    expect(SHELL_CSS).toMatch(/\.task-item::before\s*\{[^}]*width:\s*3px/);
    expect(SHELL_CSS).toMatch(/\.task-item::before\s*\{[^}]*background:\s*transparent/);
  });

  it('is-current 状态 ::before 背景色为 --ink', () => {
    expect(SHELL_CSS).toMatch(/\.task-item\.is-current::before\s*\{[^}]*background:\s*var\(--ink\)/);
  });

  it('task-item 不能再用填充色做当前态(防回归)', () => {
    expect(SHELL_CSS).not.toMatch(/\.task-item\.is-current\s*\{[^}]*background-color/);
  });
});
```

- [ ] **Step 5: 跑视觉锁测试**

```bash
cd frontend && npx vitest run src/components/desktop/styles/__tests__/task-item-current-rail.test.ts
```

预期:3 个测试全 PASS。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/components/desktop/Sidebar.tsx \
        frontend/src/components/desktop/DesktopShell.tsx \
        frontend/src/components/desktop/styles/shell.css \
        frontend/src/components/desktop/styles/__tests__/task-item-current-rail.test.ts
git commit -m "feat(desktop): Sidebar 极简化 + 3px 竖条当前态

- 删 brand/new-task/search/section-title/footer-link 5 个区块
- task-item 当前态改 3px 竖条(::before 伪元素 + var(--ink))
- 底部仅 Nexus v1.3.0 一行灰字
- 新增 task-item-current-rail.test.ts 锁测试防回归

第十四轮 Claude Desktop 高保真重构步骤 2/6"
```

---

## Task 3: 主区删 chat-status-bar 顶部条

**Files:**
- Modify: `frontend/src/components/desktop/ChatView.tsx`(删 chat-status-bar + channel === 'wechat' 分支)
- Modify: `frontend/src/components/desktop/SetupView.tsx`(删同款 chat-status-bar + 改注释)
- Modify: `frontend/src/components/desktop/styles/shell.css`(删 .chat-status-bar 规则)
- Modify: `frontend/src/components/desktop/styles/chat.css`(若有 chat-status-bar 引用)

- [ ] **Step 1: 删除 ChatView.tsx 顶部状态条**

打开 `frontend/src/components/desktop/ChatView.tsx`,找到 `<header className="chat-status-bar">...</header>`(约 L40-90),整段删除。同时找到 L53 `currentConv?.channel === 'wechat' && <span>· 微信通道</span>` 条件渲染,删除。

如果 ChatView 整体只剩 `ChatArea + composer-wrap` 两个子元素,可考虑把 wrapper grid 简化(`.main` 已经 grid 布局)。

- [ ] **Step 2: 删除 SetupView.tsx 同款状态条 + 改注释**

打开 `frontend/src/components/desktop/SetupView.tsx`,L77 的 `<header className="chat-status-bar" data-tauri-drag-region>` 删。L71 注释里"36px chat-status-bar"改成"38px drag region 让位"。

- [ ] **Step 3: 删除 shell.css .chat-status-bar 规则**

```bash
cd frontend && grep -n "chat-status-bar" src/components/desktop/styles/shell.css
```

预期:命中若干行。打开文件,删除所有 `.chat-status-bar` / `.status-pill` / `.status-pill .dot` 规则。

- [ ] **Step 4: 跑测试**

```bash
cd frontend && npm run test:vitest -- --run 2>&1 | head -80
```

预期:可能有 e2e / 锁测试红(Sidebar.test.tsx 等),但 TSX 不崩。继续 Task 4-5。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/desktop/ChatView.tsx \
        frontend/src/components/desktop/SetupView.tsx \
        frontend/src/components/desktop/styles/shell.css \
        frontend/src/components/desktop/styles/chat.css
git commit -m "refactor(desktop): 删主区顶部 chat-status-bar 状态条

- ChatView.tsx 删 <header className='chat-status-bar'> + channel===wechat 条件
- SetupView.tsx 删同款 + 改 38px drag region 注释
- shell.css 删 .chat-status-bar / .status-pill 规则

第十四轮 Claude Desktop 高保真重构步骤 3/6"
```

---

## Task 4: EmptyState 删 prompt-grid + status-card

**Files:**
- Modify: `frontend/src/components/ChatArea/EmptyState.tsx`(整文件覆盖)
- Modify: `frontend/src/components/ChatArea/constants.ts`(删 QUICK_PROMPTS)
- Modify: `frontend/src/components/desktop/styles/chat.css`(删 .prompt-grid / .prompt-card / .status-card)

- [ ] **Step 1: 重写 EmptyState.tsx**

```tsx
// frontend/src/components/ChatArea/EmptyState.tsx
import { ComposerArea } from './ComposerArea';

export interface EmptyStateProps {
  onSubmit: (text: string) => void;
}

/**
 * 第十四轮:Claude Desktop 风格极简单版
 *   - 只一行 hero 欢迎文案 + 大输入框
 *   - 删 prompt-grid(2 列 6 卡)+ status-card(任务状态表)
 */
export function EmptyState({ onSubmit }: EmptyStateProps): JSX.Element {
  return (
    <div className="empty-state">
      <div className="empty-state-hero">
        <h1>今天想让我帮你做什么?</h1>
        <p>Nexus 会在后台理解任务、选择模型、整理上下文</p>
      </div>
      <div className="empty-state-composer">
        <ComposerArea onSubmit={onSubmit} />
      </div>
      <div className="empty-state-footer-note">
        内容由 AI 生成,请核实重要信息
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 删 constants.ts 的 QUICK_PROMPTS**

打开 `frontend/src/components/ChatArea/constants.ts`,如果只有 `QUICK_PROMPTS` 一项,删整个 export + import 用法。

- [ ] **Step 3: 删 chat.css 的 prompt-grid / prompt-card / status-card 规则**

```bash
cd frontend && grep -n "prompt-grid\|prompt-card\|status-card" src/components/desktop/styles/chat.css
```

打开文件,删除所有相关规则。

- [ ] **Step 4: 加新 CSS 规则支持极简单版**

在 chat.css 末尾追加:

```css
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  padding: 32px;
  gap: 32px;
}
.empty-state-hero {
  text-align: center;
}
.empty-state-hero h1 {
  font-size: 28px;
  font-weight: 600;
  color: var(--ink);
  margin: 0 0 8px;
}
.empty-state-hero p {
  font-size: 14px;
  color: var(--ink-3);
  margin: 0;
}
.empty-state-composer {
  width: min(720px, 100%);
}
.empty-state-footer-note {
  font-size: 11px;
  color: var(--ink-3);
  text-align: center;
}
```

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/ChatArea/EmptyState.tsx \
        frontend/src/components/ChatArea/constants.ts \
        frontend/src/components/desktop/styles/chat.css
git commit -m "refactor(desktop): EmptyState 极简化 — 删 prompt-grid + status-card

- 只留 hero 欢迎文案 + 大输入框 + AI 生成免责声明
- 删 QUICK_PROMPTS constants
- chat.css 删 prompt-grid/prompt-card/status-card 规则

第十四轮 Claude Desktop 高保真重构步骤 4/6"
```

---

## Task 5: 整轮删微信通道 UI + slice 字段清理

**Files:**
- Delete: `frontend/src/components/WechatPluginModal.tsx`
- Delete: `frontend/src/components/__tests__/WechatPluginModal.test.ts`
- Delete: `frontend/src/components/desktop/channels/ChannelViewBase.tsx`
- Delete: `frontend/src/components/desktop/channels/ChannelInbox.tsx`
- Delete: `frontend/src/components/desktop/channels/`(整个目录)
- Delete: `frontend/src/hooks/useChannelStatusPolling.ts`
- Delete: `frontend/e2e/wechat-channel.spec.ts`
- Delete: `frontend/e2e/journey/journey-wechat-bound-receive.spec.ts`
- Modify: `frontend/src/store/slices/channels.ts`(删 channelInbox / addChannelInbox / clearChannelInbox)
- Modify: `frontend/src/components/ChatArea/hooks/wsHandlers.ts`(删 handleChannelMessage)
- Modify: `frontend/src/components/desktop/styles/views.css`(删 L546-580 .wechat-copy-inline 块)

- [ ] **Step 1: 验证后端协议保留位置**

```bash
cd frontend && grep -rn "channel_message\|ChannelMessage" src/types/
```

预期:看到 `channel_message` 帧类型在 `types/index.ts` 中保留。本轮只删 UI,不动 types。

- [ ] **Step 2: 删 channels slice 的 channelInbox 字段**

打开 `frontend/src/store/slices/channels.ts`,删:
- `channelInbox: ChannelMessage[]` 字段 + initialState
- `addChannelInbox` action + reducer case
- `clearChannelInbox` action + reducer case
- `ChannelMessage` type import(如果 channels.ts 只为 channelInbox 用)
- **保留**:`pendingConfirmation: ConfirmationRequest | null` + `setPendingConfirmation` + `ConfirmationRequest` type

- [ ] **Step 3: 删 wsHandlers.handleChannelMessage**

打开 `frontend/src/components/ChatArea/hooks/wsHandlers.ts`,找到 `handleChannelMessage` 函数(约 L??),整段删除。保留 `handleToolConfirm`(HITL 用)。

- [ ] **Step 4: 删除 6 个微信 UI 文件**

```bash
git rm frontend/src/components/WechatPluginModal.tsx \
        frontend/src/components/__tests__/WechatPluginModal.test.ts \
        frontend/src/components/desktop/channels/ChannelViewBase.tsx \
        frontend/src/components/desktop/channels/ChannelInbox.tsx \
        frontend/src/hooks/useChannelStatusPolling.ts \
        frontend/e2e/wechat-channel.spec.ts \
        frontend/e2e/journey/journey-wechat-bound-receive.spec.ts
rmdir frontend/src/components/desktop/channels 2>/dev/null || true
```

- [ ] **Step 5: 删 views.css 的微信专属规则**

打开 `frontend/src/components/desktop/styles/views.css`,找到 L546-580 附近的 `.wechat-copy-inline` / `.wechat-mark` / `.wechat-benefits` / `.wechat-extra-actions` 规则,删除。

- [ ] **Step 6: grep 验证 UI 全清**

```bash
cd frontend && grep -rn "wechat\|Wechat\|WECHAT\|channel-tag-inline\|channel === 'wechat'" src/
```

预期:0 命中(`pendingConfirmation` 不应命中,因为是独立字段)。

- [ ] **Step 7: 跑测试看哪些红了**

```bash
cd frontend && npm run test:vitest -- --run 2>&1 | grep -E "FAIL|PASS|Test Files|Tests"
```

预期:大量 FAIL(锁测试 / Sidebar.test / Channel 相关),继续 Task 6 修。

- [ ] **Step 8: 提交**

```bash
git add -A
git commit -m "feat(desktop): 整轮删除微信通道 UI + slice 字段清理

- 删 WechatPluginModal + 测试
- 删 channels/ 目录(ChannelViewBase + ChannelInbox)
- 删 useChannelStatusPolling hook
- 删 wechat-channel e2e + journey
- channels slice 删 channelInbox/addChannelInbox/clearChannelInbox
- wsHandlers 删 handleChannelMessage(保留 handleToolConfirm HITL)
- views.css 删微信专属规则块

后端 channel_message 协议保留,pendingConfirmation HITL 不受影响

第十四轮 Claude Desktop 高保真重构步骤 5/6"
```

---

## Task 6: 锁测试 + e2e selector 全部更新

**Files:**
- Modify: `frontend/src/components/desktop/__tests__/Sidebar.test.tsx`
- Modify: `frontend/src/components/desktop/styles/__tests__/a11y-polish.test.ts`
- Modify: `frontend/src/components/desktop/styles/__tests__/shell-sidebar-brand.test.ts`
- Modify: `frontend/src/components/desktop/styles/__tests__/product-polish.test.ts`
- Modify: `frontend/src/styles/__tests__/tokens-dark.test.ts`(删 'wechat' 字面)
- Modify: `frontend/src/components/desktop/hooks/useGlobalShortcuts.test.ts`
- Modify: `frontend/e2e/settings.spec.ts`
- Modify: `frontend/e2e/journey/journey-redesign.spec.ts`
- Modify: `frontend/e2e/journey/journey-quick-prompts-and-history.spec.ts`
- Modify: `frontend/e2e/chat-happy-path.spec.ts`
- Modify: `frontend/e2e/helpers.ts`
- Modify: `frontend/src/components/desktop/styles/tokens.css`(删 --wechat)
- Modify: `frontend/src/components/desktop/styles/responsive.css`(删 mobile sidebar 3 列)

- [ ] **Step 1: 删 tokens.css --wechat 2 个灰阶 token**

打开 `frontend/src/components/desktop/styles/tokens.css`,L32 `--wechat: #4a4a4a;` 和 L104 `--wechat: #b5b5b5;` 两处删除(都在 :root 和 :root[data-theme=dark] 块内)。

- [ ] **Step 2: 删 responsive.css 的 mobile sidebar 3 列布局**

打开 `frontend/src/components/desktop/styles/responsive.css`,找到 `@media (max-width: 760px)` 块内的 `.sidebar` `grid-template-rows: auto; grid-template-columns: auto minmax(0, 1fr) auto; grid-template-areas: 'brand section footer';` 整段 + `.sidebar-brand { grid-area: brand; }` / `.sidebar-section { grid-area: section; }` / `.sidebar-footer { grid-area: footer; }` / `.sidebar .sidebar-section-title { display: none; }` 全部删除。

保留:`.prompt-grid { grid-template-columns: 1fr; }`(prompt-grid 类名就算没用了,CSS 留着无害) — 改成也删,因为 prompt-grid 已经不存在了。

- [ ] **Step 3: 改 Sidebar.test.tsx**

打开 `frontend/src/components/desktop/__tests__/Sidebar.test.tsx`:
- 删 `wechatConnected` / `wechatInboxCount` props 传入
- 加新断言:`expect(screen.queryByRole('button', { name: /新建对话/ })).toBeNull()`(确认无新对话按钮)
- 加新断言:`expect(screen.queryByText(/搜索会话/)).toBeNull()`(确认无搜索 input)
- 加新断言:`expect(screen.queryByText(/微信通道/)).toBeNull()`(确认无微信底栏)
- 加新断言:`expect(screen.getByText(/Nexus v1\.3\.0/)).toBeInTheDocument()`(版本号在)
- 加新断言:task-item 当前态有 `is-current` 类

- [ ] **Step 4: 改 a11y-polish.test.ts**

打开 `frontend/src/components/desktop/styles/__tests__/a11y-polish.test.ts`,所有 `.preferences-drawer-overlay` 引用 → `.preferences-modal-overlay`,所有 `.preferences-drawer` → `.preferences-modal`。

- [ ] **Step 5: 改 shell-sidebar-brand.test.ts**

打开 `frontend/src/components/desktop/styles/__tests__/shell-sidebar-brand.test.ts`,把测品牌块的断言改为测 sidebar 极简结构:
- 旧断言:`expect(SHELL_CSS).toContain('.sidebar-brand {')`
- 新断言:`expect(SHELL_CSS).not.toContain('.sidebar-brand {')`(确认删干净)
- 新断言:`expect(SHELL_CSS).toContain('.task-item.is-current::before')`

- [ ] **Step 6: 改 product-polish.test.ts**

打开 `frontend/src/components/desktop/styles/__tests__/product-polish.test.ts`,删所有 `--wechat` / `.wechat-copy-inline` / `.footer-link--wechat` 引用。

- [ ] **Step 7: 改 tokens-dark.test.ts**

打开 `frontend/src/styles/__tests__/tokens-dark.test.ts`:
- L139 删 `'wechat'` 字面字符串
- L48-54 删 `--wechat` 注释段落
- 如果有断言 `--wechat 的 HSL 饱和度` 等,整条删

- [ ] **Step 8: 改 useGlobalShortcuts.test.ts**

打开 `frontend/src/components/desktop/hooks/useGlobalShortcuts.test.ts`:
- L64 `onFocusSearch` 测试改为测 ⌘, 触发 PreferencesModal 的新契约
- 找 `.preferences-drawer-overlay` → `.preferences-modal-overlay`
- 找 `.wechat-plugin-modal-overlay` → 删除

- [ ] **Step 9: 改 settings.spec.ts**

打开 `frontend/e2e/settings.spec.ts`:
- 所有 `preferences-drawer-overlay` → `preferences-modal-overlay`
- 验证齿轮点击后出现居中模态框,而不是右滑抽屉

- [ ] **Step 10: 改 4 个 journey / e2e 的 selector**

```bash
cd frontend && grep -n "btn-new-task\|sidebar-search\|sidebar-brand\|sidebar-section-title\|prompt-card\|prompt-grid\|status-card\|chat-status-bar" e2e/
```

对每个命中行,按 spec §4.3 改名表一对一替换:
- `.btn-new-task` → 走 ⌘N 快捷键,不通过 button selector(用 `page.keyboard.press('Meta+n')`)
- `.sidebar-search input` → 移除(无搜索 input)
- `.prompt-card` → 移除(无建议卡)
- `.chat-status-bar` → 移除(无顶部状态条)

具体 4 个文件:
- `frontend/e2e/journey/journey-redesign.spec.ts`(L62/L36 / L77/L24 / L258/L31)
- `frontend/e2e/journey/journey-quick-prompts-and-history.spec.ts`(L47/71)
- `frontend/e2e/chat-happy-path.spec.ts`(L27)
- `frontend/e2e/helpers.ts`(L42 .prompt-card 锁定)

- [ ] **Step 11: 跑全栈测试**

```bash
cd frontend && npm run lint && npm run test:vitest -- --run 2>&1 | tail -30
```

预期:全绿(可能需要处理个别 selector 边界情况)。

- [ ] **Step 12: 跑 e2e**

```bash
cd frontend && npm run test:e2e 2>&1 | tail -40
```

预期:全绿。

- [ ] **Step 13: grep 验收清单**

```bash
cd /Users/yxb/projects/nexus

# 必为 0 命中
grep -rn "wechat\|Wechat\|WECHAT\|channel-tag-inline\|channel === 'wechat'" frontend/src/

# 必为 0 命中
grep -rn "btn-new-task\|sidebar-search\|sidebar-brand\|sidebar-section-title\|prompt-card\|prompt-grid\|status-card\|chat-status-bar" frontend/src/ frontend/e2e/

# 必为 0 命中
grep -rn "preferences-drawer\|PreferencesDrawer" frontend/src/

# 必为 0 命中
grep -rn "channelInbox\|addChannelInbox\|clearChannelInbox" frontend/src/

# 必为命中(协议保留)
grep -n "channel_message" frontend/src/types/index.ts

# 必为命中(HITL 保留)
grep -n "pendingConfirmation" frontend/src/store/slices/channels.ts

# 必为 0 命中
find frontend/src -name "WechatPluginModal*" -o -name "useChannelStatusPolling*" -o -name "PreferencesDrawer*" -o -name "preferences-drawer.css"

# 必不存在
find frontend/src/components/desktop/channels
```

每条 grep / find 命令预期输出与清单一致。

- [ ] **Step 14: 提交**

```bash
git add -A
git commit -m "test(desktop): 锁测试 + e2e selector 全更新 — 第十四轮

- tokens.css 删 --wechat 双 token
- responsive.css 删 mobile sidebar 3 列布局
- 4 个产品锁测试改新契约(modal/sidebar 极简)
- useGlobalShortcuts.test.ts 改 onFocusSearch + selector 改名
- 4 个 e2e(journey-redesign / quick-prompts / chat-happy-path / helpers)改 selector
- settings.spec.ts 改测居中模态

锁测试保留:
- task-item.is-current::before (新)
- preferences-modal-overlay (改自 preferences-drawer-overlay)

第十四轮 Claude Desktop 高保真重构步骤 6/6"
```

---

## Task 7: 全栈验证 + CHANGELOG + DMG 重打

**Files:**
- Modify: `CHANGELOG.md`(第十四轮 entry)

- [ ] **Step 1: tsc + build 验证**

```bash
cd /Users/yxb/projects/nexus
source .venv/bin/activate 2>/dev/null || true
cd frontend
npx tsc -b --noEmit
npm run build
```

预期:全绿,`frontend/dist/` 重新生成。

- [ ] **Step 2: 视觉验证 — Chrome headless 截图**

```bash
cd /Users/yxb/projects/nexus
# 启后端
source .venv/bin/activate
python -m nexus.backend.main &

# 等服务起来
sleep 5

# Chrome headless 截图
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless --no-sandbox --disable-gpu \
  --window-size=1100,720 \
  --screenshot=/tmp/nexus-r14-empty.png \
  --hide-scrollbars \
  http://localhost:30077
```

打开 `/tmp/nexus-r14-empty.png` 验证:
- sidebar 极简(无品牌块 / 无新对话按钮 / 无搜索 / 无 section 标题 / 无微信底栏)
- 主区只一行 hero + 大输入框
- task-item 当前态 3px 竖条(需先建一个会话)

- [ ] **Step 3: 写 CHANGELOG**

打开 `CHANGELOG.md`,在最近一条 entry 后追加:

```markdown
## 第十四轮 — 高保真 Claude Desktop 重构 (2026-07-17)

**重大变更**:
- 偏好设置:抽屉(PreferencesDrawer)→ 居中模态(PreferencesModal)
- 微信通道 UI 整轮删除(后端 channel_message 协议保留)

**UI 重构**:
- Sidebar 极简化:删除品牌块 / +新对话按钮 / 搜索 input / section 标题 / 微信底栏
- task-item 当前态:整行填充 → 左侧 3px 竖条
- 主区:删除顶部 chat-status-bar 状态条
- 空状态:删除 prompt-grid(2 列 6 卡)+ status-card,只留 hero + 大输入框
- 新增 sidebar 版本号 `Nexus v1.3.0` 一行灰字

**触发路径**:
- `⌘N` 新对话 / `⌘,` 偏好 / `⌘K` 搜索(后续) / `Esc` 关闭模态

**文件变化**:~30 个文件改动,+约 800 / -约 1200 行

**测试**:5 个产品锁测试改写 + 1 个新增视觉锁测试 + 4 个 e2e selector 更新

**DMG**:v1.3.0 重打,~70 MB
```

- [ ] **Step 4: 重打 DMG**

```bash
cd /Users/yxb/projects/nexus
bash scripts/build_dmg.sh
```

预期:产出 `release/Nexus-1.3.0-arm64.dmg`,~70 MB。

- [ ] **Step 5: 桌面端手测 6 条**

打开 `/Applications/Nexus.app`:
1. 点齿轮 → PreferencesModal 居中(不是右滑)、改深色立即生效、Esc 关闭 ✓
2. 空状态只有一行 hero + 大输入框,无 prompt grid,无状态条 ✓
3. task-item 当前态左 3px 竖条 ✓
4. sidebar 无品牌块 / 无新对话按钮 / 无搜索 input / 无 section 标题 / 无微信底栏 ✓
5. ⌘, 直接打开 PreferencesModal ✓
6. ⌘N 仍能新建对话(快捷键路径保留) ✓

- [ ] **Step 6: 提交 CHANGELOG + 进度文档**

```bash
git add CHANGELOG.md docs/superpowers/progress.md
git commit -m "docs(changelog): 第十四轮 高保真 Claude Desktop 重构

- 偏好抽屉 → 居中模态
- 微信通道 UI 整轮删除
- Sidebar 极简 + 3px 竖条当前态
- 主区无 topbar 状态条
- DMG v1.3.0 重打"
```

- [ ] **Step 7: 进度文档更新**

打开 `docs/superpowers/progress.md`,追加第十四轮完成记录(格式参考前面 13 轮)。

---

## Self-Review Checklist

- [x] Spec §1.1 偏离清单(10 项)对应 6 个 task 全覆盖
- [x] Spec §3.5 HITL 独立性在 Task 5 步骤 2-3 体现
- [x] Spec §3.6 类名改名表在 Task 1 步骤 6 + Task 6 多处体现
- [x] Spec §4.3 自检补漏列 12 项全部进入 Task 2-6 的修改清单
- [x] Spec §5.3 视觉验证在 Task 7 步骤 2 体现
- [x] Spec §7 验收清单在 Task 6 步骤 13 + Task 7 步骤 5 体现
- [x] 无 placeholder / 无 TBD / 无 TODO
- [x] 每个 task 都有具体代码 / 命令 / 预期输出
- [x] 每个 task 都以 commit 收尾(单一意图,Conventional Commits 中文主题 ≤ 50 字)
- [x] 跨 task 类型一致(SidebarProps、PreferencesModal props、channelInbox 字段删除路径一致)