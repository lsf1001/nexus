# 灰阶主题重构 — Claude Desktop 双色风格

> 日期:2026-07-17
> 作者:Nexus
> 状态:design(待用户批准 → 进 writing-plans)

## 1. 目标与动机

当前前端主题是"森林绿 + 鼠尾草 + 茶叶 + 微信绿"四色品牌调,源自 `nexus-handdrawn-assistant-ui-v2.html` 原型。第九轮/第十轮迭代后用户反馈:**"前端主题只有黑白两种颜色"** — 决定参考 Claude Desktop 双色设计,所有品牌强调色去掉,只保留黑白灰阶 + 状态色(error/success/warn/info)。

### 1.1 范围(in scope)

| 项 | 改动 |
|----|----|
| `frontend/src/components/desktop/styles/tokens.css` | 重写 `:root` 与 `:root[data-theme="dark"]` 两套 token,删除 brand 色 |
| `frontend/src/components/desktop/styles/views.css` | 引用 `forest / forest-2 / forest-soft / sage / tea / wechat` 的位置全部改灰阶 token(全文件 ~80 处旧 token 引用) |
| `frontend/src/components/desktop/styles/shell.css` | 同上(~15 处) |
| `frontend/src/components/desktop/styles/chat.css` | 同上(~10 处,含 `forest-strong`) |
| `frontend/src/components/desktop/styles/responsive.css` | 响应式断点内如有硬编码彩色,改 token(~2 处) |
| `frontend/src/index.css` | `@theme` Tailwind token 中的 moss/wood/cream 等去掉,新增中性灰 token |
| `frontend/src/components/ModelConfigModal.tsx` | 硬编码 hex(`#4a7c59` / `#e0dcd4` / `#8fbc8f` / `#f0f7f1` 等)改 Tailwind `gray-*` 类 |
| `frontend/src/components/WechatPluginModal.tsx` | 硬编码 hex(`#4a7c59` / `#5a6b52` / `#8a9a7a` 等)改 Tailwind `gray-*` 类 |
| 锁测试 `frontend/src/styles/__tests__/tokens-dark.test.ts` | 改断言:不再检查"森林绿族",改为检查"所有 token 饱和度 ≤ 0.1" |
| 锁测试 `frontend/src/components/desktop/styles/__tests__/*.test.ts` | 4 个(shell-sidebar-brand / focus-ring / product-polish / a11y-polish),按新色板更新断言 |

### 1.2 范围外(out of scope)

- **状态色**:`ToastHost` 中的 `info / success / warn / error` 四种语义色 **保留不动**(红/黄/绿/蓝)— 它们表示系统状态,不是品牌强调色
- **错误色**:`#c62828` / `#ffebee` / `#e8f5e9` 等"出错了 / 已绑定"提示色 **保留** — 同上,语义色
- **`-text-muted: #5a6b52`**:在 WechatPluginModal 用作次文字 — 改为 `gray-500` 即可
- **深色模式背景渐变**:Claude Desktop 是纯色而非渐变,渐变去除

## 2. 新色板

### 2.1 原则

1. **Claude Desktop 双色** — 浅色=白底 + 深文字;深色=近黑底 + 浅文字。无中间暖色调
2. **三档 ink + 三档 paper + 两档 line** — 灰阶等级化,不要一个 hex 应付所有
3. **一个 `--accent`** — 用于"被选中/被强调",值与 `--ink` 相同(强调 = 文字色压底)
4. **不保留任何绿色品牌色** — sage / tea / forest / moss 全部清零
5. **`--wechat` 改成中性灰** — 作为"通道识别色"灰阶化:light=#4a4a4a,dark=#b5b5b5

### 2.2 Light(`:root`)

