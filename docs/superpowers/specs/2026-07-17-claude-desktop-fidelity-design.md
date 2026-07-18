# 高保真 Claude Desktop 重构 — 第十四轮

> 日期:2026-07-17
> 作者:Nexus
> 状态:design(待用户批准 → writing-plans → subagent-driven 执行)

## 1. 目标与动机

第十一轮(2026-07-16)起,Nexus 桌面端的设计参考一直宣称"Claude Desktop / Linear / Cursor 主流做法",但实际只在**偏好面板 → 抽屉模式**这一点上对齐了,其他 8 处偏离都没碰。用户对截图(侧栏塌陷 + 微信通道竖排)的二次反馈 `重构 前端 参考 Claude desktop 记住了吗` 把整轮重构推到台面。

本次重构目的:**逐项对齐 Claude Desktop 真实界面**(我自己),同时**彻底删除微信通道**这套产品决策(用户明确:"去掉微信通道(Claude Desktop 没有)")。

### 1.1 对照基线 — Claude Desktop 真实界面观察

从 `/Applications/Claude.app` 抓取的截图(2026-07-17 20:24)逐项观察:

| 区域 | Claude Desktop 真实做法 |
|---|---|
| sidebar 顶部 | **空白** —— traffic lights 后直接是会话列表(38px 让位 macOS chrome) |
| sidebar 入口 | **无 "+ 新对话"按钮**(Cmd+N 走快捷键)|
| sidebar 搜索 | **无 input**(右上 🔍 图标 + ⌘K)|
| sidebar 分组 | **无 section 标题** —— 会话列表扁平 |
| task-item 当前态 | **左侧 3px 竖条高亮**,内容区无填充色 |
| sidebar 底部 | 用户头像 + 铃铛通知 + ?帮助 —— **无"微信通道"状态行** |
| 主区 topbar | **无任何顶部条** —— 不显示"任务状态/模型名/运行中"那种状态 pill |
| 主区 prompt grid | **无** —— 空状态只显示一行欢迎文案 + 大输入框 |
| composer placeholder | `今天帮你做些什么?  @ 引用对话文件, / 调用技能与指令` |
| 主区右上 | 🔍 / 历史 / 时钟 / 窗口切换 4 个图标 |
| 设置 | **不是右滑抽屉** —— macOS 原生偏好窗口风格 |

### 1.2 当前 Nexus 偏离清单

| 偏离 | 当前 | Claude Desktop | 处理 |
|---|---|---|---|
| 1. sidebar 品牌块 | `N + Nexus + 个人 AI 助手` | 无 | **删除** |
| 2. sidebar 新对话按钮 | `+ 新对话` 42px 大按钮 | 无 | **删除**(Cmd+N 已就绪) |
| 3. sidebar 搜索框 | `搜索会话` input | 无 | **删除 input**(右上 🔍 + ⌘K) |
| 4. sidebar section 标题 | `对话 / 50` | 无 | **删除** |
| 5. sidebar 底部通道入口 | `微信通道 · 未绑定` | 无 | **删除**(整轮去 wechat) |
| 6. task-item 当前态 | 整行填充高亮 | 左侧 3px 竖条 | **改竖条** |
| 7. 主区 topbar 状态条 | `任务状态:助手/运行中/最近任务 50 条` | 无 | **删除** |
| 8. 主区 prompt grid | 2 列 6 个建议卡 | 无 | **删除**(只留欢迎文案 + 大输入框) |
| 9. PreferencesDrawer 抽屉 | 420px 右滑 | macOS 原生窗口 | **改模态框**(简化版,无 tab)|
| 10. 微信通道整套 | wechat-plugin-modal / channel-status-polling / channels/ 目录 | 不存在 | **整轮删除** |

### 1.3 范围(in scope)

