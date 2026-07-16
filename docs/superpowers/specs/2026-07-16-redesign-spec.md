# 第九轮 UI 重设计 — "完美产品" SPEC

> **For agentic workers:** 设计增量章节,描述第九轮要做哪些 UI/UX 改动。
> 不推翻第八轮的 Claude Desktop 单层外壳契约,**在它上面升级**。

**背景**:用户 2026-07-16 跑 `/goal 重新设计前端界面 然后做E2E模拟真人测试
要求符合主流agent操作习惯 界面简约 给我完美的产品`。

**目标**:把 Nexus 桌面端从"功能可达"升级到"用户爱用"。对照基线 = Claude
Desktop / ChatGPT / Cursor / Manus。SPEC 只列增量(第八轮已完成的不动)。

---

## 1. 设计原则(锁)

1. **左窄右宽,单主区** — sidebar 270px 固定,主区吃掉剩下的窗口宽度(≥600px)
2. **首屏 hero + 大输入框** — 首次启动没历史会话 = 居中 logo + 标题 + 大输入框 + 建议 prompt 卡片,**不**直接渲染空 chat list
3. **底部固定 composer** — composer 钉底,主区只滚消息流;发送 = Enter,Shift+Enter 换行
4. **思考块可折叠** — `<thinking>` 默认折叠成 1 行"已思考 N 字",点开看细节
5. **工具调用透明卡** — `tool_call`/`tool_result` **不再 noop**;显示卡片(icon + name + 折叠 details),运行中/成功/失败状态可视化
6. **会话可搜索 / 可重命名** — sidebar 顶部加搜索框,会话项 hover 出现重命名 / 删除菜单
7. **模型切换在顶栏** — 顶栏中央 / 右侧 dropdown,不藏设置页
8. **浅深色一键切换** — 顶栏右侧太阳/月亮 icon,**不**塞设置页
9. **停止按钮 = 真停止** — 已记录为已知问题;第九轮**不**重做软停止,但加 `服务端 cancel_frame` 提示(后端协议增量,后续 PR)
10. **截图 = 证据** — 每改一处都跑 Playwright 截图,放 `/tmp/redesign-*.png`,人眼看

---

## 2. 视觉系统

### 2.1 间距 / 字号 token(补齐)

`tokens.css` **缺间距和字号 token**(基线确认)。第九轮补:
```css
--space-1: 4px;
--space-2: 8px;
--space-3: 12px;
--space-4: 16px;
--space-5: 24px;
--space-6: 32px;
--space-7: 48px;
--font-xs: 12px;
--font-sm: 13px;
--font-base: 14px;
--font-md: 16px;
--font-lg: 20px;
--font-xl: 28px;
--font-2xl: 36px;
```
不替换现有 px,只**新增** token + 在 `shell.css` 关键处替换硬编码(渐进)。

### 2.2 配色不变

第八轮已定 light+dark 两套,**第九轮不动色**,只补间距/字号 token。

---

## 3. 改动清单(分模块)

### 3.1 Sidebar 增强 — `[src/components/desktop/Sidebar.tsx]`

**改动**:
- 顶部 brand 区(已存在 logo + 名字 + 齿轮)— 齿轮保留
- brand 区**下方**:加 `<input type="search" placeholder="搜索会话" />`
- 会话列表渲染:`title` 截 24 字,hover 显示 `...` 菜单(`重命名 / 删除 / 复制`)
- 列表项点击 = 切换激活会话(已存在)
- 列表底部 + 列表之间留 `--space-3`
- **不**改宽度(270px 已有),不改布局

**测试**: `Sidebar.test.tsx` 新增
- search 框过滤逻辑
- menu 点击触发重命名 / 删除 callback
- 长 title 截断

### 3.2 ChatArea 空状态升级 — `[src/components/ChatArea/EmptyState.tsx]`