```css
:root {
  /* 文字三档 */
  --ink:      #1f1f1f;   /* 主文字 */
  --ink-2:    #4a4a4a;   /* 次文字 */
  --ink-3:    #8a8a8a;   /* 三级:divider / disabled */

  /* 纸面三档 */
  --paper:    #ffffff;   /* 主背景 */
  --paper-2:  #f7f7f7;   /* 卡片/sidebar 起始 */
  --paper-3:  #ededed;   /* hover/active 底 */

  /* 描边两档 */
  --line:     #e5e5e5;
  --line-2:   #d0d0d0;

  /* 强调 */
  --accent:        #1f1f1f;
  --accent-soft:   #ededed;

  /* 通道识别色(灰阶化) */
  --wechat:        #4a4a4a;

  /* 阴影 */
  --shadow-lg: 0 28px 70px rgba(0, 0, 0, 0.10);
  --shadow-md: 0 14px 34px rgba(0, 0, 0, 0.06);
  --shadow-sm: 0  7px 18px rgba(0, 0, 0, 0.04);

  /* sidebar(Claude Desktop 浅) */
  --sidebar-bg:        #fafafa;
  --sidebar-bg-2:      #f0f0f0;
  --sidebar-fg:        #1f1f1f;
  --sidebar-fg-2:      #5a5a5a;
  --sidebar-fg-3:      #9a9a9a;
  --sidebar-divider:   rgba(0, 0, 0, 0.08);
  --sidebar-hover-bg:  rgba(0, 0, 0, 0.04);

  /* 焦点环 */
  --focus-ring:        #000000;
  --focus-ring-offset: #ffffff;
}
```

### 2.3 Dark(`:root[data-theme="dark"]`)

```css
:root[data-theme="dark"] {
  --ink:      #ededed;
  --ink-2:    #a8a8a8;
  --ink-3:    #6e6e6e;

  --paper:    #1a1a1a;
  --paper-2:  #232323;
  --paper-3:  #2c2c2c;

  --line:     #2e2e2e;
  --line-2:   #404040;

  --accent:       #ededed;
  --accent-soft:  #2c2c2c;

  --wechat:       #b5b5b5;

  --shadow-lg: 0 28px 70px rgba(0, 0, 0, 0.55);
  --shadow-md: 0 14px 34px rgba(0, 0, 0, 0.40);
  --shadow-sm: 0  7px 18px rgba(0, 0, 0, 0.25);

  --sidebar-bg:        #161616;
  --sidebar-bg-2:      #1f1f1f;
  --sidebar-fg:        #ededed;
  --sidebar-fg-2:      #a8a8a8;
  --sidebar-fg-3:      #6e6e6e;
  --sidebar-divider:   rgba(255, 255, 255, 0.08);
  --sidebar-hover-bg:  rgba(255, 255, 255, 0.05);

  --focus-ring:        #ffffff;
  --focus-ring-offset: #1a1a1a;
}
```

### 2.4 删除的旧 token

`--muted` / `--faint` / `--canvas` / `--paper-soft` / `--paper-tint` / `--forest` / `--forest-2` / `--forest-soft` / `--sage` / `--tea` / `--forest-strong` — 全部删除。

## 3. Tailwind `@theme` 调整(`index.css`)

### 3.1 删除

`--color-forest-start / --color-forest-end / --color-moss / --color-moss-dark / --color-moss-light / --color-cream / --color-cream-dark / --color-wood / --color-text-dark / --color-text-muted / --color-border / --color-toggle-off / --color-moss-rgb / --color-thinking-text`

### 3.2 新增(对齐 Tailwind 默认 `gray-*` 体系,简化)

```css
@theme {
  --color-ink:      #1f1f1f;   /* 替代 --color-text-dark */
  --color-paper:    #ffffff;   /* 替代 --color-cream */
  --color-line:     #e5e5e5;   /* 替代 --color-border */
}
```

深色由 `dark:` 前缀 + 系统 `gray-*` 处理(已有的 Tailwind 自带 gray 调色板够用,不引入新 token)。

### 3.3 `body` / `html` 默认色

```css
html, body {
  background: #ffffff;
  color: #1f1f1f;
}
@media (prefers-color-scheme: dark) {
  html, body {
    background: #1a1a1a;
    color: #ededed;
  }
}
:root[data-theme="dark"], :root[data-theme="dark"] body {
  background: #1a1a1a;
  color: #ededed;
}
```

## 4. 组件 CSS 调整细则

### 4.1 `chat.css` — 用户消息气泡

```diff
 .message-user {
-  background: var(--forest);
+  background: var(--ink);   /* light 下深底白字 */
   color: #ffffff;
 }
+.nexus-desktop[data-theme="dark"] .message-user {
+  background: var(--accent);   /* dark 下浅底深字 */
+  color: var(--paper);
+}
 .message-user .message-markdown code {
   background: rgba(255, 255, 255, 0.18);
 }
```

`--forest-strong` 引用 → 直接删,用 `--ink`(值与 `--accent` 同)。

### 4.2 `chat.css` — copy button / tool-call name

```diff
 .copy-button:hover {
-  color: var(--forest);
+  color: var(--ink-2);
 }
 .tool-call-name {
-  color: var(--forest);
+  color: var(--ink);
 }
```

