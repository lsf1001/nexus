# Nexus 三栏重构设计 SPEC

> **目标**：把 Nexus 前端从两栏（Sidebar + ChatArea）改为三栏（Sidebar + Chat + Artifacts），借鉴 Claude Desktop 的产物可渲染交互模式，但保留 Nexus 现有的 token / 主题 / 测试契约。
>
> **基线文档**：[docs/designs/frontend.md](../../../designs/frontend.md) — 唯一权威前端设计文档，本 SPEC 是它的"重构增量"。
>
> **设计稿**：`/tmp/nexus-mock/design.html` — 7 状态视觉稿。
>
> **状态**：草案 0.1（2026-07-20）。

---

## 1. 背景与动机

### 1.1 现状

Nexus 当前前端是两栏布局（`grid-template-columns: 264px minmax(0, 1fr)`）：

- **Sidebar**：会话列表 + 搜索 + 设置入口
- **ChatArea**：主对话流（空态 / MessageList / Composer）

工具调用结果（`ToolCallCard`）以折叠 JSON 形式呈现，长代码 / Markdown / SVG / 可交互 HTML 在消息流里被压扁，可读性差，也无法交互。

### 1.2 目标

参考 Claude Desktop 的产物可渲染交互模式，新增**右侧 Artifacts 面板**，把 ToolCallCard 的产物（文件类：代码 / Markdown / SVG / HTML）从消息流里"拎出来"在右侧高保真渲染，可折叠、不打断对话流。

### 1.3 非目标（YAGNI）

- **不**做 chat 多分支 / git-style 工作树（Nexus 单线对话流足够）
- **不**做实时协同 / share link（个人助理，单用户）
- **不**做 Artifacts 持久化到文件系统（仅当前会话内可用，会话结束可清空；如需持久化在后续 SPEC 单独评估）
- **不**改 WS 协议（ToolCallCard 的产物已通过 `tool_result` 帧携带正文，前端解析即可，后端无感）
- **不**改后端中间件链 / 模型调用 / 工具注册（仅前端消费既有帧）

---

## 2. 架构

### 2.1 总体形态

```
┌─────────────────────────────────────────────────────────────────┐
│ ◉ ◉ ◉                                              ⌘K  ☀  ⋯   │ 22px drag
├──────────┬──────────────────┬───────────────────────────────────┤
│ Sidebar  │     Chat         │           Artifacts               │
│  260px   │      760         │      420 (minmax 0, 1fr)          │
│          │                  │                                   │
│  现有    │  现有 EmptyState  │  新增:                            │
│  不动    │  现有 MessageList│   - tab 切换 Code/Md/SVG/HTML      │
│          │  现有 Composer   │   - 头部 文件名 + 操作             │
│          │                  │   - 主体 渲染器                    │
│          │                  │   - 底部 meta (token / 来源 tool)  │
│          │                  │                                   │
│          │                  │  默认折叠(Cmd+\ 切换)              │
│          │                  │  折叠态下 Chat 区回退到 1fr         │
├──────────┴──────────────────┴───────────────────────────────────┤
│ ● online                                          local         │ 14px
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 三态尺寸

| 状态 | Sidebar | Chat | Artifacts | 触发 |
|------|---------|------|-----------|------|
| 折叠（默认） | 260 | minmax(0, 1fr) | 0 | 初始 / 用户主动 Cmd+\ |
| 展开 | 260 | minmax(0, 760px) | minmax(0, 1fr) | 联动触发 / 用户主动 Cmd+\ |
| 移动端 (≤768px) | 0 | 1fr | 0 | 响应式隐藏 Sidebar/Artifacts |

折叠阈值：Artifacts ≥ 420px 才显示，否则视为折叠（避免 0 闪烁）。

### 2.3 CSS Grid

```css
.nexus-desktop {
  display: grid;
  grid-template-columns:
    260px                                  /* Sidebar   - 固定 */
    minmax(0, 760px)                       /* Chat      - 优先 */
    minmax(0, 1fr);                        /* Artifacts - 弹性 */
  /* 共 3 列；Artifacts 折叠时通过 .artifacts-collapsed 切到 2 列 */
}

.nexus-desktop.artifacts-collapsed {
  grid-template-columns: 260px minmax(0, 1fr);
}

