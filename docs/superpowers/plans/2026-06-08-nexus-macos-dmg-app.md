# Nexus macOS DMG 应用实施计划

> 面向执行者：按阶段推进，每个阶段完成后运行对应验证。文档正文使用简体中文；命令、文件路径、接口名和技术专有名词保留原文。

> ⚠️ **[SUPERSEDED — 2026-07-01 标注]**：本计划基于 **Electron + PyInstaller onedir** 路径,2026-06 中止执行,已被 Tauri 2 migration 计划全面替代(见 [[2026-06-26-tauri-migration.md]])。历史快照保留,仅供追溯 — **请勿按本计划执行**。当前 DMG 构建命令见仓库根 `scripts/build_dmg.sh`(走 `cargo tauri build`)。

## 目标

把 Nexus 做成一个 macOS 个人 AI 助手应用。用户从 GitHub Release 下载一个 DMG，拖入 Applications 后即可使用，不需要理解 Python、Node、后端端口、虚拟环境或命令行。

应用定位不是开发者控制台，而是“用户把任务交给 Nexus，Nexus 在底层自动完成”的个人助理。微信能力作为“微信通道”，用于把微信消息接入统一任务流。

## 产品原则

- 用户只需要在聊天窗口发起任务指令。
- 主界面只显示任务状态、执行过程中的关键反馈和最终结果。
- 会话压缩、记忆机制、路由、后端进程、配置文件等底层能力默认对用户无感。
- 微信是通道，不是另一个独立助手；微信来源任务进入统一最近任务列表。
- 模型配置支持任意兼容模型，但入口要简单，默认只展示常用字段。
- 设置页只放模型、数据隐私和高级入口，不重复展示微信通道。

## 技术路线

- 桌面壳：Electron + TypeScript。
- 前端：继续使用 React + TypeScript + Vite。
- 后端：继续使用 FastAPI，桌面版由 Electron 启动和管理。
- 后端运行时：开发期使用项目 `.venv`；发布期打包为应用内置可执行文件。
- 安装包：使用 `electron-builder` 生成 macOS `.dmg`。
- 发布：GitHub Actions 在 macOS runner 上构建并上传到 GitHub Release。

## 信息架构

主界面采用固定左栏 + 主工作区：

- 左栏：Nexus、个人 AI 助手、新任务、最近任务、微信通道状态、设置。
- 主区：当前任务、任务状态、消息与结果、底部任务输入框。
- 微信通道页：绑定状态、扫码入口、刷新二维码、通道运行状态。
- 设置页：模型配置、数据与隐私、高级设置。

不要恢复旧的三栏后台布局，不要展示重复的状态卡片，也不要把普通用户不需要理解的技术状态放在首屏。

## 视觉方向

使用 `docs/prototypes/nexus-handdrawn-assistant-ui-v2.html` 作为唯一视觉参考。

实现时保持以下方向：

- 暖色纸感背景。
- 深绿固定侧栏。
- 手绘感线条和柔和层次。
- 页面留白充足，重点突出任务输入和结果反馈。
- 微信绿色只作为通道状态点缀。
- 不使用后台管理系统式卡片堆叠。

侧栏里的“新任务”不使用白色块，应与左栏整体融合，使用绿色半透明或当前选中态样式。

## 阶段一：桌面壳与后端生命周期

涉及文件：

- `desktop/src/main.ts`
- `desktop/src/preload.ts`
- `desktop/src/backend.ts`
- `desktop/src/paths.ts`
- `desktop/package.json`
- 根目录 `package.json`

工作内容：

- 创建 Electron 主窗口。
- 启动本地 FastAPI 后端。
- 健康检查通过后加载前端。
- 应用退出时清理后端进程。
- 开发期从项目 `.venv` 启动后端。
- 为发布期内置后端资源预留路径逻辑。

验证命令：

```bash
npm run desktop:build
npm run desktop:test
```

## 阶段二：前端个人助理界面

涉及文件：

- `frontend/src/components/desktop/DesktopShell.tsx`
- `frontend/src/components/desktop/ChatView.tsx`
- `frontend/src/components/desktop/Sidebar.tsx`
- `frontend/src/styles/desktop.css`
- `frontend/src/App.tsx`

工作内容：

- 清理旧三栏 UI。
- 保留固定左栏和单一主工作区。
- 统一旧微信相关命名为“微信通道”。
- 把任务状态展示为用户能理解的短句。
- 让回复内容、思考过程、执行状态层级清楚，避免回复不可见。
- 输入区始终固定在主区底部。

验证命令：

```bash
npm run build --prefix frontend
```

视觉验收：

- 页面不是三栏。
- 左栏固定，不随主内容滚动。
- “新任务”不是白色突兀块。
- 首屏没有重复的微信、模型、本地状态卡片。
- 用户一眼能知道“在这里把任务交给 Nexus”。

## 阶段三：模型配置与微信通道

涉及文件：

- `frontend/src/components/desktop/SettingsView.tsx`
- `frontend/src/components/desktop/WechatChannelView.tsx`
- `frontend/src/api.ts`
- `nexus/backend/api/*`
- `nexus/backend/channels/wechat.py`

工作内容：

- 设置页只展示模型配置、连接测试、数据与隐私、高级入口。
- 微信通道独立成页，不在设置里重复。
- 微信绑定后不展示独立微信会话列表，只展示通道状态。
- 微信来源任务进入统一最近任务，并带来源标记。
- API 密钥默认使用密码输入框，日志中不得输出密钥。

验证重点：

- 未绑定、等待扫码、已绑定、二维码过期、断开等状态都有清晰提示。
- 用户不会看到“插件管理”等旧概念。

## 阶段四：发布模式后端打包

涉及文件：

- `scripts/build_backend_app.sh`
- `desktop/src/paths.ts`
- `desktop/src/backend.ts`
- `pyproject.toml`

工作内容：

- 使用项目 `.venv` 安装和运行后端打包工具。
- 把后端打包为发布期可执行文件。
- 将后端可执行文件放入 Electron 应用资源目录。
- Electron 发布模式从资源目录启动后端。

验证命令：

```bash
./scripts/build_backend_app.sh
npm run desktop:build
```

## 阶段五：DMG 与 GitHub Release

涉及文件：

- `desktop/electron-builder.json`
- `.github/workflows/macos-dmg.yml`
- 根目录 `package.json`

工作内容：

- 前端执行 `npm run build --prefix frontend`。
- 桌面壳执行 `npm run desktop:build`。
- 后端执行 `./scripts/build_backend_app.sh`。
- Electron 生成 `.dmg`。
- GitHub Actions 把 `.dmg` 上传到 GitHub Release。

验证命令：

```bash
npm run desktop:pack
```

用户最终只需要下载一个 `.dmg`，不需要关心构建流程。

## 最终验收

- 干净 macOS 环境中可安装并打开 Nexus。
- 用户不需要安装 Python 或 Node。
- 首次启动可配置模型并测试连接。
- 主界面可发起任务并看到状态与结果。
- 回复内容和思考过程视觉层级清楚。
- 微信通道可进入扫码绑定流程。
- 关闭应用后后端进程被清理。
- 重新打开后配置和最近任务可恢复。
- GitHub Release 中能直接下载 `.dmg`。

## 当前非目标

- Windows/Linux 安装包。
- 自动更新。
- 完整商业代码签名和 notarization 流程。
- 插件市场。
- 面向开发者的 MCP 可视化管理后台。
- 原生 Swift 重写。
- 完整离线模型。