### 4.3 `shell.css` — sidebar wechat inbox badge / footer link

```diff
 .sidebar-footer .footer-link--wechat.is-connected .footer-link-icon {
-  color: var(--wechat);
+  color: var(--wechat);   /* 仍是 --wechat token,值已改 #4a4a4a(light)/ #b5b5b5(dark) */
 }
 .wechat-inbox-badge {
-  background: var(--wechat);
+  background: var(--ink-2);   /* badge 用 ink-2 中灰,与 --wechat token 解耦 */
 }
```

WHY 解耦:badge 是数量提示,高对比更好;`--wechat` 留给"图标 / 文字标识"那种柔和识别场景。

### 4.4 `views.css` — wechat-bind-card / status chip / 选中边框

`forest / forest-2 / forest-soft` 全部按 §2.4 映射表替换。具体:

```diff
 .wechat-bind-card {
-  background: var(--forest-soft);
+  background: var(--accent-soft);
 }
 .wechat-bind-card input:focus-visible {
-  border-color: var(--forest);
+  border-color: var(--ink);
 }
 .wechat-bind-card .btn-primary {
-  background: var(--forest);
+  background: var(--ink);
 }
 .wechat-bind-card .btn-primary:hover {
-  background: var(--forest-2);
+  background: var(--ink-2);
 }
 .wechat-status-chip.connected {
-  background: var(--forest-soft);
-  color: var(--forest);
+  background: var(--accent-soft);
+  color: var(--ink);
 }
```

`sage / tea` 引用(`tokens.css` 第 240-242 行的 `.sketch-line ellipse` 手绘装饰)— 该文件 `::before` / `::after` 已用 `content: none` 整体禁掉,装饰死代码,删。

`.btn-primary`(`views.css:199-205`)全局按钮主态:
```diff
 .btn-primary {
-  background: var(--forest);
-  color: var(--paper-tint);
-  box-shadow: 0 6px 16px rgba(49, 79, 56, 0.20);
+  background: var(--ink);          /* dark 模式反色 */
+  color: var(--paper);
+  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.20);
 }
 .btn-primary:hover:not(:disabled) {
-  background: var(--forest-2);
+  background: var(--ink-2);
 }
+.nexus-desktop[data-theme="dark"] .btn-primary {
+  background: var(--accent);
+  color: var(--paper);
+}
+.nexus-desktop[data-theme="dark"] .btn-primary:hover:not(:disabled) {
+  background: var(--paper-3);
+}
```

`forest-strong` 引用 2 处:
- `views.css:677` `.channel-copy-inline` 顶栏渐变 → 改为 `--ink`(主文字色)单色,无渐变
- `chat.css:206` tool-call name strong → 改为 `--ink-2`(与弱化一档的工具名一致)

### 4.5 `responsive.css`

仅断点内 `forest / sage` 引用,替换为新 token。无新增断点规则。

## 5. TSX 硬编码 hex 调整

### 5.1 `ModelConfigModal.tsx`

10 处硬编码 hex,逐个替换为 Tailwind `gray-*`:

| 旧 hex | 替换为 | 用途 |
|--------|--------|------|
| `#4a7c59` | `bg-gray-900` / `text-gray-900` / `border-gray-900` | 主强调色 |
| `#8fbc8f` | `bg-gray-700` / `hover:bg-gray-700` | hover |
| `#2d4a3a` | `bg-gray-800` / `hover:bg-gray-800` | active/按下 |
| `#e0dcd4` | `border-gray-200` | 默认边框 |
| `#f0f7f1` | `bg-gray-50` | 选中底 |
| `#6b7c6b` | `text-gray-500` | 次文字 |

### 5.2 `WechatPluginModal.tsx`

| 旧 hex | 替换为 | 用途 |
|--------|--------|------|
| `#4a7c59` / `#2d4a3a` | `bg-gray-900` / `bg-gray-800` | 主按钮/渐变止 |
| `#3d6a4a` | `bg-gray-800` | hover |
| `#f0f2ed` | `bg-gray-100` | icon 容器 |
| `#5a6b52` | `text-gray-500` | 次文字 |
| `#8a9a7a` | `text-gray-400` | 三级文字 |
| `#e8f5e9` | `bg-gray-100` | 已绑定 icon 容器 |
| `#2d4a3a` | `text-gray-900` | "已绑定"标题 |
| `#ffebee` | 保留(error 状态色,语义色不动) |
| `#c62828` | 保留(error 状态色) |
| `#666` | `text-gray-500` | 次文字 |
| `from-[#4a7c59] to-[#2d4a3a]` | `from-gray-900 to-gray-800` | 顶栏渐变 |