@media (max-width: 768px) {
  .nexus-desktop { grid-template-columns: 0 1fr 0; }
}
```

`data-theme` 切换 light/dark 不影响 grid（颜色由各子组件 token 驱动）。

---

## 3. 组件

### 3.1 新增

| 组件 | 路径 | 职责 |
|------|------|------|
| `ArtifactsPanel` | `components/Artifacts/ArtifactsPanel.tsx` | 容器：head + tabs + body + foot |
| `ArtifactCodeRenderer` | `components/Artifacts/renderers/CodeRenderer.tsx` | 行号 + 语法高亮（基于 highlight.js，已在依赖） |
| `ArtifactMarkdownRenderer` | `components/Artifacts/renderers/MarkdownRenderer.tsx` | react-markdown 渲染 |
| `ArtifactSvgRenderer` | `components/Artifacts/renderers/SvgRenderer.tsx` | 内联 SVG，`fit width` |
| `ArtifactHtmlRenderer` | `components/Artifacts/renderers/HtmlRenderer.tsx` | sandboxed iframe（`sandbox="allow-scripts"`） |
| `useArtifactsStore` | `src/store/slices/artifacts.ts` | 切片：list + activeId + collapsed |

### 3.2 修改

| 组件 | 修改 |
|------|------|
| `ShellLayout` | grid 列从 2 改 3；新增 `<ArtifactsPanel />` 直挂 |
| `ToolCallCard` | 命中文件类产物时，新增 "→ 在右侧查看" 链接，点击触发 store.push + setActive + 展开 |
| `useGlobalShortcuts` | 新增 `Cmd+\`（macOS）/ `Ctrl+\`（其他）切换 Artifacts 折叠 |
| `index.css` | 新增 3 栏 grid；`.artifacts-collapsed` 类；Art 渲染器样式 |
| `index.ts` (store) | 组合 `useArtifactsStore` |

### 3.3 不动

- Sidebar、ChatArea、Composer、EmptyState、MessageList、PreferencesModal、StatusBar、CommandPalette、SetupView — 视觉/行为零变化
- 后端代码、WebSocket 协议、REST 路由、数据库 schema — 全部零变化
- Tauri 2 桌面壳、PyInstaller 打包脚本 — 零变化

---

## 4. 数据模型

### 4.1 `Artifact` 类型

```ts
// src/store/slices/artifacts.ts
export type ArtifactKind = 'code' | 'markdown' | 'svg' | 'html' | 'unknown';

export interface Artifact {
  id: string;                // nanoid(8),本次会话内唯一
  kind: ArtifactKind;        // 由 content-type / 后缀推断
  filename: string;          // 来自 tool_call.args.path / write_md args 等
  content: string;           // 原始文本(code/md/svg/html 直接存;svg 也存 markup)
  language?: string;         // code 用,如 'python' / 'typescript'
  sourceToolCallId?: string; // 触发该产物的 tool_call.id(供 foot 显示)
  createdAt: number;         // Date.now()
}
```

### 4.2 Store API

```ts
interface ArtifactsState {
  list: Artifact[];
  activeId: string | null;
  collapsed: boolean;