- sidebar 重写:删 5 个区块(brand / new-task / search / section-title / footer-link),只保留 flat task-item 列表
- 主区重写:删 `chat-status-bar`(顶部状态条)、删 prompt-grid + prompt-card(空态建议卡)
- EmptyState 重写:只保留 hero + 大输入框(去掉 prompt-grid + status-card)
- PreferencesDrawer 改名 PreferencesModal,改居中模态(不右滑),去 tab,只保留核心 toggle
- 整轮删除微信通道:
  - `frontend/src/components/WechatPluginModal.tsx`(及其测试)
  - `frontend/src/components/desktop/channels/`(ChannelViewBase + ChannelInbox)
  - `frontend/src/hooks/useChannelStatusPolling.ts`
  - `frontend/e2e/wechat-channel.spec.ts`
  - `frontend/e2e/journey/journey-wechat-bound-receive.spec.ts`
  - `frontend/src/components/desktop/PreferencesDrawer.tsx`(改名为 PreferencesModal.tsx)
  - `frontend/src/components/desktop/styles/preferences-drawer.css`(合并进 preferences-modal.css)
- CSS 大瘦身:`shell.css` 删 .sidebar-brand / .btn-new-task / .sidebar-search / .sidebar-section-title / .sidebar-footer 规则;`chat.css` 删 .prompt-grid / .prompt-card / .status-card 规则;`views.css` 删 .setup-view 双栏(改单列简化)
- 锁测试改写:4 个文件全部按新结构更新断言(自检补:含 `tokens-dark.test.ts:139` 的 `'wechat'` 字面 + 新增 `task-item.is-current::before` 视觉锁测试)
- e2e 改写:`settings.spec.ts` 改测模态框;`wechat-channel.spec.ts` 删;`journey-wechat-bound-receive.spec.ts` 删;**自检补:`journey-redesign.spec.ts` / `journey-quick-prompts-and-history.spec.ts` / `chat-happy-path.spec.ts` / `helpers.ts` 4 个文件锁定被删 UI 类名,selector 全部更新**
- 注释清理:`SetupView.tsx:71` / `ChatView.tsx:67` / `DesktopShell.tsx:67/88/103` 的旧结构注释同步改
- CHANGELOG 收尾

### 1.4 范围外(out of scope)

- **后端 channel_message 协议保留** —— 前端只删 UI 引用,`types/index.ts` 的 `channel_message` 帧字段、`channels.ts` slice 保留(后端还在发,前端先不接)
- **状态色(error/success/warn/info)** —— 红黄绿蓝保留,跟第十二轮灰阶主题一致
- **macOS chrome drag region** —— `data-tauri-drag-region` 38px 让位逻辑保留(Tauri titleBarStyle=Overlay 必须)
- **DMG 重打** —— 完成所有改动后跑 `bash scripts/build_dmg.sh` 重打 v1.3.0

## 2. 视觉对照 — Claude Desktop vs Nexus 新版

### 2.1 sidebar

**Claude Desktop(目标):**
```
[ 38px 让位 ]
[ 空 12px ]
─────────────────
任务标题          2天前
任务标题          3天前
任务标题          4天前
任务标题          5天前
...
─────────────────
[flex-1 空白]
─────────────────
👤 夜小白    🔔    ❔
```

**Nexus 新版:**
```
[ 38px 让位 traffic lights ]
[ 空 14px ]
─────────────────
红烧肉的做法      7/16
请尽量在思考时...  7/16
请只回复"茶馆"...  7/16
你好              7/16
...
─────────────────
[ flex-1 空 ]
─────────────────
Nexus v1.3.0
```

**改动细节:**
- task-item 当前态:左边 3px `--ink` 竖条 + 内容区不填充
- task-item hover:背景 `--paper-2` 浅,无边框
- task-item 删除按钮 ✕ 平时隐藏,hover 时显示
- 底部 `Nexus v1.3.0`:12px 灰字,无 hover 态,占位而已(不造假用户系统)

### 2.2 主区

**Claude Desktop(目标):**
```
                                       🔍  📋  🕐  ⛶
[ flex-1 空 ]
              今天想让我帮你做什么?
        把任务交给 Nexus,其它事情交给背景进程
[ flex-1 空 ]
                       ┌───────────────────────┐
                       │ 今天帮你做些什么? @ │ [↑]
                       │ 默认权限 ✓    Auto │ 🎤 ⬆ │
                       └───────────────────────┘
                内容由 AI 生成,请核实重要信息
```