### 5.3 `ToastHost.tsx`

不动。info / success / warn / error 状态色是语义色,语义色保留。

## 6. 锁测试更新

### 6.1 `tokens-dark.test.ts`

**现有断言**(锁"森林绿族"):
```ts
expect(g).toBeGreaterThanOrEqual(80);
expect(g).toBeGreaterThan(r);
expect(b / r).toBeLessThan(2.0);  // 防 teal
```

**新断言**(锁"灰阶,无彩色"):
```ts
// 锁:两套主题所有 token 的 HSL 饱和度必须 ≤ 0.10
// WHY:防止回归出彩色(sage/tea/forest/微信绿等)
const tokens = ['ink', 'ink-2', 'ink-3', 'paper', 'paper-2', 'paper-3',
  'line', 'line-2', 'accent', 'accent-soft', 'wechat'];
for (const name of tokens) {
  const { r, g, b } = hexToRgb(getToken(light, name));
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  const sat = max === 0 ? 0 : (max - min) / max;
  expect(sat, `${name} light 饱和度 ${sat.toFixed(2)} 过高`).toBeLessThanOrEqual(0.10);
}
// dark 同样
```

`FORBIDDEN_HEXES` 数组保留(防历史 teal 回归),不动。

### 6.2 `focus-ring.test.ts`

不动 — 焦点环值无变化,断言仍过。

### 6.3 `product-polish.test.ts` / `a11y-polish.test.ts` / `shell-sidebar-brand.test.ts`

需要按 §2.2 / §2.3 新值更新断言(读取 token 值的具体 hex)。具体每条断言在 plan 阶段逐条更新。

## 7. 风险与回归

| 风险 | 缓解 |
|------|------|
| 微信绿徽标改成灰后用户不认得"哪个通道是微信" | sidebar 底部仍有文字"微信通道";inbox badge 数字仍醒目 |
| 用户消息气泡从绿底变黑底,反差点变了 | a11y 对比度:白字 / `#1f1f1f` 底 = 17.5:1(超 WCAG AAA 7:1) |
| 深色模式无彩色强调,用户找"我在哪里"会更费眼 | `--paper-3` 比 `--paper-2` 浅一档,作为 hover/active 视觉锚;选中态用 `--ink` 反白 |
| 深色背景从"森林绿 #1a3328" 变"#1a1a1a 真黑" — 是有意的(参考 Claude Desktop),用户可能短期不适应 | 在 CHANGELOG 标注;如果用户反馈"太黑",可以再把 dark paper 提一档到 `#1f1f1f` |
| 锁测试改动大,如果漏改会全红 | plan 阶段按 5 个测试文件逐条列断言 diff,实施时用 grep 验证 |

## 8. 验收

- `npm run lint`(frontend)0 error
- `npm run test`(vitest + 锁测试)全过
- `npm run build`(Vite + TS 严格模式)无 type 错
- 桌面端手测:
  1. light 模式:整窗白底,无任何彩色装饰;用户消息气泡黑底白字;选中态黑底
  2. dark 模式:整窗近黑,无绿色森林调;用户消息气泡浅灰底深字
  3. 微信通道:sidebar 文字"微信通道"仍可识别,inbox badge 数字醒目
  4. 切换深浅:无闪烁(`useDarkModeRoot` MutationObserver 仍生效)
- 桌面端 DMG 构建:`bash scripts/build_dmg.sh` 成功

## 9. 不做(YAGNI)

- 不做"主题三态"(增加一个"跟随系统"以外的中间态)— 当前 store 已是 light/dark 二态
- 不做"用户自定义 accent 色" — 黑白二色已是最终态
- 不做 CSS variable 命名规范统一 — 仅本次重命名 ink/paper/line/accent 体系
- 不改后端 — 纯前端样式

## 10. 实施顺序(在 plan 中细化)

1. `tokens.css` 重写 light + dark 两套
2. `index.css` `@theme` + body 默认色更新
3. `chat.css` / `shell.css` / `views.css` / `responsive.css` 引用面替换
4. `ModelConfigModal.tsx` / `WechatPluginModal.tsx` 硬编码 hex 替换
5. 锁测试更新(5 个 test 文件)
6. 跑 `npm run lint && npm run test && npm run build`
7. 手测深浅切换 + DMG 构建
8. CHANGELOG 标注 + 提交