# 灰阶主题重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Nexus 桌面端 CSS 主题从"森林绿 + 鼠尾草 + 茶叶 + 微信绿"四色品牌调重构成 Claude Desktop 双色灰阶(白/黑 + 三档灰),只保留状态色与焦点环。

**Architecture:** 三层落地 — (1) `tokens.css` 重写 light/dark 两套 token 体系为 `ink/paper/line/accent` 语义名; (2) 5 个 CSS 文件按 §2.4 映射表替换 ~107 处旧 token 引用; (3) 2 个 TSX 文件 16 处硬编码 hex 改为 Tailwind `gray-*` 类; (4) 5 个锁测试改断言防彩色回归。

**Tech Stack:** Vite + React 19 + Tailwind CSS 4 + Vitest(锁测试)+ TypeScript 严格模式。

**Spec:** `docs/superpowers/specs/2026-07-17-grayscale-theme-redesign-design.md`

---

## File Structure

| 文件 | 责任 |
|-----|------|
| `frontend/src/components/desktop/styles/tokens.css` | light + dark 两套 `:root` token 重写 |
| `frontend/src/components/desktop/styles/chat.css` | 用户消息气泡、copy button、tool-call name 引用替换 |
| `frontend/src/components/desktop/styles/shell.css` | sidebar wechat inbox badge / footer link 引用替换 |
| `frontend/src/components/desktop/styles/views.css` | wechat-bind-card / status chip / btn-primary / 各种 muted / forest 引用替换 |
| `frontend/src/components/desktop/styles/responsive.css` | 响应式断点内 forest / sage 引用替换 |
| `frontend/src/index.css` | `@theme` Tailwind token + body 默认色 |
| `frontend/src/components/ModelConfigModal.tsx` | 10 处硬编码 hex → Tailwind `gray-*` |
| `frontend/src/components/WechatPluginModal.tsx` | 12 处硬编码 hex → Tailwind `gray-*` |
| `frontend/src/styles/__tests__/tokens-dark.test.ts` | 改断言:无彩色饱和度 |
| `frontend/src/components/desktop/styles/__tests__/{focus-ring,product-polish,a11y-polish,shell-sidebar-brand}.test.ts` | 按新色板更新 hex 断言 |
| `docs/superpowers/progress.md` | 第十二轮进度追加 |

---

## Task 1: 重写 `tokens.css` — 删旧 token,新增 light/dark 双套

**Files:**
- Modify: `frontend/src/components/desktop/styles/tokens.css`(全文件覆盖)

- [ ] **Step 1: 备份当前 tokens.css 一行(写到 commit message)**

```bash
git diff --stat frontend/src/components/desktop/styles/tokens.css
```

预期:看到文件 ~244 行,先看改动量再下手。

- [ ] **Step 2: 替换 `:root` 块(行 12-94)**

把 `:root { ... }`(行 12 到行 94,共 83 行)整段替换为 spec §2.2 的新内容:

```css
:root {
  /* 文字三档 */
  --ink:      #1f1f1f;
  --ink-2:    #4a4a4a;
  --ink-3:    #8a8a8a;

  /* 纸面三档 */
  --paper:    #ffffff;
  --paper-2:  #f7f7f7;
  --paper-3:  #ededed;

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

  /* 字体 stack:保持原值不动 */
  --font-sans: "SF Pro Display", "PingFang SC", "Avenir Next",
    ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
    "Segoe UI", "PingFang SC", "Hiragino Sans GB", sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;

  /* 圆角:保持原值不动 */
  --r-sm: 9px;
  --r-md: 12px;
  --r-lg: 16px;
  --r-xl: 20px;
  --r-2xl: 28px;

  /* 间距 + 字号:保持原值不动 */
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

  /* Sidebar(Claude Desktop 浅) */
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

- [ ] **Step 3: 替换 dark 块(行 102-145)**

把 `:root[data-theme="dark"] { ... }`(行 102 到行 145)整段替换为 spec §2.3 的内容:

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

- [ ] **Step 4: 删除 `.nexus-desktop[data-theme="dark"] .sketch-line ellipse` 规则(行 240-243)**

```css
.nexus-desktop[data-theme="dark"] .sketch-line ellipse[fill="none"] {
  stroke-opacity: 0.18;
}
.nexus-desktop[data-theme="dark"] .sketch-line ellipse[fill="var(--sage)"],
.nexus-desktop[data-theme="dark"] .sketch-line ellipse[fill="var(--tea)"] {
  fill-opacity: 0.06;
}
```

整段删除(sage/tea 已无 token,装饰死代码)。

- [ ] **Step 5: 验证 Vite 编译**

```bash
cd frontend && npm run build 2>&1 | tail -20
```

预期: 编译失败(因为后续 CSS 文件还引用了 `--forest` 等旧 token),但**没有 "unknown CSS variable" 类型错误**——因为 CSS 变量缺失是运行时 cascade 缺失,不会让 Vite 编译失败。如果有 TS 类型错或 Vite 语法错,停下。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/components/desktop/styles/tokens.css
git commit -m "feat(desktop): 重写 tokens.css — Claude Desktop 灰阶主题(第十二轮)"
```