**Nexus 新版:去掉右上 4 个图标(我们没那么多 history/clock/window 概念),保留:**
```
[ 38px 让位 drag ]
[ 空 14px ]
[ flex-1 空 ]
           今天想让我帮你做什么?
     Nexus 会在后台理解任务、选择模型、整理上下文
[ flex-1 空 ]
              ┌──────────────────────────┐
              │ 把任务交给 Nexus…   ↑  │
              │ 默认权限 ✓  Auto  🎤  │
              └──────────────────────────┘
              内容由 AI 生成,请核实重要信息
```

**改动细节:**
- composer 居中(max-width: 720px),不是贴底
- composer 底栏:`+ 默认权限 | 模型选择器 | 麦克风 | 发送按钮`
- placeholder 改成 `把任务交给 Nexus…  (Enter 发送 · Shift+Enter 换行)`
- 删 `prompt-grid`(2 列 6 卡)、`status-card`(助手/连接/当前会话/最近任务 50 条)

### 2.3 设置入口

**Claude Desktop:** macOS 原生偏好窗口(NSWindow)

**Nexus 新版:** 居中模态框(简化),`⌘,` 触发:
```
┌──────────────────────────────┐
│  偏好                   ✕    │
├──────────────────────────────┤
│  当前模型    [MiniMax-M3]   │
│  ─────────────────────────   │
│  数据与隐私  本机保存        │
│  ─────────────────────────   │
│  显示思考过程  [已开启]      │
│  ─────────────────────────   │
│  深色模式    [已开启]        │
│  ─────────────────────────   │
│  高级设置    稍后开放        │
└──────────────────────────────┘
```

**关键约束:**
- 不放右滑抽屉(用户截图反馈"为什么抽屉盖住主区那么多"暗含不满)
- 居中模态(`max-width: 480px`,垂直水平居中)
- 蒙层 `rgba(0,0,0,0.55)` 半透明,点击蒙层关闭
- Esc 关闭(已走 `closeTopModal`)
- 触发:`⌘,`(useGlobalShortcuts 新增 onOpenPreferences 触发器)
- 删除 tab 切分:通用就是全部内容,微信通道整个删除

## 3. 关键决策

### 3.1 后端 channel_message 协议怎么办?

**决策:协议保留,前端 UI 全部删除。**

理由:微信通道后端服务(`/api/channels/wechat/bind` + `channel_message` WS 帧)是后端独立进程,与前端 UI 解耦。前端不接 UI 入口不代表后端不能用,只是**当前桌面端不暴露这个产品能力**。

具体保留:
- `frontend/src/types/index.ts`:`channel_message` 帧字段保留(后端还在发)
- `frontend/src/store/slices/channels.ts`:`channelInbox` slice 保留(其他 module 可能 import)
- `frontend/src/components/ChatArea/hooks/useWsMessageRouter.ts`:有 wechat 引用就保留(实际是后端帧处理)
- `frontend/src/components/ChatArea/hooks/wsHandlers.ts`:同上

具体删除:
- `frontend/src/hooks/useChannelStatusPolling.ts`
- `frontend/src/components/desktop/channels/ChannelViewBase.tsx`
- `frontend/src/components/desktop/channels/ChannelInbox.tsx`
- `frontend/src/components/WechatPluginModal.tsx`(及其测试)
- `frontend/src/components/desktop/PreferencesDrawer.tsx`(被 PreferencesModal 替换)
- 任何 sidebar / chat-status-bar 里 `channel === 'wechat'` 的 UI 分支
- `useGlobalShortcuts.ts` selector 里的 `.wechat-plugin-modal-overlay`

### 3.2 task-item 当前态改成 3px 竖条,实现细节

```css
.task-item {
  position: relative;
  padding: 8px 14px 8px 17px; /* 17px = 14px + 3px 竖条 */
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
```

### 3.3 PreferencesModal 实现细节