  push(artifact: Omit<Artifact, 'id' | 'createdAt'>): string; // 返回 id
  setActive(id: string): void;
  clear(): void;
  toggleCollapsed(): void;
  setCollapsed(b: boolean): void;
  remove(id: string): void;
}
```

约定：
- `push` 自动推断 `kind`：以 `.md` 结尾 → markdown；`<svg` 开头 → svg；`<!doctype html>` / `<html` 开头 → html；其他 → code（用 filename 后缀给 language）
- `push` 后默认 `setActive(id)` + `setCollapsed(false)`（展开 + 定位）
- 单会话内存持有（不持久化）；`clear()` 由会话切换 / 新对话触发（沿用现有 `conversationMessages` slice 的清理时机）

---

## 5. ToolCallCard → Artifacts 联动

### 5.1 触发条件

ToolCallCard 在以下条件**追加** "→ 在右侧查看" 链接：

1. `toolCall.name` 是白名单之一：`edit_file` / `write_md` / `draw_diagram` / `write_html` / `shell_run`（带文件落地）
2. `toolCall.result` 是字符串且 ≥ 30 字符（避免空产物）
3. `toolCall.args.path` 存在且后缀在 `{ .py, .ts, .tsx, .js, .jsx, .json, .md, .svg, .html, .css, .sh }` 中

不满足条件 → 保持现状，不显示链接。

### 5.2 链接行为

```ts
onClick = () => {
  const kind = inferKind(toolCall.args.path, toolCall.result);
  const id = artifacts.push({
    kind,
    filename: toolCall.args.path,
    content: toolCall.result,
    language: extToLanguage(toolCall.args.path),
    sourceToolCallId: toolCall.id,
  });
  // push 已自动展开 + 定位
};
```

点击后：
1. Artifacts 展开（`collapsed = false`）
2. 新产物入栈 + 自动 active
3. 右侧面板 tab 切到对应 kind（push 时设置）
4. Chat 流位置不变，**不**自动滚动

### 5.3 视觉

链接放在 ToolCallCard 现有"操作区"（result 文本后），样式：

```
✓ edit_file   /tmp/quicksort.py   +120 行                    → 在右侧查看 →
```

颜色用 `--accent` token；hover 加下划线；无障碍：`aria-label="在右侧 Artifacts 面板查看 quicksort.py"`。

---

## 6. 快捷键

| 键位 | 行为 |
|------|------|
| `Cmd+\` (macOS) / `Ctrl+\` (其他) | 切换 Artifacts 折叠 |
| `Esc`（Artifacts 聚焦时） | 折叠 |
| `Cmd+W`（Artifacts 聚焦时） | 清空当前 active |

扩展点：未来可在 `useGlobalShortcuts` 加 `Cmd+1/2/3/4` 切 Artifacts tab，本次不做。

---

## 7. 测试契约

### 7.1 选择器新增

| 选择器 | 含义 |
|--------|------|
| `.artifacts-panel` | 右侧产物面板根 |
| `.artifacts-panel.is-collapsed` | 折叠态（用 CSS 0 宽实现，不渲染） |
| `.artifact-tabs` | tab 容器 |
| `.artifact-tab` | 单个 tab |
| `.artifact-tab.is-active` | 当前激活 tab |
| `.artifact-renderer-code` | Code 渲染器 |
| `.artifact-renderer-markdown` | Markdown 渲染器 |
| `.artifact-renderer-svg` | SVG 渲染器 |
| `.artifact-renderer-html` | HTML iframe 渲染器 |
| `.artifact-foot` | 底部 meta（token / 来源） |
| `.tool-call-card .artifact-link` | ToolCallCard 上"在右侧查看"链接 |

### 7.2 单元 / 组件测试（vitest）

新增 `src/store/slices/__tests__/artifacts.test.ts`：

- `push` 自动推断 kind（覆盖 svg / html / md / py / ts）
- `push` 后默认展开 + 定位到新产物
- `toggleCollapsed` 翻转 `collapsed`
- `clear` 清空 list + activeId
- `remove` 删除指定 id，若删除的是 active 则 activeId 置 null

新增 `src/components/Artifacts/__tests__/`：

- `<ArtifactsPanel />` 折叠时不渲染 tab/body
- `<CodeRenderer />` 显示行号 + 语言标识
- `<MarkdownRenderer />` 渲染标题 / 列表 / code
- `<SvgRenderer />` 内联 svg DOM 存在
- `<HtmlRenderer />` iframe sandbox 属性正确

### 7.3 E2E（journey）

在 `frontend/e2e/journey/journey-redesign.spec.ts` 新增 j11 ~ j13：

- **j11-artifacts-toggle**：`Cmd+\` 切换折叠；视觉上 grid 列数变化（截图为证）
- **j12-tool-call-link**：触发 `edit_file` 类 tool_call，看到 ToolCallCard 上"在右侧查看"链接；点击后 `.artifacts-panel` 可见且 `.artifact-renderer-code` 内容非空
- **j13-artifacts-tabs**：push 一个 markdown 产物 → 切到 Md tab → 看到标题/列表

---

## 8. 视觉规范

### 8.1 Artifacts 面板 token 复用

所有视觉从 `index.css` 既有 token 取，**不新增** color / radius / shadow 变量：

| 用途 | token |
|------|-------|
| 背景 | `var(--paper)` |
| 头/底栏背景 | `var(--paper-2)` |
| 边框 | `var(--line)` |
| 主文字 | `var(--ink)` |
| 次文字 | `var(--ink-2)` |
| 三级文字 | `var(--ink-3)` |
| 圆角 | `var(--r-sm)` / `var(--r-md)` |
| 等宽字体 | `var(--font-mono)` |

### 8.2 Code 渲染器

- 行号列宽 `24px`，右对齐，颜色 `var(--ink-3)`
- 语法高亮用 highlight.js 内置主题（GitHub / GitHub Dark），按 `data-theme` 切；**不引入新依赖**
- 字体 `var(--font-mono)`，字号 12.5px，行高 1.55
- 长行 `<pre>` 内部横向滚动，不换行

### 8.3 Markdown 渲染器

- 标题 / 段落 / 列表继承 `.prose` 已有的样式（已有 `--font-sans` 链路）
- 行内 `code` 用 `var(--paper-2)` 背景 + `var(--r-sm)` 圆角
- 代码块用 `.prose pre`（dark 主题已在 index.css 处理）

### 8.4 SVG 渲染器

- 内联 `<svg>`，`viewBox` 自适应面板宽度
- 最大宽度 = 面板宽度 - 28px padding，垂直居中
- 失败回退：显示 `<pre>` + "SVG 解析失败"

### 8.5 HTML 渲染器

- `<iframe sandbox="allow-scripts" srcDoc={content} />`
- iframe 默认高度 = 面板高度 - 80px(head + foot)
- 顶部一行小字："sandbox · console 隔离 · ↻ 重新加载"
- `loading="lazy"` 减少初始开销

---

## 9. 暗色主题

无需额外工作。`index.css` 既有 `:root[data-theme="dark"]` 已覆盖所有 token，Artifacts 面板继承即可。

- Code 高亮主题按 `data-theme` 切（GitHub / GitHub Dark）
- iframe 内 HTML 自带样式不受外层主题影响（沙箱隔离），用户文档类 HTML 通常自带主题

E2E 加 j14：`artifacts-dark-theme` — 切到 dark 后，Code 渲染器背景变深、行号颜色变化，截图比对。

---

## 10. 迁移与回滚

### 10.1 灰度（可选）

Artifacts 默认折叠，行为兼容旧版 → **本质上是新增，不破坏现有 UX**。

### 10.2 回滚

- 单一 git revert（如果 SPEC 实施时按 atomic commits）
- 删 `ArtifactsPanel / renderers / artifacts slice` 三个文件，CSS 回退到 `264px minmax(0, 1fr)`

### 10.3 数据迁移

无。Artifacts 仅内存持有，刷新即清空。

---

## 11. 风险与权衡

| 风险 | 缓解 |
|------|------|
| highlight.js 体积 | 已在前端依赖中（ECharts / 其他组件引入），不引入新依赖 |
| iframe 安全 | sandbox + 禁止 `allow-same-origin` 防提权 |
| ToolCallCard 改动影响现有 E2E | j4-tool-call-visible 继续通过；新增 j12 只测新增链接，不改旧断言 |
| Artifacts 撑爆窄屏 | ≤768px 自动隐藏 |
| 会话切换未清空 Artifacts | 在 `useChatSend` / 会话切换处补 `artifacts.clear()` 调用 |
| push 同一产物多次（LLM 重发） | 用 `filename + sourceToolCallId` 去重（本次不做，后续可加） |

---

## 12. 实施步骤（高层）

1. SPEC 审过 → 写 plan（writing-plans）
2. Plan 审过 → 执行（subagent-driven-development）
3. 任务清单（详见 plan）：
   - Task 1: artifacts store slice + 单元测试
   - Task 2: ArtifactsPanel 容器 + tabs + head + foot
   - Task 3: CodeRenderer / MarkdownRenderer / SvgRenderer / HtmlRenderer
   - Task 4: ShellLayout 三栏 grid + 折叠 class
   - Task 5: ToolCallCard "在右侧查看" 联动
   - Task 6: Cmd+\ 快捷键 + 折叠 toggle
   - Task 7: 测试契约补充 + journey j11-j14
   - Task 8: dark 主题适配验证

---

## 13. 验收清单

- [ ] `npm run test:vitest` 全过（含新增 artifacts store / renderer 单测）
- [ ] `npm run test:e2e` 全过（含新增 j11-j14）
- [ ] `npm run lint` 0 error
- [ ] `npm run build` 成功
- [ ] Dev server 手动验证：空态 / 对话中 / Artifacts 展开 / dark 主题 四个截图与 mock 设计稿视觉一致
- [ ] Cmd+\ 切换折叠生效，键盘焦点不被打断
- [ ] ToolCallCard 联动点击后，Artifacts 展开 + 内容正确
- [ ] iframe sandbox 不允许同源、不允许 top navigation（手动验证一次）
- [ ] `docs/designs/frontend.md` 同步更新到三栏形态（本 SPEC 完成后合并进去）
- [ ] `CHANGELOG.md` 加 0.x 版本条目

---

## 14. 文档同步

完成后需同步：

- `docs/designs/frontend.md` — 把 2.1 节"两列布局"改为"三列布局（Artifacts 默认折叠）"，新增 Artifacts 章节
- `CHANGELOG.md` — 新增版本条目
- `frontend/README.md` — 简述 Artifacts 行为
- 本 SPEC 文件保留，作为该次重构的设计决策追溯

---

*草案 0.1 · 2026-07-20 · 待 review*