---

## Task 2: 更新 `index.css` — Tailwind `@theme` + body 默认色

**Files:**
- Modify: `frontend/src/index.css`

- [ ] **Step 1: 替换 `@theme` 块(行 2-19)**

把:

```css
@theme {
  --color-forest-start: #1a3d2a;
  --color-forest-end: #0f2618;
  --color-moss: #4a7c59;
  --color-moss-dark: #3A6249;
  --color-moss-light: #8fbc8f;
  --color-cream: #faf8f5;
  --color-cream-dark: #f0ebe3;
  --color-wood: #d4a574;
  --color-text-dark: #2c3e2d;
  --color-text-muted: #5a6b52;
  --color-border: #c8d4c0;
  --color-toggle-off: #9CA3AF;
  --color-moss-rgb: 74, 124, 89;
  --color-thinking-text: #4a5d42;
}
```

替换为:

```css
@theme {
  --color-ink:   #1f1f1f;
  --color-paper: #ffffff;
  --color-line:  #e5e5e5;
}
```

- [ ] **Step 2: 替换 body 默认色 + dark 媒体查询 + JS dark mode 块(行 22-末尾)**

把:

```css
html, body {
  height: 100%;
  overflow: hidden;
  background: #f5f7f2;
  color: #1a1a1a;
}
@media (prefers-color-scheme: dark) {
  html, body {
    background: #1a3328;
    color: #f5efe2;
  }
}
:root[data-theme="dark"],
:root[data-theme="dark"] body {
  background: #1a3328;
  color: #f5efe2;
}
```

替换为:

```css
html, body {
  height: 100%;
  overflow: hidden;
  background: #ffffff;
  color: #1f1f1f;
}
@media (prefers-color-scheme: dark) {
  html, body {
    background: #1a1a1a;
    color: #ededed;
  }
}
:root[data-theme="dark"],
:root[data-theme="dark"] body {
  background: #1a1a1a;
  color: #ededed;
}
```

(注: 行 56-148 是 `index.css` 后续的 utility 类,保留不动。)

- [ ] **Step 3: 验证 Vite 编译 + lint**

```bash
cd frontend && npm run build 2>&1 | tail -10
```

预期: 编译成功(CSS 变量缺失不影响 Vite,Tailwind 自身不依赖这些 `--color-*` 编译期常量)。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/index.css
git commit -m "feat(desktop): Tailwind @theme 简化为 ink/paper/line 三 token"
```

---

## Task 3: 替换 `chat.css` — 用户消息气泡 + copy + tool-call

**Files:**
- Modify: `frontend/src/components/desktop/styles/chat.css`

- [ ] **Step 1: 替换 `.message-user` 块(行 122-127)**

`--forest` → `--ink`(浅色下深底白字),加 dark 反色:

```diff
 .message-user {
-  background: var(--forest);
+  background: var(--ink);
   color: #ffffff;
 }