```tsx
<div
  className="modal-overlay preferences-modal-overlay"
  onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
>
  <div className="preferences-modal" role="dialog" aria-modal="true" aria-label="偏好">
    <header className="preferences-modal-header">
      <h2>偏好</h2>
      <button onClick={onClose} aria-label="关闭">✕</button>
    </header>
    <div className="preferences-modal-body">
      {/* 5 个 setting-row,跟原 GeneralPanel 一致 */}
    </div>
  </div>
</div>
```

```css
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
}
@keyframes preferences-modal-in {
  from { opacity: 0; transform: scale(0.96) translateY(8px); }
  to   { opacity: 1; transform: scale(1) translateY(0); }
}
```

### 3.4 sidebar 底部只放版本号,够不够空?

**决策:只放 `Nexus v1.3.0` 一行灰字,不造假用户系统。**

理由:Claude Desktop 底栏是用户头像 + 铃铛 + 帮助,这些是真实的产品能力。Nexus 没用户系统(用户只有一个账号 = yxb 自己),造假的"铃铛"和"帮助"按钮会显得空洞。一行版本号够用,既体现"产品在管自己",又不假装自己有用户系统。

如果未来真的需要帮助入口,走 macOS 菜单栏 Help 菜单(Tauri 2 menu API),不在桌面端 UI 造假。

### 3.5 HITL pendingConfirmation 与 channelInbox 独立性确认

**决策:HITL 卡片完全独立于 channel_message,本轮只删 channelInbox UI 部分。**

自检验证:
- `frontend/src/store/slices/channels.ts` 中 `pendingConfirmation: ConfirmationRequest | null` 和 `channelInbox: ChannelMessage[]` 是 **store 两个独立字段**
- `frontend/src/test/setup.ts:31` 默认 `pendingConfirmation: null`,不依赖 channelInbox
- `frontend/src/components/ChatArea/hooks/wsHandlers.ts` 的 `handleChannelMessage` 走 channelInbox 路径,HITL 走 `handleToolConfirm` 完全不同的代码路径
- `frontend/src/components/ChatArea/HITL/ConfirmationPanel.tsx`(HITL UI)不 import channels slice 的 channelInbox

具体执行:
- 保留:`channels.ts` slice 的 `pendingConfirmation` reducer + getter
- 保留:`HITL/` 目录 + `ConfirmationPanel.tsx` + `wsHandlers.handleToolConfirm`
- 删:`channels.ts` slice 的 `channelInbox` / `addChannelInbox` / `clearChannelInbox` 字段 + reducer
- 删:`channels.ts` slice 的 `setPendingConfirmation` 不删(还要用)
- 删:`wsHandlers.handleChannelMessage` 整个函数(没 UI 收件箱了,handler 无意义)
- 删:Sidebar 底栏 footer-link 整块(永远显示"未绑定",没意义)

### 3.6 `preferences-drawer-overlay` → `preferences-modal-overlay` 类名改名清单

**决策:PreferencesModal 居中模态,共享 `modal-overlay` 基础蒙层样式,但新类名 `.preferences-modal-overlay` 区分。**

复合类名替换表:
| 旧(PreferencesDrawer) | 新(PreferencesModal) |
|---|---|
| `modal-overlay preferences-drawer-overlay` | `modal-overlay preferences-modal-overlay` |
| `.preferences-drawer`(容器) | `.preferences-modal`(容器) |
| `.preferences-drawer-header` | `.preferences-modal-header` |
| `.preferences-drawer-tabs` | **删除**(无 tab)|
| `.preferences-drawer-body` | `.preferences-modal-body` |

CSS 文件:`preferences-drawer.css` → `preferences-modal.css`(改名 + 改类名),通过 `tokens.css` 的 `@import` 或 `index.css` 全局引入。

`useGlobalShortcuts.ts` 的 `closeTopModal` 优先级链:
- 旧:`.wechat-plugin-modal-overlay, .preferences-drawer-overlay, .model-config-modal-overlay, .context-menu`
- 新:`.preferences-modal-overlay, .model-config-modal-overlay, .context-menu`(删 wechat-plugin,改 draw → modal)

## 4. 改动文件清单

### 4.1 删除

