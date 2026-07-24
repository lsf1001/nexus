# Nexus 对齐 Claude Desktop 总览 SPEC

> **目标**:把 Nexus 从"通用 AI Gateway"演进到"个人助理桌面客户端",能力对标 Claude Desktop,但保留 Nexus 现有差异点(微信通道、DMG 分发、用户数据唯一在 `~/.nexus/`)。
>
> **基线文档**:
> - [`docs/designs/frontend.md`](../../designs/frontend.md) — 唯一权威前端设计文档
> - [`docs/superpowers/specs/2026-07-20-nexus-claude-desktop-refactor-design.md`](2026-07-20-nexus-claude-desktop-refactor-design.md) — 已落地的三栏重构 SPEC
>
> **基线代码**:v1.5.4 `feat/e2e-v154-completion` 分支(`edd3ef2`)
>
> **状态**:草案 0.1(2026-07-23)

---

## 1. 背景与动机

### 1.1 现状(已对齐 13 项 + 部分对齐 3 项)

**已对齐(用户可见 + 后台能力)**:

| 能力 | 实现位置 | 备注 |
|------|---------|------|
| 会话侧栏 | `desktop/Sidebar.tsx` | 260px + 搜索 + 新对话 + 折叠 |
| 主对话流 | `ChatArea/index.tsx` + 14 子文件 | 流式 / thinking / 工具卡 |
| Artifacts 面板 | `Artifacts/ArtifactsPanel.tsx` | 三栏默认折叠,Code/Md/SVG/HTML 4 渲染器 |
| 设置(Provider/界面) | `desktop/PreferencesModal.tsx` | 抽屉式 |
| 模型切换 | `ChatArea/ModelSelector.tsx` + `desktop/ModelSwitcher.tsx` | chip + dropdown(#22 已接后端) |
| 记忆系统 | `desktop/MemoryPanel.tsx` + AGENTS.md | ⌘K 调出,跨会话持久 |
| 工具调用卡片 | `ChatArea/ToolCallCard.tsx` | fold/expand + 联动 Artifacts |
| 快捷键 | `useGlobalShortcuts` | ⌘N/K//\\/= /- /0 + Esc |
| 主题(浅/深) | `desktop/ThemeToggle.tsx` | data-theme 双色 |
| 字号缩放 | `uiPrefs.fontScale` + PreferencesModal | 0.875/1/1.25 + Mac 快捷键 |
| 星标会话 | `uiPrefs.starredIds` + Sidebar | 排前 |
| 重命名会话 | `Sidebar.tsx` onRename | 双击/按钮 |
| 删除会话 | `Sidebar.tsx` deleteTimerRef | 软删除 + 二次确认 |

**部分对齐(后台有 / 前端不可见)**:

| 能力 | 后端状态 | 前端缺什么 |
|------|---------|-----------|
| Skills | `~/.nexus/skills/` 目录扫读 | 无 UI 面板、无列表/描述/调用统计 |
| MCP | `nexus/backend/plugins/mcp/` 默认启用 | 无前端开关/列表 |
| 历史搜索 | 侧栏搜标题 | 无消息级全文搜索 |

**超出 Nexus 范围(产品差异化)**:

- 微信通道(单独通道,不算缺口)

### 1.2 GAP 清单(9 项,按用户感知重要性排序)

1. **🔴 Projects 概念** — Claude Desktop 按目录隔离上下文(AGENTS.md / Skills / MCP / 工具集);Nexus 只有平坦会话列表,无法"切换项目"换上下文根。
2. **🔴 文件上传 / 附件** — Composer 无 input/drop,只有 LLM 写出本地路径再 pathLinkify 反向贴图。
3. **🟡 草稿持久化** — 关闭窗口/切会话后未发送内容丢失(注:`73cdec5` 已加 localStorage 持久化,需确认范围是否已闭合)。
4. **🟡 Skill / MCP UI 面板** — 后端已注册可调用,前端用户看不到列表/描述/调用情况,无法 on/off。
5. **🟡 消息级搜索** — 只能搜会话标题,无法在历史会话内 grep 关键词。
6. **🟢 会话导出 / 分享** — 不能导出 Markdown / 分享链接。
7. **🟢 Voice 输入** — Mac 上无麦克风转文字入口(系统权限门槛)。
8. **🟢 Plugin / Marketplace** — 无第三方插件通路(**本 SPEC 仅做本地扫描**,不做市场)。
9. **🟢 多模态图片输入** — 不能直接上传截图让 LLM 看(文件上传子集)。

### 1.3 目标

按"对齐 Claude Desktop 个人助理桌面客户端"产品目标,**多轮交付**,每轮独立 SPEC + plan + 执行,每轮结束有可交付成果(commit / 文档)。**第一轮必须先交付 Projects**,因为它是后续 6 项的上下文容器。

---

## 2. 非目标(本总览 SPEC)

- ❌ **Plugin / Marketplace 第三方生态** — 不做供应/需求/分发/签名/审批。本 SPEC 仅包含"本地 Plugins 目录扫描"作为轻量版。
- ❌ **跨平台桌面** — Nexus 当前仅 macOS DMG;Windows / Linux 不在本期。
- ❌ **云端同步 / 账户体系** — 保持"用户数据唯一在 `~/.nexus/`"原则,个人助理形态。
- ❌ **真多模态 Vision 模型集成** — 仅做"文件上传把图片塞进 LLM 输入",选型留给用户配置。
- ❌ **跨项目协同 / 分享** — 单用户单设备。

---

## 3. 范围(5 轮交付)

### 第 1 轮(本期):Projects 骨架 + per-project Skills/MCP

**WHY 在前**:Projects 是其它 6 项的上下文容器。先把"上下文根"建好,后续轮再加功能(文件上传 / 搜索 / 导出)时,只需考虑"per-project 还是全局"两个版本。

**交付**:
- Project 目录模型(`projects` 表 + sessions.project_id 外键)
- 默认 Project 自动迁移(无破坏)
- Sidebar 顶部 Project 切换 dropdown
- 新建 Project 表单
- Skills/MCP per-project 隔离(后端扫目录 / 前端面板)

详见 §4。

### 第 2 轮:文件上传 / 附件 + 草稿持久化补全

- Composer 拖拽 + 文件选择 + paste 图片
- 后端 multipart 上传 → `~/.nexus/uploads/`
- 多模态图片自动 inline 进 LLM 输入
- 草稿 UX 补全(草稿列表 / 冲突提示 / per-project)

### 第 3 轮:消息级搜索 + 会话导出/分享

- SQLite FTS5 索引(messages.content)
- Sidebar 搜索扩展(标题 + 消息正文)
- ⌘+F 全局搜索
- 会话导出 Markdown 文件
- 分享链接(后端临时 endpoint + token)

### 第 4 轮:Voice 输入 + 多模态图片

- macOS 系统麦克风权限(Info.plist + Tauri 2 permission)
- Whisper / 云端 ASR 切换
- Voice 与多模态共用上传通道

### 第 5 轮:本地 Plugins 目录扫描 UI

- 后端扫 `~/.nexus/plugins/` 读 manifest
- PreferencesModal 加 Plugins tab,只读列表(无安装)
- Skills/MCP 与 Plugins 统一"扩展"概念

---

## 4. 第 1 轮详细 SPEC(本期交付)

### 4.1 数据模型

**新表 `projects`**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT PRIMARY KEY | UUID,启动时生成 |
| `name` | TEXT NOT NULL UNIQUE | 用户可见名(slug 校验:`[a-z0-9-_]{1,32}`) |
| `display_name` | TEXT | UI 友好名 |
| `path` | TEXT NOT NULL UNIQUE | 绝对路径 `~/Nexus/projects/<name>/` |
| `description` | TEXT | 用户填 |
| `created_at` | INTEGER | epoch ms |
| `updated_at` | INTEGER | epoch ms |

**改 `sessions` 表**:

- 加 `project_id TEXT REFERENCES projects(id) ON DELETE RESTRICT` 列
- 现有 sessions 在启动迁移时全部设为默认 project
- `db.py` 走 `_ensure_column()` 自动迁移,**禁止**手工 ALTER

### 4.2 默认 Project 自动迁移(无破坏)

**首次启动 / 现有用户升级时**:

1. 后端启动 → `db.py` 检测 `projects` 表空 → 自动插入默认 project:
   - `id = "default"`,`name = "default"`,`display_name = "默认项目"`,`path = ~/Nexus/projects/default/`
2. 文件系统:
   - 创建 `~/Nexus/projects/default/`
   - 创建 `~/Nexus/projects/default/AGENTS.md` —— 如果 `~/.nexus/AGENTS.md` 存在,**拷**(不是软链,避免用户编辑原文件影响默认 project 上下文)
   - 创建 `~/Nexus/projects/default/skills/` 软链接 → `~/.nexus/skills/`(向后兼容)
   - 创建 `~/Nexus/projects/default/mcp.json` 默认配置(空 enabled servers)
3. 数据库:
   - 所有 sessions 的 `project_id = 'default'`
   - 启动日志写 `migrated N sessions to default project`

**新建 Project 时**:

1. 表单输入:name + display_name + description
2. 后端 `POST /api/projects` → 校验 name 唯一 + slug 合法
3. 创建目录 + 初始化 AGENTS.md(空模板) + skills/ 空目录 + mcp.json 默认
4. 返回新 project

### 4.3 Sidebar UX(第 1 轮"够用"标准)

- 顶部加 Project dropdown(在 Sidebar 标题区下方),显示 `display_name`,点开列表所有项目 + "+ 新建项目" 项
- 切换 Project → `store.activeProjectId = id` + 后端 `GET /api/sessions?project_id=...` 重载 sessions
- 新建 Project 表单:drawer 弹出,3 字段(name / display_name / description),提交后立即切换
- **不**做 per-project 侧栏分组(放进第 2 轮)
- **不**做项目图标 / 颜色(放进第 3 轮)

### 4.4 Skills per-project 隔离

**后端**:

- 新增 `list_skills(project_id: str) -> list[dict]`,扫 `~/Nexus/projects/<name>/skills/`
- 默认 project 走软链 `~/.nexus/skills/`
- 切换 project → 重新扫 + 重新注册到 agent
- 现有 `/api/skills` 加可选 query `?project_id=`,默认 = 当前 active project

**前端**:

- PreferencesModal 加 "Skills" tab(已有 `MemoryPanel` ⌘K 调出的不动,这是另一个 tab)
- 列出当前 project 的 skills + 来源路径 + 启用 toggle
- 切 project 后 tab 内容自动重载
- 调用统计:每次 ToolCallCard 调 skill 时记录到 store,Skills 面板显示"已调用 N 次"

### 4.5 MCP per-project 隔离

**后端**:

- 新增 `load_mcp_config(project_id: str) -> dict`,读 `~/Nexus/projects/<name>/mcp.json`
- 默认 project 走 `~/.nexus/mcp.json`(如存在)
- 切 project → 重启 MCP 连接 + reload tools
- `GET /api/mcp/tools` 加 `?project_id=`,默认 = 当前 active

**前端**:

- PreferencesModal 加 "MCP" tab,列出当前 project 的 servers + 启用 toggle
- 切 project 自动重载(切前 toast 提示"重连 MCP 中…")
- **风险**:MCP 切换必须热更新 agent(详见 §5)

### 4.6 Per-project 上下文注入

启动 agent 时,在 system prompt 顶部插入:

```
<project_context>
name: my-coding-project
path: /Users/yxb/projects/my-coding-project
AGENTS.md: <内容前 200 行>
skills: [list of available skill names]
mcp_servers: [list of enabled server names]
</project_context>
```

WHY:让 LLM 知道"我现在在哪个 project 上下文",自动应用对应 AGENTS.md 规则。

`build_project_context_prompt(project_id)` 函数:后端 `nexus/backend/prompts/project_context.py` 新文件。

### 4.7 前端 store 改造

**新 store slice** `frontend/src/store/slices/projects.ts`:

```ts
interface ProjectsSlice {
  projects: Project[];
  activeProjectId: string | null;
  loading: boolean;
  loadProjects: () => Promise<void>;
  setActiveProject: (id: string) => Promise<void>;  // 异步,后端重载 sessions + skills + mcp
  createProject: (input: CreateProjectInput) => Promise<Project>;
}
```

**接入**:

- `desktop/Sidebar.tsx` 顶部加 ProjectDropdown
- `desktop/DesktopShell.tsx` 启动时 `loadProjects()` 一次
- `store/index.ts` partialize 加 `activeProjectId`(用户偏好持久化)

---

## 5. 风险点与对策

### 5.1 数据迁移不能破坏现有会话

- 默认 project 创建用 **upsert**(已存在跳过),启动幂等
- sessions.project_id 设置用 **单条 UPDATE 事务**,失败回滚
- AGENTS.md 拷贝用 `shutil.copy2` 保留原 mtime,源文件不动
- 启动日志明示"migrated N sessions to default project",失败抛 RuntimeError 阻止后端启动

### 5.2 MCP 切换必须热更新 agent

- 切 project → 后端先 `await mcp.disconnect_all()`,再 `load_mcp_config(new)`,最后 `connect_all(new)`
- 任一步失败 → 保留旧 MCP 配置 + toast.error,UI 不变
- agent 重建在 MCP 重连后(同样用 `run_in_executor`,见 `model_config.py:227`)

### 5.3 Skills 双扫路径防重复

- 默认 project 的 `~/Nexus/projects/default/skills/` 是 `~/.nexus/skills/` 的软链,后端扫的是软链展开后的内容
- 用 `pathlib.Path.resolve()` 去重 —— 同一 inode 的不同路径算一个 skill
- 测试覆盖:`~/.nexus/skills/foo` 和 `~/Nexus/projects/default/skills/foo` 解析到同一路径时,API 返回 1 条而非 2 条

### 5.4 Project 切换时的 UX 一致性

- 切 project → store 重置:`currentMessages`, `currentSessionId`, `currentArtifacts` 全部清空(避免上一个 project 的上下文污染)
- Composer 草稿保留(per-session 草稿不变)
- 重载完 sessions 后,如果新 project 没有任何会话 → 显示"新建第一个会话"空态

### 5.5 name slug 校验

- 用户输入必须匹配 `^[a-z0-9][a-z0-9-_]{0,31}$`
- 不合法 → 表单红字提示 + 阻止提交
- 重复 → 后端 409,前端 toast

---

## 6. 不在本期范围(留到后续轮)

- ❌ **Project 图标 / 颜色 / 排序** —— 第 3 轮
- ❌ **per-project 侧栏分组(按 project 折叠 sessions)** —— 第 2 轮
- ❌ **Project 切换动画** —— 后续 UX 打磨轮
- ❌ **Skills 调用历史跨 project 聚合** —— 第 5 轮
- ❌ **MCP 工具调用可视化(哪个 tool 被哪个 project 调过)** —— 第 5 轮
- ❌ **详尽 UI 视觉打磨** —— 第 1 轮只求"够用"

---

## 7. SPEC 自检

- [x] **Placeholder 扫描**:无 TBD / TODO / "后续实现" 模糊表述
- [x] **类型一致**:store interface 与后端 Pydantic schema 字段名一致(`name` / `display_name` / `path` / `description`)
- [x] **范围聚焦**:第 1 轮可独立交付,不依赖后续轮
- [x] **歧义检查**:默认 project 的 skills 软链 vs 拷贝已明确(软链)
- [x] **风险覆盖**:5 项风险点全部有对策

---

## 8. 签字 / 决策记录

| 决策点 | 选择 | WHY |
|--------|------|-----|
| Project 模型 | 目录(贴近 Claude Desktop) | 用户对话确认 |
| Plugins 范围 | 仅本地目录扫描 | 不做市场 |
| 交付节奏 | 多轮,每轮可 stop | 用户对话确认 |
| 默认 Project 迁移策略 | 自动 + 无破坏 | 用户对话确认 |
| 第 1 轮范围 | Project + Skills/MCP 一起 | 用户对话确认 |
| 默认 project skills 路径 | 软链 | 向后兼容 |
| 默认 project AGENTS.md | 拷(非软链) | 用户编辑原文件不影响默认上下文 |
| sessions.project_id 默认值 | 'default'(非 null) | 所有现有会话归属确定 |

---

## 9. 后续流程

1. 用户审批本 SPEC
2. 写第 1 轮实施 plan:`docs/superpowers/plans/2026-07-23-project-skeleton-impl.md`(使用 writing-plans 技能)
3. 用户审批 plan
4. 用 subagent-driven-development 串行执行每 task,两阶段 review(spec compliance + code quality)
5. 验证通过 → 推 `feat/e2e-v154-completion`(本地 push,不动 main,不打 DMG)
6. 启动第 2 轮 SPEC(文件上传 + 草稿)