+.nexus-desktop[data-theme="dark"] .message-user {
+  background: var(--accent);
+  color: var(--paper);
+}
```

- [ ] **Step 2: 替换 `--forest-strong` 引用(行 206)**

```diff
-  color: var(--forest-strong, var(--forest));
+  color: var(--ink-2);
```

- [ ] **Step 3: 替换其他 `--forest` 引用(行 176 / 198 / 217 / 225 / 274 / 292)**

用 `replace_all` 把整个文件里所有 `var(--forest)` 替换为 `var(--ink)`(注意 `--forest-2 / --forest-soft / --forest-strong` 是不同 token,需要单独替换):

```bash
cd frontend
# 主色: forest → ink
sed -i '' 's/var(--forest)/var(--ink)/g' src/components/desktop/styles/chat.css
# hover: forest-2 → ink-2
sed -i '' 's/var(--forest-2)/var(--ink-2)/g' src/components/desktop/styles/chat.css
# chip 底: forest-soft → accent-soft
sed -i '' 's/var(--forest-soft)/var(--accent-soft)/g' src/components/desktop/styles/chat.css
# strong(已 Step 2 改过)但 sed 不会重复
sed -i '' 's/var(--forest-strong, var(--forest))/var(--ink-2)/g' src/components/desktop/styles/chat.css
```

(注: `sed -i ''` 是 macOS BSD sed 语法,Linux 上用 `sed -i` 即可。)

- [ ] **Step 4: 验证 grep 残留**

```bash
grep -nE 'forest|sage|tea' src/components/desktop/styles/chat.css
```

预期: 0 匹配。

- [ ] **Step 5: 验证 Vite 编译**

```bash
cd frontend && npm run build 2>&1 | tail -10
```

预期: 编译成功(只检查 Vite 自身的语法 / TS 错,不检查视觉)。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/components/desktop/styles/chat.css
git commit -m "feat(desktop): chat.css 灰阶化 — 用户气泡/copy/tool-call 全部走 ink"
```

---

## Task 4: 替换 `shell.css` — wechat inbox badge + footer link

**Files:**
- Modify: `frontend/src/components/desktop/styles/shell.css`

- [ ] **Step 1: 替换 `--forest-strong` 引用(行 631)**

```diff
-  color: var(--forest, #2a4a30);
+  color: var(--ink);
```

- [ ] **Step 2: 替换其他 `--forest` / `--wechat` 引用**

`shell.css` 出现的位置:

- 行 369: `background: var(--wechat);` — wechat mark 大图标背景
- 行 424: `.footer-link--wechat.is-connected .footer-link-icon { color: var(--wechat); }`
- 行 428: `.footer-link--wechat.is-connected .footer-link-status { color: var(--wechat); }`
- 行 440: `.wechat-inbox-badge { background: var(--wechat); }` — inbox 数字徽标
- 行 708: `background: var(--wechat);` — 另一处 wechat 背景
- 行 724: `background: var(--tea);` — 装饰色 tea

替换规则(按 spec §4.3):
- 行 369 / 708 — wechat mark 背景 → `var(--ink-2)`(中性深灰)
- 行 424 / 428 — footer link 文字色 → **保持 `var(--wechat)`**(值已灰阶化,这是识别色场景)
- 行 440 — inbox badge 数字背景 → `var(--ink-2)`(高对比徽标)
- 行 724 — tea 装饰色 → `var(--ink-3)`(弱化背景)

逐个 Edit:

```diff
--- a/frontend/src/components/desktop/styles/shell.css
+++ b/frontend/src/components/desktop/styles/shell.css
@@ -366,7 +366,7 @@
 }
 .wechat-mark {
   color: #ffffff;
-  background: var(--wechat);
+  background: var(--ink-2);
 }
 .wechat-benefits {
@@ -421,11 +421,11 @@
 .sidebar-footer .footer-link--wechat.is-connected .footer-link-icon {
-  color: var(--wechat);
+  /* 保持 var(--wechat) — token 值已灰阶化(light=#4a4a4a dark=#b5b5b5) */
   color: var(--wechat);
 }
 .sidebar-footer .footer-link--wechat.is-connected .footer-link-status {
-  color: var(--wechat);
+  /* 同上,识别色 */
   color: var(--wechat);
 }
 .wechat-inbox-badge {
   color: #ffffff;
-  background: var(--wechat);
+  background: var(--ink-2);
 }
@@ -705,7 +705,7 @@
 .wechat-plugin {
-  background: var(--wechat);
+  background: var(--ink-2);
 }
 .wechat-plugin-plugin {
-  background: var(--tea);
+  background: var(--ink-3);
 }
```