| 路径 | 理由 |
|---|---|
| `frontend/src/components/WechatPluginModal.tsx` | 微信通道 UI 入口 |
| `frontend/src/components/__tests__/WechatPluginModal.test.ts` | 同步 |
| `frontend/src/components/desktop/channels/ChannelViewBase.tsx` | 微信通道面板(被 PreferencesDrawer 用) |
| `frontend/src/components/desktop/channels/ChannelInbox.tsx` | 微信通道收件箱 |
| `frontend/src/components/desktop/channels/` 目录 | 整个目录空,移除 |
| `frontend/src/hooks/useChannelStatusPolling.ts` | 微信状态轮询 |
| `frontend/src/components/desktop/PreferencesDrawer.tsx` | 被 PreferencesModal 替换 |
| `frontend/src/components/desktop/styles/preferences-drawer.css` | 被 preferences-modal.css 替换 |
| `frontend/e2e/wechat-channel.spec.ts` | 微信通道 e2e |
| `frontend/e2e/journey/journey-wechat-bound-receive.spec.ts` | 微信通道 journey e2e |

### 4.2 新增

| 路径 | 内容 |
|---|---|
| `frontend/src/components/desktop/PreferencesModal.tsx` | 居中模态偏好(单页,无 tab) |
| `frontend/src/components/desktop/styles/preferences-modal.css` | 模态样式 |

### 4.3 修改

| 路径 | 改动 |
|---|---|
| `frontend/src/components/desktop/Sidebar.tsx` | 删 brand / new-task / search / section-title / footer-link,改 3px 竖条当前态 |
| `frontend/src/components/desktop/DesktopShell.tsx` | 删 wechatConnected / onOpenPreferences 改为单参数 → ⌘, 触发器;清理 L67/88/103 的旧结构注释 |
| `frontend/src/components/desktop/ShellLayout.tsx` | 同步删 onOpenPreferences 参数 |
| `frontend/src/components/desktop/ChatView.tsx` | 删 `<header className="chat-status-bar">`(顶部状态条);删 L53 `currentConv?.channel === 'wechat' && <span>· 微信通道</span>` 条件分支 |
| `frontend/src/components/desktop/SetupView.tsx` | **自检补:删 L77 同款 `<header className="chat-status-bar">`;改 L71 注释"36px chat-status-bar → drag region 让位"** |
| `frontend/src/components/ChatArea/EmptyState.tsx` | 删 prompt-grid / status-card,只留 hero + 大输入框 |
| `frontend/src/components/ChatArea/constants.ts` | 删除 QUICK_PROMPTS(被 EmptyState 引用) |
| `frontend/src/components/desktop/hooks/useGlobalShortcuts.ts` | 删 `.wechat-plugin-modal-overlay` selector,**改 `.preferences-drawer-overlay` → `.preferences-modal-overlay`** |
| `frontend/src/components/desktop/hooks/useGlobalShortcuts.test.ts` | **自检补:改 L64 `onFocusSearch` 测试(绑到删掉的 sidebar-search input,改为测新 selector)** |
| `frontend/src/components/desktop/__tests__/Sidebar.test.tsx` | 删 wechatConnected 引用,改新结构 |
| `frontend/src/components/desktop/styles/__tests__/a11y-polish.test.ts` | 改新 modal 契约 |
| `frontend/src/components/desktop/styles/__tests__/shell-sidebar-brand.test.ts` | 删品牌相关,改测 sidebar 结构 |
| `frontend/src/components/desktop/styles/__tests__/product-polish.test.ts` | 删 wechat 相关,改新结构 |
| `frontend/src/styles/__tests__/tokens-dark.test.ts` | **自检补:删 L139 `'wechat'` 字面锁 + L48-54 旧色值注释(对应 tokens.css 删 --wechat)** |
| `frontend/src/components/desktop/styles/shell.css` | 删 .sidebar-brand / .btn-new-task / .sidebar-search / .sidebar-section-title / .sidebar-footer / .chat-status-bar / .prompt-grid / .prompt-card / .status-card |
| `frontend/src/components/desktop/styles/chat.css` | 同上补充删除 |
| `frontend/src/components/desktop/styles/views.css` | 删 .setup-view 双栏,改单列简化;**自检补:删 L546-580 `.wechat-copy-inline` 等微信专属规则块** |
| `frontend/src/components/desktop/styles/responsive.css` | 删 mobile sidebar 3 列布局(现在 sidebar 极简,不需要 mobile 特化)|
| `frontend/src/components/desktop/styles/tokens.css` | **自检补:删 `--wechat: #4a4a4a` (L32) 和 `--wechat: #b5b5b5` (L104) 两个灰阶 token,UI 全清后无引用** |
| `frontend/src/main.tsx` | preferences-drawer.css → preferences-modal.css |
| `frontend/e2e/settings.spec.ts` | 改测模态框(`preferences-modal-overlay`)|
| `frontend/e2e/journey/journey-redesign.spec.ts` | **自检补:改 L62/L36 `.chat-status-bar`、L77/L24 `.prompt-card`、L258/L31 `.sidebar-search input` 等老 selector → 新契约** |
| `frontend/e2e/journey/journey-quick-prompts-and-history.spec.ts` | **自检补:改 L47/71 `.prompt-card` + `.btn-new-task` selector** |
| `frontend/e2e/chat-happy-path.spec.ts` | **自检补:改 L27 `button.btn-new-task` selector** |
| `frontend/e2e/helpers.ts` | **自检补:改 L42 `.prompt-card` 锁定 selector** |
| `frontend/src/components/desktop/styles/__tests__/task-item-current-rail.test.ts` | **自检补:新增 — 锁测试断言 `.task-item.is-current::before { background: var(--ink); width: 3px; position: absolute; left: 0; }`,防回归** |
| `CHANGELOG.md` | 第十四轮 entry |