**现状**:hero + prompt 卡片 + 状态卡(已经在)
**改动**:
- hero 字号放大:`h1` 从 `--font-xl` → `--font-2xl`
- 4 个 prompt 卡片改成 2×2 grid(现是 1 行 4 列,小屏挤),`--space-4` 间距
- 状态卡**保留**,但放 hero 下方右侧;移动到 sidebar 折叠区(用户可选)
- 大输入框(单独组件)放在 hero 下方,占 `--space-7` 宽,**直接回车发送**
  - 输入框有 placeholder "把任务交给 Nexus..."
  - 输入框右端有 `↑` 发送按钮(圆形,绿)
  - 选中 prompt 卡片 → 文本进输入框,自动 focus
- 输入框内可显示一个 `<model-name>` chip(当前激活模型),点击 → 切模型 dropdown

**测试**: `EmptyState.test.tsx` 新增
- 渲染 4 个 prompt 卡片
- 点 prompt → 调 onInsertPrompt
- 大输入框回车 → 调 onSubmit

### 3.3 Composer 改造 — `[src/components/ChatArea/Composer.tsx]`

**改动**:
- 改 Enter 行为:`onKeyDown` 已有 Enter 调 onSubmit,加 Shift+Enter 不提交只换行
- 发送按钮移到输入框**右下角**(圆形),不占整行
- 流期间发送按钮变红色 `停止`(已存在)
- 左下角放 `+` 按钮(占位):附件 / 截图 / 选 skill,**第九轮只放 icon,点击暂无行为**
- 输入框高度自适应:1-6 行,超出滚动

**测试**: `Composer.test.tsx` 新增
- Shift+Enter 不提交
- Enter 提交
- `+` 按钮存在
- 流期间显示 stop button

### 3.4 思考块折叠 — `[src/components/ChatArea/ChatBubble.tsx]` / `useWsMessageRouter.ts`

**改动**:
- `thinking` 帧累积进 assistant message 的 `thinking` 字段(store 已有)
- ChatBubble 渲染:`thinking` 默认折叠成 1 行 "已思考 N 字 · 点开看"
- 点开 → 展开完整文本,字号 `--font-xs`,颜色 `--ink-muted`
- 折叠/展开状态由用户偏好(localStorage `nexus_thinking_expanded`)控,默认 false

**测试**: `ChatBubble.test.tsx` 新增
- 默认不渲染完整 thinking
- 点 toggle → 渲染完整
- 切会话 → 折叠状态保留

### 3.5 工具调用透明卡 — `[src/components/ChatArea/ToolCallCard.tsx]` (新) + `useWsMessageRouter.ts`

**新增组件** `ToolCallCard.tsx`:
```tsx
<div className="tool-call-card">
  <div className="tool-call-header">
    <span className="tool-call-icon">🔧</span>
    <span className="tool-call-name">{name}</span>
    <span className="tool-call-state">{state}</span>  // running | success | error
    <button className="tool-call-toggle">▾</button>
  </div>
  {expanded && (
    <div className="tool-call-details">
      <div className="tool-call-args"><code>{JSON.stringify(args)}</code></div>
      {result && <div className="tool-call-result"><pre>{result}</pre></div>}
    </div>
  )}
</div>
```

**改动 `wsHandlers.ts`**:把 `tool_call` / `tool_result` 从 noop 改成:
- `tool_call` → append 到当前 assistant message 的 `toolCalls` 数组
- `tool_result` → 更新对应 `toolCall.result` + state
- 默认折叠

**测试**:
- `ToolCallCard.test.tsx` 新增(渲染 / 折叠 / 状态颜色)
- `wsHandlers.test.tsx` 加 tool_call 帧 → store 更新

### 3.6 模型切换在顶栏 — `[src/components/desktop/ChatView.tsx]` / 新 `<ModelSwitcher>`

**新增** `<ModelSwitcher>`(顶栏右侧):
- 紧凑 chip:模型名 + `▾`
- 点开 dropdown:列表(从 `/api/models` 拿),点切
- 已选 = 加粗 + 绿点
- 切完 → 调 `modelsConfig.setActive()`(现有 store)