(注: `/* 注释 */` 不必写,删掉。简化为只改值:)

```diff
 .sidebar-footer .footer-link--wechat.is-connected .footer-link-icon {
   color: var(--wechat);
 }
 .sidebar-footer .footer-link--wechat.is-connected .footer-link-status {
   color: var(--wechat);
 }
```

(这两行其实**不需要改**——`var(--wechat)` 在新 token 中值已灰阶化,留作识别色。)

实际操作:**行 369 / 440 / 708 / 724 四处 Edit,行 424 / 428 不动**。

- [ ] **Step 3: 验证 grep 残留**

```bash
grep -nE 'forest|sage|tea' src/components/desktop/styles/shell.css
```

预期: 0 匹配(只可能有注释里的字面 "forest")。

- [ ] **Step 4: 验证 Vite 编译**

```bash
cd frontend && npm run build 2>&1 | tail -10
```

预期: 编译成功。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/desktop/styles/shell.css
git commit -m "feat(desktop): shell.css 灰阶化 — wechat mark/badge 用 ink-2"
```

---

## Task 5: 替换 `views.css` — ~80 处旧 token 引用

**Files:**
- Modify: `frontend/src/components/desktop/styles/views.css`

- [ ] **Step 1: 用 sed 批量替换 4 个旧 token 变体**

`views.css` 旧 token 引用密度最高(80+ 处),按 spec §2.4 映射表批量替换:

```bash
cd frontend
# 主色 forest → ink
sed -i '' 's/var(--forest)/var(--ink)/g' src/components/desktop/styles/views.css
# hover forest-2 → ink-2
sed -i '' 's/var(--forest-2)/var(--ink-2)/g' src/components/desktop/styles/views.css
# chip 底 forest-soft → accent-soft
sed -i '' 's/var(--forest-soft)/var(--accent-soft)/g' src/components/desktop/styles/views.css
# strong(views.css:677 channel-copy-inline 顶栏)
sed -i '' 's/var(--forest-strong, #2a4a30)/var(--ink)/g' src/components/desktop/styles/views.css
# 次文字 muted → ink-2
sed -i '' 's/var(--muted)/var(--ink-2)/g' src/components/desktop/styles/views.css
# 三级 faint → ink-3(views.css 应该无,faint 主要在 tokens.css 已删)
sed -i '' 's/var(--faint)/var(--ink-3)/g' src/components/desktop/styles/views.css
# paper-soft → paper-2
sed -i '' 's/var(--paper-soft)/var(--paper-2)/g' src/components/desktop/styles/views.css
# paper-tint → paper
sed -i '' 's/var(--paper-tint)/var(--paper)/g' src/components/desktop/styles/views.css
```

- [ ] **Step 2: `.btn-primary` 块单独改(spec §4.4)**

views.css 行 199-225 的 `.btn-primary` 块,改值 + 加 dark 反色:

找到:
```css
.btn-primary {
  background: var(--ink);          /* 已 Step 1 替换 */
  color: var(--paper);             /* 已 Step 1 替换 */
  box-shadow: 0 6px 16px rgba(49, 79, 56, 0.20);
}
.btn-primary:hover:not(:disabled) {
  background: var(--ink-2);
  transform: translateY(-1px);
}
.btn-primary:disabled {
  opacity: 0.48;
}
```

把 `box-shadow` 的暖棕色 rgba 改成纯黑:
```diff
-  box-shadow: 0 6px 16px rgba(49, 79, 56, 0.20);
+  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.20);
```

然后在 `.btn-primary` 块后加 dark 模式反色:
```css
.nexus-desktop[data-theme="dark"] .btn-primary {
  background: var(--accent);
  color: var(--paper);
}
.nexus-desktop[data-theme="dark"] .btn-primary:hover:not(:disabled) {
  background: var(--paper-3);
}
```

- [ ] **Step 3: 验证 grep 残留**

```bash
grep -nE 'forest|sage|tea|muted\)|faint\)|paper-soft|paper-tint' src/components/desktop/styles/views.css
```

预期: 0 匹配(可能只剩注释里的字面 "forest" / "muted")。

- [ ] **Step 4: 验证 Vite 编译**

```bash
cd frontend && npm run build 2>&1 | tail -10
```

预期: 编译成功。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/desktop/styles/views.css
git commit -m "feat(desktop): views.css 灰阶化 — 80 处旧 token 替换 + btn-primary dark 反色"
```