### 4.4 CSS 命名规则更新

sidebar CSS 类只保留:
- `.sidebar`(容器)
- `.sidebar-task-list`(扁平列表)
- `.task-item`(单个会话)
- `.task-item.is-current`(当前态,左 3px 竖条)
- `.sidebar-footer-version`(底栏版本号)

chat-status-bar 整个删掉,ComposerArea 改成 `composer-wrap`(已存在,不动),底部模型/权限选择器进入 composer 内联(`+ 默认权限` 是个 inline button,跟 composer 同行)。

## 5. 测试

### 5.1 vitest 单元测试

- `Sidebar.test.tsx`:删 wechatConnected / footer-link,加新结构断言
  - 测试 sidebar 只渲染 task-item 列表(无 brand / new-task / search / section-title)
  - 测试当前态是 `is-current` 类,不是填充
- `PreferencesModal.test.tsx` 新增:测试 ⌘, 触发、Esc 关闭、点击蒙层关闭
- `EmptyState.test.tsx`:删 prompt-grid / status-card 断言
- 4 个产品锁测试全部按新结构更新

### 5.2 e2e 测试

- `settings.spec.ts`:改测 PreferencesModal 居中模态框(`.preferences-modal-overlay`)
- `journey/*.spec.ts`:删微信 journey
- 新增 `journey/preferences-modal.spec.ts`:验证齿轮 → 模态框 → ⌘, 三触发路径

### 5.3 视觉验证

- 全栈 lint + tsc + vitest + vite build 全绿
- DMG v1.3.0 重打
- Chrome headless 900x700 截图验证:
  - sidebar 极简(无品牌块 / 无新对话 / 无搜索 / 无 section 标题)
  - task-item 当前态 3px 竖条
  - 主区无 topbar 状态条
  - 空状态只有 hero + 大输入框
  - 齿轮 → PreferencesModal 居中(不是右滑)

## 6. 风险与回退

### 6.1 风险