**测试**: `ModelSwitcher.test.tsx` 新增

### 3.7 浅深色切换 — `[src/components/desktop/ChatView.tsx]` / 新 `<ThemeToggle>`

**新增** `<ThemeToggle>`(顶栏右侧,ModelSwitcher 旁):
- 太阳 ☀️ / 月亮 🌙 icon
- 点击 toggle `data-theme` attribute
- 状态持久化到 localStorage
- 不调设置页

**测试**: `ThemeToggle.test.tsx` 新增

### 3.8 顶栏排版调整 — `[src/components/desktop/ChatView.tsx]`

**现状**:36px chat-status-bar 已有,左 title 右连接 pill
**改动**:
- 左:title(已存在)
- 右:连接 pill + `<ModelSwitcher>` + `<ThemeToggle>` + 返回按钮(若有 onBack)
- 间距 `--space-3`,垂直居中

---

## 4. E2E 模拟真人测试(独立 Playwright suite)

### 4.1 新增 spec `[frontend/e2e/journey-redesign.spec.ts]`

> 模拟真人测试 = 跑完整用户旅程,**不** mock 后端,启 vite dev + 后端
> 真实后端有:`NEXUS_WS_TOKEN=nexus-default-token uvicorn nexus.backend.main:app --port 30000`
> 真实前端:vite dev (30077)

**8 个 journey**:

1. `journey-empty-state-hero` — 删全部会话 → 看到 hero + 4 prompt + 大输入框,截图
2. `journey-new-conversation-flow` — 输入框打 "你好" → Enter → 等响应,截图
3. `journey-multi-turn-context` — 同一会话多轮,后轮带前轮上下文
4. `journey-tool-call-visible` — 触发工具调用(让 LLM 调 shell_run),看到 ToolCallCard
5. `journey-thinking-collapsed` — agent 思考时折叠,展开后看到内容
6. `journey-sidebar-search` — 多会话 → 搜索 → 过滤命中
7. `journey-model-switch` — 顶栏切换模型 dropdown
8. `journey-theme-toggle` — 切深色,截图对比浅色
9. `journey-wechat-bind-modal` — 点扫码绑定 → modal → 看到 QR(已有契约)
10. `journey-stop-during-stream` — 流期间点 stop,看到停止 marker

### 4.2 截图存档

每跑完一个 journey 截一张 `/tmp/redesign-jN-<name>.png`,用于人工目视。

---

## 5. 不做

- **不**重做软停止(后端无 cancel 帧,需要后端协议增量,后续 PR)
- **不**改 splash / 启动流程 / 安装流程
- **不**改 token / 模型配置弹窗(SetupView / ModelConfigModal)
- **不**改 HITL ConfirmationCard 文案(已 OK)
- **不**改 backend / 后端协议
- **不**改主题色

---

## 6. 完成度估算

- 代码量:~750 行(新 350 + 改 400)
- 新文件:`ToolCallCard.tsx` / `ModelSwitcher.tsx` / `ThemeToggle.tsx` / 4 个 test.tsx + 1 e2e spec
- 关键风险:
  1. `tool_call` 帧从 noop 改有 UI,**必须**配合 store 加字段 — 加 `toolCalls` array 到 Message type
  2. 思考块折叠状态在切会话 / 切主题时不能丢 — localStorage key 锁
  3. ModelSwitcher 拉 `/api/models` 失败时降级到当前模型,不能 crash
  4. ThemeToggle 切深色时不能把 splash 重置

---

## 7. 验收

- [ ] `npm run lint` 0 error
- [ ] `npm run test` 全过(新增 ≈ 25 个单测)
- [ ] `npm run test:e2e` 全过(10 个新 journey + 9 旧)
- [ ] DMG 重打 + 装 /Applications/Nexus.app + 截 10 张图
- [ ] CHANGELOG 增条目
- [ ] atomic commits