---

## Task 6: 替换 `responsive.css` — 断点内 2 处

**Files:**
- Modify: `frontend/src/components/desktop/styles/responsive.css`

- [ ] **Step 1: grep 当前引用**

```bash
grep -nE 'forest|sage|tea|muted|faint' src/components/desktop/styles/responsive.css
```

预期: 0~2 处。

- [ ] **Step 2: 替换(若有)**

```bash
cd frontend
sed -i '' 's/var(--forest)/var(--ink)/g' src/components/desktop/styles/responsive.css
sed -i '' 's/var(--forest-2)/var(--ink-2)/g' src/components/desktop/styles/responsive.css
sed -i '' 's/var(--forest-soft)/var(--accent-soft)/g' src/components/desktop/styles/responsive.css
```

- [ ] **Step 3: 验证**

```bash
grep -nE 'forest|sage|tea|muted|faint' src/components/desktop/styles/responsive.css
```

预期: 0 匹配。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/components/desktop/styles/responsive.css
git commit -m "feat(desktop): responsive.css 灰阶化(若有引用)"
```

---

## Task 7: `ModelConfigModal.tsx` — 10 处硬编码 hex 替换

**Files:**
- Modify: `frontend/src/components/ModelConfigModal.tsx`

- [ ] **Step 1: 逐处 Edit**

按 spec §5.1 表替换:

| 行 | 旧 | 新 |
|----|----|----|
| 201 | `bg-[#4a7c59] hover:bg-[#8fbc8f]` | `bg-gray-900 hover:bg-gray-700` |
| 217 | `border-[#4a7c59] bg-[#f0f7f1]` | `border-gray-900 bg-gray-50` |
| 218 | `border-[#e0dcd4] hover:border-[#8fbc8f]` | `border-gray-200 hover:border-gray-700` |
| 233 | `bg-[#4a7c59] text-white` | `bg-gray-900 text-white` |
| 248 | `bg-[#4a7c59] text-white hover:bg-[#2d4a3a]` | `bg-gray-900 text-white hover:bg-gray-800` |
| 274 | `border-[#e0dcd4] text-[#6b7c6b] hover:border-[#4a7c59] hover:text-[#4a7c59]` | `border-gray-300 text-gray-500 hover:border-gray-900 hover:text-gray-900` |
| 295 | `border-[#e0dcd4] focus:border-[#4a7c59]` | `border-gray-300 focus:border-gray-900` |
| 305 | 同 295 | 同 295 |
| 316 | 同 295 | 同 295 |
| 331 | `accent-[#4a7c59]` | `accent-gray-900` |
| 343 | `bg-[#4a7c59] text-white hover:bg-[#2d4a3a]` | `bg-gray-900 text-white hover:bg-gray-800` |

(10 处 hex 替换,但 table 列出 11 个 className 块,有的 className 里有 2 个 hex。)

- [ ] **Step 2: 验证 grep 残留**

```bash
grep -nE '#4a7c59|#e0dcd4|#8fbc8f|#f0f7f1|#2d4a3a|#6b7c6b' src/components/ModelConfigModal.tsx
```

预期: 0 匹配。

- [ ] **Step 3: 验证 tsc 严格模式**

```bash
cd frontend && npx tsc --noEmit 2>&1 | tail -20
```

预期: 0 error。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/components/ModelConfigModal.tsx
git commit -m "feat(desktop): ModelConfigModal 灰阶化 — 10 处硬编码 hex 改 Tailwind gray-*"
```

---

## Task 8: `WechatPluginModal.tsx` — 12 处硬编码 hex 替换

**Files:**
- Modify: `frontend/src/components/WechatPluginModal.tsx`

- [ ] **Step 1: 逐处 Edit**

按 spec §5.2 表替换。**保留 error 状态色**(`#ffebee` / `#c62828` / `#ffebee` 背景 / `#c62828` 文字),其它全部灰阶化:

| 行 | 旧 | 新 |
|----|----|----|
| 169 | `from-[#4a7c59] to-[#2d4a3a]` | `from-gray-900 to-gray-800` |
| 184 | `bg-[#f0f2ed]` | `bg-gray-100` |
| 187 | `text-[#5a6b52]` | `text-gray-500` |
| 193 | `bg-[#f0f2ed]` | `bg-gray-100` |
| 196 | `text-[#5a6b52]` | `text-gray-500` |
| 201 | `bg-[#4a7c59] hover:bg-[#3d6a4a]` | `bg-gray-900 hover:bg-gray-800` |
| 210 | `text-[#5a6b52]` | `text-gray-500` |
| 214 | `text-[#8a9a7a]` | `text-gray-400` |
| 215 | `bg-[#4a7c59]` | `bg-gray-900` |
| 223 | `bg-[#e8f5e9]` | `bg-gray-100`(已绑定 icon 容器) |
| 226 | `text-[#2d4a3a]` | `text-gray-900` |
| 228 | `text-[#8a9a7a]` | `text-gray-400` |
| 232 | `text-[#5a6b52]` | `text-gray-500` |
| 238 | `bg-[#4a7c59] hover:bg-[#3d6a4a]` | `bg-gray-900 hover:bg-gray-800` |
| 244 | `text-[#5a6b52] hover:text-[#2d4a3a]` | `text-gray-500 hover:text-gray-900` |
| 254 | `bg-[#ffebee]` | **保留**(error icon 背景) |
| 257 | `text-[#c62828]` | **保留**(error 文字) |
| 258 | `text-[#666]` | `text-gray-500` |
| 261 | `bg-[#4a7c59] hover:bg-[#3d6a4a]` | `bg-gray-900 hover:bg-gray-800` |

- [ ] **Step 2: 验证 grep 残留**

```bash
grep -nE '#4a7c59|#5a6b52|#8a9a7a|#3d6a4a|#2d4a3a|#f0f2ed|#e8f5e9|#666' src/components/WechatPluginModal.tsx
```

预期: 0 匹配(error 状态的 `#ffebee` / `#c62828` 仍在)。

- [ ] **Step 3: 验证 tsc 严格模式**

```bash
cd frontend && npx tsc --noEmit 2>&1 | tail -10
```

预期: 0 error。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/components/WechatPluginModal.tsx
git commit -m "feat(desktop): WechatPluginModal 灰阶化 — 12 处 hex 改 Tailwind gray-*,error 色保留"
```

---

## Task 9: 改锁测试 `tokens-dark.test.ts` — 锁"无彩色"

**Files:**
- Modify: `frontend/src/styles/__tests__/tokens-dark.test.ts`

- [ ] **Step 1: 替换 "森林绿族" 断言**

找到 `it('--forest 在 dark 模式必须为森林绿族...', ...)` 块(行 124-136),整段替换为:

```ts
  it('dark 模式所有 token 饱和度 ≤ 0.10(锁防彩色回归)', () => {
    const tokens = [
      'ink', 'ink-2', 'ink-3',
      'paper', 'paper-2', 'paper-3',
      'line', 'line-2',
      'accent', 'accent-soft',
      'wechat',
      'sidebar-bg', 'sidebar-bg-2',
      'sidebar-fg', 'sidebar-fg-2', 'sidebar-fg-3',
    ];
    for (const name of tokens) {
      const { r, g, b } = hexToRgb(getToken(block, name));
      const max = Math.max(r, g, b);
      const min = Math.min(r, g, b);
      const sat = max === 0 ? 0 : (max - min) / max;
      expect(sat, `dark --${name} 饱和度 ${sat.toFixed(2)} 过高(> 0.10)`).toBeLessThanOrEqual(0.10);
    }
  });
```

- [ ] **Step 2: 加 light 模式同样断言(若原文件无)**

在 `it('dark 模式 ...')` 后加:

```ts
  it('light 模式所有 token 饱和度 ≤ 0.10(锁防彩色回归)', () => {
    const lightBlock = document.createElement('div');
    lightBlock.style.cssText = '';
    document.body.appendChild(lightBlock);
    const tokens = [
      'ink', 'ink-2', 'ink-3',
      'paper', 'paper-2', 'paper-3',
      'line', 'line-2',
      'accent', 'accent-soft',
      'wechat',
      'sidebar-bg', 'sidebar-bg-2',
      'sidebar-fg', 'sidebar-fg-2', 'sidebar-fg-3',
    ];
    for (const name of tokens) {
      const { r, g, b } = hexToRgb(getToken(lightBlock, name));
      const max = Math.max(r, g, b);
      const min = Math.min(r, g, b);
      const sat = max === 0 ? 0 : (max - min) / max;
      expect(sat, `light --${name} 饱和度 ${sat.toFixed(2)} 过高(> 0.10)`).toBeLessThanOrEqual(0.10);
    }
    document.body.removeChild(lightBlock);
  });
```

(具体如何 getToken light,看原文件 getToken 实现 — 如不支持 light 块,改用 querySelector `:root` 直接读 `getComputedStyle(document.documentElement).getPropertyValue('--ink')` 替代。)

- [ ] **Step 3: 验证测试通过**

```bash
cd frontend && npx vitest run src/styles/__tests__/tokens-dark.test.ts 2>&1 | tail -30
```

预期: PASS(全部 token 饱和度都 ≤ 0.10)。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/styles/__tests__/tokens-dark.test.ts
git commit -m "test(desktop): 锁测试改锁无彩色 — 15 个 token 饱和度 ≤ 0.10"
```

---

## Task 10: 改 4 个 desktop 锁测试 — 按新色板更新 hex 断言

**Files:**
- Modify:
  - `frontend/src/components/desktop/styles/__tests__/focus-ring.test.ts`
  - `frontend/src/components/desktop/styles/__tests__/product-polish.test.ts`
  - `frontend/src/components/desktop/styles/__tests__/a11y-polish.test.ts`
  - `frontend/src/components/desktop/styles/__tests__/shell-sidebar-brand.test.ts`

- [ ] **Step 1: 跑当前测试,看哪些断言失败**

```bash
cd frontend && npx vitest run src/components/desktop/styles/__tests__/ 2>&1 | tail -40
```

预期: 看到具体哪些 `expected #xxx to be #yyy` 失败。

- [ ] **Step 2: 逐文件改 hex 断言**

把失败的 hex 期望值改为新值:

| 旧期望 hex | 新期望 hex | 用途 |
|----------|----------|------|
| `#2d6a4f` | `#1f1f1f` | --forest / --accent light |
| `#5fa37f` | `#ededed` | --forest / --accent dark |
| `#1b4332` | `#4a4a4a` | --forest-2 light |
| `#7fbf9b` | `#a8a8a8` | --forest-2 dark |
| `#d8e2dc` | `#ededed` | --forest-soft light |
| `#23442f` | `#2c2c2c` | --forest-soft dark |
| `#5e8f9e` | (无 — sage 已删,断言整段删) |
| `#d6923b` | (无 — tea 已删,断言整段删) |
| `#07c160` | `#4a4a4a` | --wechat light |
| `#07c160` | `#b5b5b5` | --wechat dark |

- [ ] **Step 3: 跑测试验证**

```bash
cd frontend && npx vitest run src/components/desktop/styles/__tests__/ 2>&1 | tail -10
```

预期: PASS(全部 4 文件测试过)。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/components/desktop/styles/__tests__/
git commit -m "test(desktop): 4 个锁测试按新色板更新 hex 期望"
```

---

## Task 11: 全栈验证 — lint / typecheck / vitest / build

- [ ] **Step 1: ruff / eslint**

```bash
cd frontend && npm run lint 2>&1 | tail -20
```

预期: 0 error。

- [ ] **Step 2: TypeScript 严格模式**

```bash
cd frontend && npx tsc --noEmit 2>&1 | tail -10
```

预期: 0 error。

- [ ] **Step 3: 跑全量 vitest**

```bash
cd frontend && npm test 2>&1 | tail -30
```

预期: PASS(全部测试过,包括 5 个锁测试)。

- [ ] **Step 4: Vite 构建**

```bash
cd frontend && npm run build 2>&1 | tail -10
```

预期: 编译成功,产物在 `frontend/dist/`。

- [ ] **Step 5: grep 全面残留扫描**

```bash
cd /Users/yxb/projects/nexus/frontend
grep -rnE 'var\(--forest\)|var\(--sage\)|var\(--tea\)|var\(--muted\)|var\(--faint\)|var\(--paper-soft\)|var\(--paper-tint\)|var\(--canvas\)' src/ 2>/dev/null
```

预期: 0 匹配(只能出现注释中,但其实也已清空)。

---

## Task 12: 桌面端手测 — 深浅切换 + 微信徽标

- [ ] **Step 1: 启动 dev server**

```bash
cd frontend && npm run dev
```

后台运行,`http://localhost:30077/`。

- [ ] **Step 2: light 模式视觉清单**

- [ ] 整窗白底,无任何彩色装饰(无森林绿 / 鼠尾草 / 茶叶 / 微信绿)
- [ ] 用户消息气泡:黑底白字(深色)
- [ ] 助手消息气泡:浅灰底,深字
- [ ] sidebar 微信图标:中灰(不是绿)
- [ ] inbox badge 数字:中灰底
- [ ] focus 框:2px 纯黑硬边
- [ ] 选中态 / 强调按钮:深灰底白字

- [ ] **Step 3: dark 模式视觉清单**

点 ThemeToggle 切换:

- [ ] 整窗近黑(`#1a1a1a`),无绿色调
- [ ] 用户消息气泡:浅灰底深字(反转)
- [ ] sidebar 微信图标:浅灰
- [ ] focus 框:2px 纯白硬边

- [ ] **Step 4: 切换无闪烁**

reload 页面,观察深浅切换瞬间:应该无 light → dark 闪烁(useDarkModeRoot MutationObserver 仍生效)。

- [ ] **Step 5: 提交 dev 验证记录**

```bash
git add docs/superpowers/progress.md
```

编辑 `docs/superpowers/progress.md`,追加:

```markdown
## 第十二轮 2026-07-17 — 灰阶主题重构(Claude Desktop 双色)

- 删 forest/sage/tea/moss/wood/cream/forest-strong 等品牌色
- 新增 ink/paper/line/accent 三档灰阶体系(light + dark)
- 5 个 CSS + 2 个 TSX + 1 个 index.css 全部灰阶化
- 5 个锁测试改断言(锁饱和度 ≤ 0.10)
- 微信绿 → 中灰(识别色降饱和)
- 状态色(error/success/warn/info)保留
- CHANGELOG 待补
```

```bash
git commit -m "docs(progress): 第十二轮灰阶主题完成"
```

---

## Task 13: CHANGELOG + 终 commit

- [ ] **Step 1: 编辑 CHANGELOG.md**

在顶部追加:

```markdown
## 第十二轮 (2026-07-17) — 灰阶主题重构

- 主题从"森林绿 + 鼠尾草 + 茶叶 + 微信绿"四色品牌调改为 Claude Desktop 双色灰阶
- 新增 `ink / paper / line / accent` 三档 token 体系,删 `forest / sage / tea / moss / wood / cream`
- 微信通道徽标灰阶化(识别色降饱和)
- Toast 状态色(info/success/warn/error)保留
- 5 个锁测试改断言,防彩色回归
```

- [ ] **Step 2: 跑全量验证(快速)**

```bash
cd frontend && npm run lint && npx tsc --noEmit && npm test -- --run 2>&1 | tail -10
```

预期: 全过。

- [ ] **Step 3: 提交**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): 第十二轮 灰阶主题重构 + 锁测试防彩色回归"
```

- [ ] **Step 4: 打印完成摘要**

```
✅ 第十二轮灰阶主题完成
- 5 个 CSS 文件 + 2 个 TSX + 1 个 index.css 灰阶化
- 5 个锁测试改断言
- 13 个 commit 提交
- 待 DMG 验证(可选)
```

---

## Self-Review Checklist(实施时确认)

- [ ] spec §1.1 范围文件全部覆盖(tasks 1-8 覆盖)
- [ ] spec §2.4 删除 token 全部替换(Task 1 + 后续 grep 验证)
- [ ] spec §3 Tailwind 调整(Task 2 覆盖)
- [ ] spec §4 组件 CSS 调整细则(Tasks 3-6 覆盖)
- [ ] spec §5 TSX 硬编码 hex(Tasks 7-8 覆盖)
- [ ] spec §6 锁测试更新(Tasks 9-10 覆盖)
- [ ] spec §8 验收(Task 11 覆盖)
- [ ] spec §10 实施顺序(Tasks 1-13 顺序匹配)