- **wechat 后端协议切了会怎样?** —— 不切,后端 `channel_message` 帧照发,前端 `useWsMessageRouter` 照常路由(只是不显示)。万一后端 ws 帧处理路径依赖 `channelInbox` slice 写入,删除 UI 不影响(`wsHandlers.handleChannelMessage` 整函数删掉,slice 字段也清空,store action chain 自洽)。
- **PreferencesModal 在小窗口(< 480px)展示?** —— 模态框 `width: min(480px, 92vw)`,自动适配
- **空状态没 prompt grid,用户第一次进来会不会迷路?** —— 大输入框 + `今天想让我帮你做什么?` 提示足够。Claude Desktop 也只放一行文案
- **sidebar 太空,底部版本号会不会显得突兀?** —— 12px 灰字,low contrast,不抢眼。Claude Desktop 底栏也是低调元素
- **3px 竖条视觉锁会不会被人改回填充?** —— 新增 `task-item-current-rail.test.ts` 锁测试断言 `::before` 伪元素的 `background: var(--ink)` + `width: 3px` + `position: absolute`,未来 PR 改回填充立即红测
- **HITL 卡片会被误删吗?** —— 3.5 决策段已验证 pendingConfirmation 完全独立于 channelInbox,本轮只删 channelInbox 部分,HITL `HITL/` 目录 + `handleToolConfirm` + `ConfirmationPanel.tsx` 全部保留
- **CSS 复合类名 `.modal-overlay.preferences-drawer-overlay` 改名会漏吗?** —— 3.6 改名清单明确 4 个类名一对一替换;4 个 e2e + 1 个 useGlobalShortcuts 测试同步更新 selector
- **`tokens.css --wechat` 删了会破坏别的引用吗?** —— 灰阶 token 仅被 `product-polish.test.ts` / `tokens-dark.test.ts:139` 用作锁测试 key,删 token 同步删这两个测试断言,无生产代码引用

### 6.2 回退

- 这一轮所有 commit 单独 revert 即可回退
- 不动后端协议,微信通道如果产品决策再启,只重新引入 UI 即可

## 7. 验收清单(交付前必过)

**全栈构建**
- [ ] `npm run lint && npm run test:vitest && npx tsc -b --noEmit` 全绿
- [ ] `bash scripts/build_dmg.sh` 成功,产出 `release/Nexus-1.3.0-arm64.dmg`

**UI 残留扫描(grep 必须 0 命中)**
- [ ] `grep -rn "wechat\|Wechat\|WECHAT\|channel-tag-inline\|channel === 'wechat'" frontend/src/` 0 命中(全前端清干净)
- [ ] `grep -rn "btn-new-task\|sidebar-search\|sidebar-brand\|sidebar-section-title\|prompt-card\|prompt-grid\|status-card\|chat-status-bar" frontend/src/ frontend/e2e/` 0 命中(老 UI 类名清干净,UI 全清)
- [ ] `grep -rn "preferences-drawer\|PreferencesDrawer" frontend/src/` 0 命中(改名为 PreferencesModal)
- [ ] `grep -n "channel_message" frontend/src/types/index.ts` 有命中(确认后端协议保留)
- [ ] `grep -rn "pendingConfirmation" frontend/src/store/slices/channels.ts` 有命中(确认 HITL 字段保留)
- [ ] `grep -rn "channelInbox\|addChannelInbox\|clearChannelInbox" frontend/src/` 0 命中(确认 channelInbox 完全删除)

**文件存在性扫描(find 必须 0 命中)**
- [ ] `find frontend/src/components/desktop/channels` 目录不存在
- [ ] `find frontend/src -name "WechatPluginModal*" -o -name "useChannelStatusPolling*" -o -name "PreferencesDrawer*" -o -name "preferences-drawer.css"` 0 命中

**视觉锁测试**
- [ ] 新增 `frontend/src/components/desktop/styles/__tests__/task-item-current-rail.test.ts` 通过(断言 `.task-item.is-current::before` 的 background/width/position)
- [ ] 4 个产品锁测试(a11y-polish / shell-sidebar-brand / product-polish / tokens-dark)全部通过

**桌面端手测**
- [ ] 点齿轮 → PreferencesModal 居中(不是右滑)、改深色立即生效、Esc 关闭
- [ ] 空状态只有一行 hero + 大输入框,无 prompt grid,无状态条
- [ ] task-item 当前态左 3px 竖条
- [ ] sidebar 无品牌块 / 无新对话按钮 / 无搜索 input / 无 section 标题 / 无微信底栏
- [ ] ⌘, 直接打开 PreferencesModal
- [ ] ⌘N 仍能新建对话(快捷键路径保留)

**CHANGELOG**
- [ ] 写第十四轮 entry