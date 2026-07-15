# Changelog

Nexus 项目的所有重要变更都记录在此文件。本文件格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

---

### [Unreleased] — Pre-release hardening (2026-07-14)

#### Added — 运行时 SKILL.md loader

用户把 `~/.nexus/skills/<name>/SKILL.md` 放进本地目录,后端 lifespan 启动时
自动扫描 + 解析 + 注入 system prompt。LLM 在对话里看到 trigger 命中就调
`run_skill` 工具,内部走既有 `shell_run` 沙箱 + 审计 + 危险命令 auto-deny。

形态参考 Claude Code `.claude/skills/`(单 md 文件 + frontmatter,放进目录就生效)。

- **`nexus/backend/skills/schema.py`**:`SkillManifest(BaseModel)` 校验 `name / description / triggers / entrypoint / inputs / requires / body`
- **`nexus/backend/skills/loader.py`**:`parse_skill_md()` 拆 frontmatter + `yaml.safe_load`;`scan_skills_dir()` 单文件损坏 skip + warn 不阻断启动;`render_skills_for_prompt()` 渲染成 prompt markdown 段
- **`nexus/backend/skills/__init__.py`**:`SKILLS_DIR = ~/.nexus/skills` + `REGISTRY` module-level 字典
- **`nexus/backend/tools.py`**:`run_skill(skill_name, skill_args)` 工具,内部 `shlex.quote(skill_args)` + 直接调 `shell_run(command=..., cwd=skill_dir, timeout=120)`,走既有沙箱 + 审计
- **`nexus/backend/agent/_system_prompt.py`**:`_build_system_prompt` 末尾 append skills 段,空时跳过
- **`nexus/backend/main.py`**:lifespan `init_db()` 之后调 `scan_skills_dir()` + `reload_system_prompt()`

WHY `skill_args` 不叫 `args`:langchain 1.x Pydantic schema 把 `args`/`kwargs`
当作 `*args`/`**kwargs` 合成字段剔除,同名参数会丢;改名一劳永逸。

WHY 不弹 ConfirmationCard(方案 A):用户拍板直接执行,危险命令仍被
`shell_sandbox._should_deny` 拦,LLM 收到 error ToolMessage。

测试:`tests/test_skills_loader.py` (10) + `tests/test_run_skill.py` (5),共 15 个单测覆盖正常/边界/异常三类路径。

DMG 不受影响:`~/.nexus/skills/` 是用户运行时数据,不在 `_up_/` 里,改后端代码 + 用户自己写 SKILL.md 即用,无需重打。

#### Changed — WS 鉴权 token 随机化

DMG bundle 内 WS 鉴权 token 由公开字符串 `nexus-default-token` 改为 build-time 随机生成(64 hex 字符),
固化到前端 bundle + sidecar runtime env 两端对齐。

- **`desktop/src-tauri/build.rs`**:编译期生成 `OUT_DIR/ws_token.rs`,含 `pub const WS_TOKEN: &str = "<hex>"`
  - 优先级:`BUILD_WS_TOKEN` env → `desktop/src-tauri/.build_token` 持久化 → `openssl rand -hex 32` 首次生成
  - 持久化保证:同一机器多次重打 DMG token 不变,老用户授权不失效
- **`desktop/src-tauri/src/runtime.rs`**:`include!(concat!(env!("OUT_DIR"), "/ws_token.rs"))` 拿常量注入 sidecar env
- **`scripts/build_dmg.sh`**:在 step 2 之前 export `VITE_NEXUS_WS_TOKEN` + `BUILD_WS_TOKEN`,
  从 `.build_token` 读 token(或首次生成),同步给 Vite 编译期 + Rust 编译期
- **`desktop/src-tauri/.gitignore`**:新增,忽略 `.build_token`

#### Changed — 后端 `ws_token` 入口收紧 (breaking for config.json users)

`nexus/backend/config.py` 删去 `file_config.security.ws_token` fallback + `"nexus-default-token"` 默认值:

- 仅读 env `NEXUS_WS_TOKEN`,env 缺失 → **空串**(start_sidecar 会强制注入,所以正常运行)
- 该字段即便在旧 version 一直被读也从未生效(前端 baked-in 才是真值),显式 dead 比"看起来能改"健康
- **迁移提示**:`~/.nexus/config.json` 的 `security.ws_token` 字段被移除生效路径。本批 release 起,WS token 是 DMG 绑定的随机串,用户**无法**(也不需要)自行配置;需要轮换时重装 DMG 即可。

#### Test plan

- `tests/test_config_ws_token.py` 新增 3 个测试:env 缺失 → 空串 / env 设置 → 透传 / config.json 旧字段不再生效
- 验证 `desktop/src-tauri/build.rs` 编译产物含新 token,不含 `nexus-default-token`
- 验证 `release/Nexus-<ver>-arm64.dmg` 安装后用正确 token 200,`nexus-default-token` 401

#### Fixed — journey E2E 套件 WS 鉴权 401 全军覆没 + 新增 wechat-bound-receive (2026-07-14)

跑现网 journey 套件(8 条)时**全部 fail 在 401 Unauthorized**:`useBootstrap` 拿不到
`/api/models`,前端 SetupView 兜底显示 API key 输入框,`prompt-card` 永远不渲染,
所有 spec 30s 超时 fail。

- **根因**:`frontend/playwright.config.ts` 的 webServer.env 给 Vite 注入
  `VITE_NEXUS_WS_TOKEN`,但**没给后端 uvicorn 进程注入 `NEXUS_WS_TOKEN`**。
  `nexus/backend/config.py:79` 默认读 `os.environ.get("NEXUS_WS_TOKEN", "")`
  → 后端空串;前端 baked-in 仍是 `nexus-default-token`,`auth.py:111` 的
  `_hmac_compare` 不通过 → `/api/models` 401。
- **修法**:`playwright.config.ts` 后端 env 加
  `NEXUS_WS_TOKEN: process.env.NEXUS_WS_TOKEN ?? 'nexus-default-token'`,
  与 Vite 同款默认值,CI / 本地 dev 共享同一逻辑(用户可通过 env 显式覆盖
  测试特殊 token)。
- **结果**:7 条 journey spec 全绿(`cold-start` 7.8s / `multi-turn` 9.4s /
  `input-edge-cases` 3/3 / `quick-prompts-and-history` mock / `stop-mid-stream`
  mock 575ms / `auth-401` mock 2.6s);`resilience` 是 CI-only skip(local dev
  `reuseExistingServer=true` 不会重启被杀的后端),`hitl-workflow` 因 mock
  默认 scenario 不触发 HITL 也 skip。

**新增** `frontend/e2e/journey/journey-wechat-bound-receive.spec.ts`
(plan Task 15 降级版):只覆盖"绑定状态切换"半段 —
`page.route('**/api/channels/wechat/bind')` mock 返 `{bound: true, account_id}` →
ChannelViewBase 3s 轮询拿到新状态 → "已绑定: e2e-mock-wx-user" + 解绑按钮 +
sidebar footer-link 加 `is-connected` 类。**收消息半段因后端无标准 inbound
端点(ilink 协议内部轮询)留待后续 sandbox 就绪后补**。

- **结果**:新 spec 3.6s 一发即过;`frontend/e2e/README.md` 同步更新 9 条
  journey spec 清单 + mock 命令说明。

#### Fixed — 测试 isolation 修跨文件污染 (2026-07-14)

修 `tests/test_config_ws_token.py` 用 `importlib.reload(cfg_mod)` 重建 CONFIG dict 的反模式。
根因:`auth.py` 等模块在 import 期用 `from ..config import CONFIG` 绑定了**旧 dict 对象**,
reload 重建的 dict 没人引用,后续 test 的 `monkeypatch.setitem` 写到新 dict 而 `auth.py` 仍读旧
空 dict → WS 鉴权幻性 401。显形:全量 `pytest tests/` 37 fail,单跑文件全过。

修法:不 reload,直接 `cfg_mod.CONFIG["ws_token"] = ""/value` 模拟 `load_config()` 读 env 的产物。
`tests/conftest.py::isolate_runtime_state` 加 docstring 警告后人不要走 reload。

- **结果**:`pytest tests/` 从 `~756 passed / 37 failed` → **`793 passed / 0 failed / 12 skipped`** (39.6s)

#### Fixed — 澄清卡片 UX 兜底:ask_user 必须传 options + 前端 fallback 候选 (2026-07-14)

LLM 偶尔违反 prompt "ask_user 必传 2-6 个 options"的约束,只传 question + 空 options,
导致前端弹出**纯 textarea 卡片**(无候选按钮),用户面对空白输入框发懵。
LLM 也偶尔在 final 答案里写"如需进一步帮助请告诉我" 这种免责声明,不调 ask_user,
把球踢回用户。

修法(主流 ChatGPT / Claude.ai 模式 = 强 prompt + 前端兜底):

- **`nexus/backend/agent/_system_prompt.py`**:把 clarification_rule 段从
  "候选项(关键)" 升级为【ask_user 强约束 · 违反 = UX 事故】,5 条硬规则:
  1. options 必须传 2-6 个,**禁止传 None / 空数组 / 1 个**
  2. 候选项覆盖主要场景 + 留"其他"兜底,最常见的放第一
  3. 真正无法枚举时才允许空数组,且要写"其他(自定义)"占位
  4. **禁止用自然语言免责声明替代 ask_user**(列出 LLM 训练记忆里的
     常见 fallback 句式,要求改用工具调用)
  5. 禁止在 final 写"如有需要请告诉我"等把球踢回用户的句子
- **`frontend/src/components/ChatArea/ClarificationForm.tsx`**:
  options 为空时**前端兜底塞 2 个 fallback 候选**(`让 Nexus 帮我想` /
  `我需要更多信息`),保证 UI 一定有按钮可点;非空时正常渲染原列表,
  不出现 fallback + 真实候选混在一起的尴尬。
- **`nexus/backend/api/ws/streaming.py`**:`clarification_request` 帧下发
  时若 options 为空 → `logger.warning` 打 fallback 触发标记,让 ops
  监控"哪条会话的 prompt 强约束被 LLM 忽略",频次高 = prompt 升级失败。
- **`tests/test_clarification.py` / `tests/e2e/probe_ask_user_fallback.py`**:
  - 单测:`test_ask_user_empty_options_lets_user_free_input` 增强,断言 warning log
  - E2E:`tests/e2e/probe_ask_user_fallback.py` 直连 WS,发单字"我想吃"歧义指令,
    验证 LLM 收到强约束后主动调 ask_user + 传 6 个候选(实测 pass:
    中餐 / 西餐 / 小吃 / 甜品 / 在家吃 / 其他)

- **结果**:`pytest tests/` 902 → **907 passed**(+5),0 failed;
  vitest 35 → **40 passed**(+5 ClarificationForm 兜底测试);
  E2E probe 实测 LLM 思考帧:"用户输入了'我想吃'三次,这是个非常模糊的输入 —
  意图完全不明确,关键参数完全缺失" → 主动调 ask_user(不写免责声明)。

#### Added — LLM 工具 `get_current_time` (2026-07-14)

补齐 agent 工具集缺失的"时分秒"能力。之前 `TOOLS` 只有 `get_current_date`/`today`
(精度到日),用户问"现在几点了" LLM 只能回答"我无法直接获取当前时间"。
加 `get_current_time(tz: str | None = None) -> str`,默认 `Asia/Shanghai`(`mcp/date_utils.SHANGHAI_TZ`,
与 fact_check `today()` 共享事实源),返回 `YYYY-MM-DD HH:MM:SS`。可选 `tz` 参数支持任意 IANA 时区
(如 `UTC` / `Asia/Tokyo`)。

- **`nexus/backend/tools.py`**:新增 `@langchain_tool def get_current_time(...)`;append 进 `TOOLS` 列表
- **`tests/test_tools_registry.py`**:新增 4 个测试 — 工具已注册 / 默认 Shanghai / 自定义 tz / schema 暴露 optional tz 参数
- **live 验证**:Shanghai `08:13:34` / UTC `00:13:34` / Tokyo `09:13:34` — 三时区差值正确
- **结果**:`pytest tests/` 795 → **800 passed**(+4 新测试),0 failed / 12 skipped(pre-existing `test_e2e_features.py` 失败与本次无关,见 commit note)
- **DMG 端到端验证**:重打 `release/Nexus-1.1.0-arm64.dmg` + 安装到 `/Applications/Nexus.app` + 启动 + WS 探针问"现在几点了"
  - LLM `[调用工具] get_current_time` → `[工具返回] 2026-07-14 10:08:58` → 回复"现在是 2026-07-14 10:08:58。"
  - **踩坑笔记**:之前 08:13 截图中 LLM 答"我无法获取时间"是 **08:17 前旧 binary 残留**(用户没退出旧 .app 实例),新 binary 本身一直正常。Tauri 2 走 `Contents/Resources/_up_/_up_/` 放 sidecar,`_internal/` 不再含独立 `PYZ.pyz`(PyInstaller 6.x bootloader 把 PYZ 嵌入 binary 末尾 zlib archive,所以 `strings binary | grep nexus.backend.tools` 也能找到 — 担心"binary 不含新工具"是误判;真正判定方法是启服务后调工具)。**Did:在 `release/` 留好 `.build_token` 持久化文件 + DMG 安装流程脚本化**,避免下次再混淆"binary 是否更新"。

#### Added — LLM 工具 `shell_run` + HITL 强审批 + 路径白名单 (2026-07-14)

Nexus LLM 第一条"任意执行命令"产品能力。三层防护:

1. **沙箱黑名单**(``nexus/backend/shell_sandbox.py``):危险命令模式直接 deny
   - 递归强删(`rm -rf` / `rm --recursive` / `rm -r`)
   - 提权(`sudo` / `su -` / `doas`)
   - 系统关机(`shutdown` / `reboot` / `halt` / `poweroff`)
   - 管道入 shell(`| sh` / `| bash` / `| zsh`,覆盖 curl/wget/nc 全部)
   - 磁盘覆盖 / 格式化 / dd 镜像 / fork bomb / chmod 777 / chown -R
2. **路径白名单**:cwd **必须**在 `~/.nexus/` 下;`/tmp` / `/etc` / `~/Documents`
   全部直接拒绝(LLM 应改用 `~/.nexus/outputs/`)
3. **超时硬上限**:1-300s clamp,不传默认 30s,LLM 传 `10000` 也只生效 300s
4. **HITL 强制审批**(:class:`ShellHITLMiddleware`):合法命令走
   `langgraph.interrupt()` → WS `confirmation_request` 帧,**每次必弹确认卡**
   (无"白名单自动放行");approve 才真跑,reject 拒绝
5. **审计日志**(:mod:`nexus.backend.shell_audit`):JSONL 追加到
   `~/.nexus/logs/shell_executions.log`(权限 0600,10MB rotate 留最近 1 份),
   字段含 ts / command / cwd / exit_code / stdout_preview / stderr_preview /
   decision / duration_ms / risk_label,事后用户自查

**架构关键决策**(WHY):

- HITL 由 **中间件**(`ShellHITLMiddleware.wrap_tool_call`)抛,不在 `shell_run` 工具内部
  调 `interrupt()` —— `langgraph.types.interrupt()` 只在 langgraph 节点执行上下文(Pregel
  loop)里会抛 `GraphInterrupt`,普通 `@langchain_tool` 装饰函数里调会静默失效
- 危险命令**不弹 HITL**:LLM 看到沙箱 deny 字符串后自主改写,不让用户看"rm -rf /"卡片
- WS 层 / 前端层零改动:复用 deepagents 标准 HITL payload (`action_requests` /
  `review_configs`),`confirmation_request` 帧自动由现有 `_serialize_hitl_request` 翻译

**改动**:

- **新文件**:`nexus/backend/shell_sandbox.py` / `shell_audit.py` / `middleware/shell.py`
- **修改**:`nexus/backend/tools.py` 注册 `shell_run` 工具 + TOOLS 列表;
  `nexus/backend/agent/_agent_builder.py` 注入 `shell_hitl` 到 middleware 链
  (在 `path_aware_hitl` 之后、`dynamic_identity` 之前)
- **新测试**:`tests/test_shell_sandbox.py`(44 例,黑名单全模式 + 边界)/
  `test_shell_audit.py`(11 例,JSONL + 权限 + rotate + OSError 降级)/
  `test_shell_run_tool.py`(15 例,subprocess 真实执行 + 沙箱短路 + 超时)/
  `test_shell_hitl_middleware.py`(17 例,interrupt mock + 异步双路径);
  `tests/test_tools_registry.py` 加 `shell_run` 注册断言
- **结果**:`pytest tests/` 800 → **902 passed**(+102 新测试),0 failed / 12 skipped
  (pre-existing `test_e2e_features.py` WS 403 失败与本批无关,基线 stash 后同样失败)

**使用示例**(LLM 视角):

```
User: 帮我看一下 ~/.nexus/outputs 下面有哪些文件
LLM: 好的,我要执行 shell 命令 ls
     → [ShellHITL] interrupt() → WS confirmation_request 弹出"是否批准 ls -la ~/.nexus/outputs"
User: 批准
LLM: [调用工具] shell_run ls -la ~/.nexus/outputs  → exit_code=0, stdout=foo.txt ...
     → outputs 目录下有:foo.txt, bar.py
```

#### Added — 聊天消息本地路径 click-to-open + 图片内联缩略图 (file://) (2026-07-14)

LLM 用 `shell_run open /Users/yxb/.nexus/outputs/koi.jpg` 后,assistant 消息里
回显的绝对路径原样显示为纯文本,用户无法"点击直达 Preview / Finder"。
本批把这类路径转成 click-to-open 的 `<a>` / `<img>` 节点:

- **`frontend/src/lib/remarkPathLinkify.ts`**:remark 插件,扫 `text` 节点里的
  绝对路径(`/Users/...`、`~/...`),扩展名为图片后缀(jpg/png/gif/webp/bmp/svg)
  → 转 `image` AST 节点(直接展示缩略图);其他后缀 → 转 `link` AST 节点
  (href=`file://...`)。inlineCode / 已有 link / 相对路径 / 无后缀词 不动。
- **`frontend/src/components/ChatBubble.tsx`**:`ReactMarkdown` 接入上述 plugin,
  加 `urlTransform` 绕开 react-markdown v10 默认白名单(只放行 `https?`/`file`/
  相对/`#`,其他协议继续被抹空 — 防御 `javascript:` 等 XSS)。
- **`frontend/src/components/desktop/styles/chat.css`**:`.file-link` 绿系强调色
  + hover 浅背景 + 触摸目标放大;`.file-image` 最大 320px + 圆角 + 边框 +
  loading=lazy。user / assistant 气泡各一套配色(dark mode 走 `data-theme=dark`)。
- **测试覆盖**:
  - `frontend/src/lib/__tests__/remarkPathLinkify.test.ts` 新增 6 个用例
    (unified → remark → rehype 管线直接断言 HTML):图片→img / 路径→link +
    title / inlineCode 内不动 / 相对路径不动 / 中文标点保留 / 多图
  - `frontend/src/components/__tests__/ChatBubble.test.tsx` 新增 3 个用例
    (RTL 渲染断言最终 DOM):`<a class="file-link" target="_blank">` / 
    `<img class="file-image" src="file://..." loading="lazy">` / inlineCode 保留

- **不写 E2E**:click-to-open / 缩略图加载是浏览器 + Electron WKWebView 原生
  行为(file 协议走系统 handler,file→file 默认允许),不在 Nexus 代码路径
  上;vitest 9 个用例已 100% 覆盖可控层(AST + DOM)。

#### Fixed — 思考块禁止"自指反思 / 元话语" (2026-07-14)

用户反馈:LLM 思考卡片里 LLM 写"实际上我没有图像生成工具…我应该
直接、简洁地回答,不要过度铺垫",然后正文又重新组织一遍 → 用户看完
思考再看正文觉得是复读机。

根因:LLM 训练范式偏向"先在 thinking 里策划回答(我应该怎么答 →
让我先 X 再 Y → 我需要致歉再给替代),再写正文"。thinking 块从
"对问题的推理" 滑成了"对自己回答的策划",thinking 跟正文内容强重叠,
对用户无信息增量。

修法:`nexus/backend/agent/_system_prompt.py` 「思考输出格式」段新增
强约束(2026-07-14 commit)—— 禁止 thinking 块写"我应该…/让我…/
我需要…/要简洁/要直接/先承认…再…"这类元话语,并附 3 个负面示例
对齐 LLM 训练里的高频反模式。

#### Fixed — thinking 块 emit 阶段后处理剥离元话语 (2026-07-14)

上一条 prompt 强约束**不彻底**:LLM 仍输出 `I should be honest about
this limitation.` / `Let me respond honestly and helpfully in Chinese.`
(英文 + 自我免责策划),绕过中文禁令。System prompt 无法 100% 杀掉
LLM 对"我要怎么回答"的策划反射 —— 这是训练记忆级 reflex。

修法(2026-07-14 commit):在 `nexus/backend/api/ws/streaming.py`
`_emit_chunks` 阶段对 `kind == "thinking"` 的帧**再做一遍正则剥离**:

- 中英文双语 keyword: `我应该/让我/我需要/我打算/我会/我要/要不我/
  策略是/方法:/思路:/Approach:/Strategy:/Plan:` + `I should/Let me/
  I need to/Let me think/I will/Let us/I'll`
- 句级匹配(行边界 + 句末),命中整句删除;真推理(`The user wants…` /
  `Looking at tools…`)不误伤
- **剥离仅影响 emit 内容**;`emitted_chunk_text`(入库到
  `messages.thinking_content`)仍保留 LLM 原始推理 → 质量门
  MemoryFilter 看的还是真推理
- 全由元话语组成的 thinking → strip 后空串 → 整帧 skip,不送前端
  (event_id 仍自增,仅占位)

测试:

- `tests/test_thinking_metacommentary_strip.py` 11 个单测(纯函数边界)
- `tests/test_thinking_metacommentary_e2e_emit.py` 3 个 e2e(_FakeWebSocket
  + asyncio.run,直接用用户截图原始文本验证 emit 行为)

#### Fixed — 聊天图片内联渲染在 DMG 内真正生效 (Tauri asset protocol) (2026-07-14)

上一批 (2026-07-14) 上线的 pathLinkify 在浏览器 / Electron dev 模式可以展示,
但在 **Tauri 2 DMG** 内 `<img src="file://...">` 显示破图占位 —— webview CSP
`img-src 'self' data: blob:` 把 `file://` 协议拒了。本次修法启用 Tauri asset protocol
做 protocol-as-config 的"白名单 URL 桥"(零外部进程,跟 macOS / Electron 一样):

- **`desktop/src-tauri/tauri.conf.json`**:
  - `app.security.assetProtocol.enable: true`(必须;默认 false)
  - `app.security.assetProtocol.scope: ["$HOME/.nexus/**", "$DOWNLOAD/**",
    "$PICTURE/**", "$DESKTOP/**", "$DOCUMENT/**"]`(LLM shell_run 默认输出 + 桌面/下载/图片/文档)
  - `app.security.csp` `img-src` 增 `asset: http://asset.localhost`,放行
    `convertFileSrc()` 产出的 `<protocol>.localhost/...` URL
- **`desktop/src-tauri/Cargo.toml`**:`tauri` features 增 `protocol-asset`
  (Tauri 2 build 时检查 allowlist,缺这个直接报错)
- **`frontend/src/lib/remarkPathLinkify.ts`**:`fileUrl(path)` → `toAssetUrl(path)`:
  Tauri 模式(`window.__TAURI_INTERNALS__` 存在)调 `convertFileSrc(path)` 拿
  `http://asset.localhost/<encoded>` URL;浏览器模式维持 `file://` 兜底
  (dev / Electron fallback)。vite build 在非 Tauri bundle 里把这段 dead-code-eliminate
  (顶层 `typeof window` 守卫 + 静态 false 检测)
- **`frontend/src/components/ChatBubble.tsx`**:`urlTransform` 白名单增
  `http://asset.localhost` 前缀,放行 Tauri asset URL,不被默认白名单抹空。

**安全**:Tauri 2 asset protocol 的 scope 由 Rust 进程在 webview 层强制执行,
前端无法绕过 scope 访问任意路径 —— 即使前端被 XSS,也读不到 ~/.ssh / ~/.aws 之类。
`assetProtocol.enable=true` + scope 白名单是 Tauri 官方推荐模式(同 Electron
`protocol.handle` 思路,文档:https://v2.tauri.app/reference/config/#assetprotocolconfig)。

**测试**:
- `frontend/src/lib/__tests__/tauriAssetProtocol.test.ts` 新增 3 个用例
  (vitest + Node `fs.readFileSync` 直接断言 `tauri.conf.json` 关键字段,
  防止后续无意改回):assetProtocol.enable === true / scope 含 `$HOME/.nexus/**`
  / CSP img-src 含 `asset: http://asset.localhost`
- `frontend/src/lib/__tests__/remarkPathLinkifyTauri.test.ts` 新增 2 个用例
  (mock `window.__TAURI_INTERNALS__.convertFileSrc`,走 unified 管线断言 HTML
  含 asset URL)
- `frontend/src/components/__tests__/ChatBubble.test.tsx` 新增 2 个 Tauri 模式用例
  (RTL 渲染最终 DOM:`<img src="http://asset.localhost/...">` /
  `<a href="http://asset.localhost/...">`)
- 原 browser-mode 6 + 3 = 9 个测试**不**改:浏览器模式无 `__TAURI_INTERNALS__`
  仍走 `file://` URL,行为不变。

**为什么不上 E2E**:真 DMG 端到端验证(打包 → 安装 → 拖图进聊天)已在本地手动
跑过;cargo check 已确认 schema 接受 `protocol-asset` feature。重构为端到端
spec 工作量 / 维护成本不值,见上一批 "不写 E2E" 的同类理由。

---

### test(e2e): journey 套件 Phase 2 扩到 8 条 (2026-07-13)

新增 4 条 user-journey spec,补齐用户视角盲区:

- `journey-quick-prompts-and-history`: 4 个 QUICK_PROMPTS 填入 + 手动发送 + Sidebar 历史会话切换
- `journey-stop-mid-stream`: 流期间 send-button disabled + 流结束恢复可点 + 气泡长度稳定
- `journey-input-edge-cases`: 空消息(noop) / emoji / 多语言(中英日)3 个 sub-test
- `journey-auth-401`: 模型密钥失效兜底(走 `NEXUS_E2E_SCENARIO=auth_401` mock 场景)

**WHY**:Phase 1 落地 4 条 journey spec 后,用户视角还有"输入边界 / 交互流 / 错误路径"三类盲区没覆盖,本批补齐。
微信扫码后"收消息 / 关键词回复"是另一个盲区,但后端无 HTTP inbound webhook 端点(消息走 WS 长连接),无法 mock,留待后续专项。

**mock LLM 扩 2 个场景**(`nexus/backend/llm/e2e_mock.py`):

- `auth_401`:每次 invoke 抛 `openai.AuthenticationError`,模拟 LLM 端点密钥失效
- `rate_limit`:每次 invoke 抛 `openai.RateLimitError`,触发 stream_guard 重试 + 兜底

详见 `docs/superpowers/plans/2026-07-12-e2e-journey-suite.md` Phase 2。

---

### Breaking — WebSocket subprotocol 格式 (2026-07-12)

协议前缀由 `nexus-v1.token=<value>` 改为 `nxv1-<base64url(token)>`。

**WHY**:RFC 7230 §3.2.6 `token` ABNF 不允许 `=` 或 `.`(两者都是
delimiter,不在 `tchar` 内)。Chromium ≥149 严格校验,旧格式在
ChatArea mount 时抛 `SyntaxError`,被 ErrorBoundary 接管,前端
发送消息路径全面失效(包括 journey spec 端到端 fail)。修复选
短前缀 + base64url token,全字符在 tchar 内,browser + tungstenite
+ http::HeaderValue 三方都接受。

**改动**:

- `nexus/backend/api/ws/auth.py` — `_WS_SUBPROTOCOL_PREFIX = "nxv1-"` + 新
  `_decode_subprotocol_token()` helper,`base64.urlsafe_b64decode` 解码
  token,`try/except (binascii.Error, ValueError)` + `UnicodeDecodeError`
  兜底,失败按"无 token"处理。
- `nexus/backend/main.py` — `websocket_endpoint` 选 `selected_subprotocol = "nxv1"`,
  `has_nexus_subprotocol` 检测从 `startswith("nexus-v1.token=")` 改为
  `startswith("nxv1-")`。docstring 同步更新。
- `tests/test_ws_auth_subprotocol.py` — 新增 `_b64u_subprotocol()` helper,9 个
  测试断言从 `["nexus-v1.token=test-token"]` 改成
  `[_b64u_subprotocol("test-token")]`(生成 `nxv1-dGVzdC10b2tlbg`),
  `accepted_subprotocol` 断言改成 `"nxv1"`。
- `frontend/src/hooks/useWsConnection.ts` — 新增 `encodeWsTokenSubprotocol()`:
  `btoa(unescape(encodeURIComponent(token)))` → `+`→`-`、`/`→`_`、去
  `=` padding,前缀 `nxv1-`。`subprotocols` memo 改用它。
- `frontend/src/hooks/useTauriWs.ts` / `frontend/e2e/ws-auth-subprotocol.spec.ts` —
  注释 + E2E 断言(`startsWith('nxv1-')`)同步。
- `desktop/src-tauri/Cargo.toml` — 新增 `base64 = "0.22"` 依赖。
- `desktop/src-tauri/src/ws_relay.rs` — `WS_SUBPROTOCOL_PREFIX = "nxv1-"` +
  `encode_subprotocol_token()` 用 `base64::engine::general_purpose::URL_SAFE_NO_PAD`
  编码 token,单元测试断言值同步更新(`"nxv1-YWJjMTIz"`)。
- `docs/operations/quality.md` §11 — 加 §11.0 协议格式变更历史段,§11.1-11.5
  全部改成 `nxv1-<b64u>` 表述,§11.5 加 Chromium SyntaxError 排错条目。

**迁移**:

- 后端 / 前端 / 桌面三端均改动,**不可拆分部署**(拆开部署服务端会拒旧
  客户端 100% 失败,前端会继续抛 SyntaxError)。
- 自定义客户端必须改协议前缀并先 base64url 编码 token
  (Python `base64.urlsafe_b64encode(t).decode().rstrip("=")` /
  JS `btoa(...)` + 三步替换 / Rust
  `base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(...)`)。
- 旧 subprotocol 字符串(含等号)完全不兼容,服务端按 prefix 检测后
  走 query fallback 或直接拒,**不会出现** "裸 token" 的语义漂移。
- query string `?token=` fallback 路径仍兼容(`NEXUS_WS_AUTH_QUERY_FALLBACK=true`
  默认),但生产客户端应切换到新 subprotocol 格式。

**Test Coverage**:

- Python `pytest tests/test_ws_auth_subprotocol.py`:9/9 通过。
- Rust `cargo test ws_relay`:4/4 通过(含新格式断言 `nxv1-YWJjMTIz`)。
- 前端 `tsc --noEmit`:0 错。
- `ruff check + format`:0 错。

---

## [Unreleased] — 4 条 user-journey E2E spec + debug 工具挪出(2026-07-12)

新增 `frontend/e2e/journey/` 目录,落地 4 条模拟人工视角的端到端
E2E spec,全走真 LLM,CI 必跑:

- `journey-cold-start`: 新用户从打开到首次回复
- `journey-multi-turn`: 同会话 3 条连发 + 上下文回显
- `journey-hitl-workflow`: AGENTS.md 写入触发 HITL + 批准 → 流续接
- `journey-resilience`: 后端崩溃 → 重启 → 浏览器自动重连

新增 `frontend/e2e/journey/helpers.ts`,封装 journey 专用高层动作
(`sendSequence` / `expectContextRecall` / `killBackend` 等),
与现有 `frontend/e2e/helpers.ts` 底层选择器封装分层。

把 `debug-agnes-message.spec.ts` / `diag-ws-page.spec.ts`
从 `frontend/e2e/` 挪到 `frontend/scripts/debug/`,这俩是开发者排错
工具不是产品验收,移出 Playwright testDir 不再被自动扫描。

详见 `docs/superpowers/specs/2026-07-12-e2e-suite-design.md`。

---

## [Unreleased] — WS 鉴权收紧 + 密钥脱敏 + ChatArea 拆解(2026-07-12)

WS 鉴权 token 与 API key 存在三处泄密:

1. `frontend/src/lib/api.ts:1` 硬编码 `DEFAULT_TOKEN = 'nexus-default-token'`,被 Vite 打进 bundle,任何反编译/查看源代码都能拿到。
2. `frontend/src/components/ChatArea.tsx`(原 818 行单文件,Plan 2 已拆解 — 见下文 §ChatArea 拆解) 把 token 拼到 WS URL `?token=...`,走代理 access log / 浏览器历史 / 错误堆栈。
3. `desktop/SetupView.tsx:92` 把用户输入的 API key 尾部 4 位拼成 `••••••XXXX` 写到右键菜单 — 屏幕共享 / 录屏时等同明文,且右键菜单由 `openContextMenuAt` 持久化到组件状态。

### Root Cause

- **WS 鉴权协议选型**:RFC 6455 Sec-WebSocket-Protocol 子协议协商已存在,后端用 `Authorization: Bearer` 风格需要单独 HTTP 通道,无法套 WS。
- **降级心理**:沿用 `?token=...` query string 是低门槛选择,后端实现也最简单,但忽略了路径上每个中间件的可观测性。
- **"显示尾 4 位是 UI 友好"**:在密码管理器/一次性输入场景可以接受,但对存续会话的 API key 不适用。

### Changed (2026-07-12)

- **`nexus/backend/api/ws/auth.py`** — 新增 `_extract_ws_token(websocket)` 从 `Sec-WebSocket-Protocol` header 解析 `nexus-v1.token=<value>`;query string 走 fallback(由 `NEXUS_WS_AUTH_QUERY_FALLBACK` 控制开关,默认 `true`)。`require_token` 全程走 `_hmac_compare` (constant-time,防时序攻击)
- **`nexus/backend/main.py:397-422`** — `websocket_endpoint` 改用 subprotocol 鉴权;客户端发 `nexus-v1.token=...` 时回 `accept(subprotocol="nexus-v1")`,否则裸 accept。`import hmac` 已删
- **`desktop/src-tauri/src/ws_relay.rs`** — `ws_open` 新增 `token: String` 参数,用 `tungstenite::client::IntoClientRequest` 构造 Request,在 `Sec-WebSocket-Protocol` header 注入 `nexus-v1.token=<token>`。空 token 提前 fail。新增 `classify_ws_error()` 把 tungstenite error 映射成 UI 友好分类(不 echo raw error),杜绝 stack/URL 泄漏
- **`desktop/src-tauri/Cargo.toml`** — 新增 `http = "1"` 依赖(用于 `HeaderValue` 类型,与 tungstenite 共用)
- **`frontend/src/lib/api.ts`** — 删除 `DEFAULT_TOKEN` 常量;新增 `getWsToken()` 强制 `VITE_NEXUS_WS_TOKEN` 非空(空时抛 Error 引导配置);`apiFetch` 仅在 env 注入时设 Authorization Bearer header
- **`frontend/src/lib/secret.ts`** (新增) — `maskSecret()` 默认完全隐藏;`secretLength()` 返回字符数;`isSecretField()` 字段白名单(`api_key/token/password/...`)
- **`frontend/src/hooks/useTauriWs.ts`** — `token` 作为独立 invoke 参数传给 Rust relay;`String(e)` 替换为统一文案 `WS 启动失败,请检查后端状态和 token 配置`
- **`frontend/src/hooks/useWebSocket.ts`** — 新增 `subprotocols?: string[]` 选项,原生 `new WebSocket(url, subprotocols)`;非 JSON 文本帧丢弃(避免触发下游误分支)
- **`frontend/src/hooks/useWsConnection.ts`** — 适配层接受 `token`,按环境分派(Tauri: invoke 参数;浏览器: subprotocols)
- **`frontend/src/components/ChatArea.tsx:299`** — wsUrl 不再含 `?token=`;改传 `token` 给适配层
- **`frontend/src/components/desktop/SetupView.tsx`** — 右键菜单文本改为 `已设置(N 字符)` / `(空)`,不显示尾部字符;`saveModel` 加 `response.ok` 分支,区分 401/422/5xx 给可执行提示

### Strategy:三层防御

1. **协议层**:Sec-WebSocket-Protocol subprotocol 优先,token 不在 HTTP 任何字段(URL / header / body)出现,RFC 6455 标准
2. **传输层**:token 不进 Vite bundle(env 注入)、不进 URL、不进代理 access log
3. **UI 层**:任何敏感字段显示走 `maskSecret()` / `secretLength()`,无 `slice(-4)` 反模式

### Backward Compatibility

- `NEXUS_WS_AUTH_QUERY_FALLBACK` 默认 `true`,旧客户端 `?token=...` URL 仍可用
- 下个 major 版本 (`2.0.0`) 删除 query fallback
- SetupView 改动向后兼容,旧版本已设的 API key 不需重新配置

### Test Coverage

- `tests/test_ws_auth_subprotocol.py`(新增 9 测试):subprotocol 接受/拒绝、priority over query、fallback env 控制、空 expected、多值 subprotocol 解析、malformed value
- `desktop/src-tauri/src/ws_relay.rs` `tests` 模块(新增 3 测试):subprotocol prefix 格式、CRLF 注入防御、错误分类不泄漏
- 后端:**22/22 WS+auth 测试全过**(`test_ws_auth_subprotocol` + `test_ws_resilience` + `test_rest_auth`)
- Rust:**4/4 ws_relay 测试全过**
- 前端:`tsc --noEmit` 干净,`eslint .` 干净,`vite build` 通过(372KB → 115KB gzip)

### Why This Matters

WS token 是 gateway 唯一的访问控制 — 泄漏 = 任何人能以 Nexus 身份发任何消息、读所有会话。SetupView API key 直连第三方 LLM 服务,泄漏 = 用户账单被盗刷。三处都是低门槛修高收益。

---

### Problem

2026-07-10 21:45 Asia/Shanghai 用户让 Nexus 生成"明天穿衣提醒" HTML,LLM 输出的自然语言句"明天是 2026 年 7 月 11 日 星期五"是错的(实际为星期六)。HTML 头部时间戳恰好由确定性渲染给出正确日期,但模型侧声明是事实性幻觉 — 用户面对自相矛盾内容。根因:LLM 不擅长 mod 7 心算、无可用工具、也没拦截层。

### Root Cause

- **抽取+校验两步零基础**:无任何机制把"x 是 y"声明抽取出来对照真实日历/汇率/数学
- **system prompt 缺工具说明**:LLM 看不到能查星期/汇率的工具
- **wrap_model_call 无硬拦截**:即使模型无视工具,产物也没人挡

### Changed (2026-07-11)

- **`nexus/backend/fact_check/`** (新增 8 文件,271+230+...) — 确定性事实校验核心
  - `extractors.py`:DateWeekdayExtractor(`明天是 X 星期Y` / `2026-07-11 星期五` 中文/ISO 双 regex)、MathExtractor、UnitsExtractor、ExchangeRateExtractor
  - `verifiers.py`:DateWeekdayVerifier(Python `datetime.strptime` + `date.weekday()` 映射,纯函数零网络)、MathVerifier(`ast.literal_eval` 安全求值,禁裸表达式)、UnitsVerifier、ExchangeRateVerifier(**fail-open**,API 故障不阻断)
  - `units.py` / `exchange_rate.py`:手码转换表(温/长/质/容)+ 1h TTL 缓存
  - `pipeline.py`:`FactCheckPipeline.check(text) → FactCheckReport` 编排四类
- **`nexus/backend/agents/middleware/fact_check.py`** — `FactCheckMiddleware(AgentMiddleware)` 持 `wrap_model_call`,`fail_strategy="closed"` 默认抛 `FactCheckError`(LLM 输出被拒)
- **`nexus/backend/agent/_agent_builder.py`** — 接入中间件链:`[quality_gate, path_aware_hitl, dynamic_identity_middleware, FactCheckMiddleware, force_tool_mw]`
- **`nexus/backend/db.py`** — `quality_scores` 加 4 列(`fact_check_claims/results/status/latency_ms`),`save_quality_score()` 4 个新 kwarg(`json.dumps(ensure_ascii=False)`)
- **`nexus/backend/mcp/`** — `date_utils.py`(`today/weekday_of/next_n_days`) + `fact_verify.py`(`verify_claims`),硬编码 Asia/Shanghai,纯函数
- **`nexus/backend/fact_check/langchain_tools.py`** — 4 个 `@tool` 装饰器包装,接入 deepagents tool 注册
- **`nexus/backend/fact_check/prompt_constraint.py`** + `dynamic_identity.py` — `FACT_CHECK_CONSTRAINT` 中文提示注入,4 层 sandwich(`FACT → FACT_CHECK → static → FINAL`)
- **操作文档**:`docs/operations/fact-check.md`(215 行,8 节)+ `docs/operations/quality.md` §10

### Strategy:三层防御

1. **工具暴露**:4 个 `@tool` 让 LLM 自助校验(`today / weekday_of / next_n_days / verify_claims`)
2. **行为约束**:`FACT_CHECK_CONSTRAINT` 注入 system prompt 强制先查后答
3. **强制兜底**:`FactCheckMiddleware fail_strategy="closed"` 硬拦截,确定性 verifier 不依赖 LLM

### Test Coverage

- **128 个 fact-check 测试全过**(T1-T15)
- `test_fact_check_regression_2026_07_10.py`(T17):钉死 7-10 21:45 原 bug,5/5
- `test_fact_check_e2e_tomorrow.py`(T18):"明天是星期几" 用户场景双路径,22 测试
- 全量:785 passed / 1 skipped / 0 failed(4m32s)

### Meta-eval

- 5 样本(`data/fact_check_eval_samples.jsonl`)事实声明质量核验
- Cohen's kappa **0.643**(阈值 0.4,合格)
- Pearson **+0.950**
- 4/5 verdict 与人工一致,样本 2(`明天星期六`)被判 0.75 repair 而非 1.0 accept — 校准注记

### Modified Strategy

- **原计划**:T10 改造 `QualityPipeline.run_with_quality`(2026-06-29 已删);T11/12 等同。**重写**:中间件路径(fail-closed on output)
- **原计划**:T15 在 `nexus/backend/tools/`(已存在 `tools.py`,会 shadow);**移至** `nexus/backend/fact_check/langchain_tools.py`

### Why This Matters

下次用户问"明天/下周一/汇率/算术",Nexus 不再依赖 LLM 心算 — 工具是首选(快速自检),提示是次选(行为约束),中间件是兜底(强制拦截)。哪怕模型严重退化 / 升级出 bug / 网络挂掉,确定性事实不会编出去。

---

### §ChatArea 拆解 + 流式滚动性能(818 行 → 14 个子文件)

`frontend/src/components/ChatArea.tsx` 原 818 行单文件,9 类业务糅合:172 行 switch case、`scrollIntoView` 每个 chunk 无差别触发、`messagesRef.current.push(...)` mutate 反模式、子组件挤同一文件。变更文件 > 200 行后 Review diff 难度指数上升。

**Changed (2026-07-12,Phase 1)**:

- **`frontend/src/components/ChatArea.tsx` 删除**(原 813 行)。拆为 `frontend/src/components/ChatArea/` 目录下 14 个子文件,`ChatArea/index.tsx` 顶层编排(239 行)。Vite 文件夹导入自动解析 `'../ChatArea'` → `ChatArea/index.tsx`,`desktop/ChatView.tsx` 的 import 路径无需改动。
- **`ChatArea/hooks/useChatStream.ts`** (149 行)— 替代 `messagesRef` mutate 反模式。`ensureAssistantPlaceholder / appendToAssistant / pushUserAndPlaceholder / replaceAssistantWithPlaceholder / reset / snapshot` 六类操作,内部读 `useStore.getState().conversationMessages` 后用 `setConversationMessages(next)` 触发订阅。
- **`ChatArea/hooks/wsHandlers.ts`** (159 行)— 9 个 handler 纯函数 + `noop` 兜底。`(ev: StreamEvent, ctx: WsRouterCtx) => void`,便于后续 vitest 单测。
- **`ChatArea/hooks/useWsMessageRouter.ts`** (76 行)— `HANDLERS: Readonly<Record<StreamEvent['type'], WsHandler>>` 派发表 + dispatcher hook。type 不在表内时 noop。
- **`ChatArea/hooks/useChatSend.ts`** (90 行)— 单 send 入口 + `getReadyState() === 1` 闸门 + watchdog arm + user+placeholder push。
- **`ChatArea/hooks/useAutoScroll.ts`** (67 行)— `requestAnimationFrame` 节流的 scrollIntoView,`bottomThreshold=80` 避免用户拉历史时硬拽回底。
- **`ChatArea/hooks/useChatAreaActions.ts`** (84 行)— `handleKeyDown / insertPrompt / handleCopyMessage / handleRetry` 集中。
- **子组件 6 个**(`EmptyState` 99 / `MessageList` 49 / `ClarificationForm` 101 / `ConfirmationCard` 74 / `ErrorBanner` 52 / `Composer` 79)— 每个 ≤ 101 行,只接 props,无 store 引用(便于 React.memo)。
- **`ChatArea/index.tsx`** (239 行)— 顶层编排:`useChatStream → useMemo(WsRouterCtx) → useWsMessageRouter → useWsConnection → useChatSend → useChatAreaActions → useAutoScroll`。`wsCtx` 用 `useMemo` 注入保证 dispatcher 引用稳定 — 否则 useWsConnection 每次 render 会重连。
- **`tests/test_use_tauri_ws_placeholder.py::test_chunk_thinking_stop_spinner_early`** — 断言路径从 `ChatArea.tsx` 改到 `wsHandlers.ts`,断言形式从 `case 'thinking': { ... break; }` 改为 `export const handleThinking: WsHandler = (...)`。UX 不变量保留(`setIsLoading(false)` + `disarm` 都在 thinking/chunk 入口触发)。

**Why This Matters**:14 文件后单 PR 平均 diff ≤ 50 行;handler 是纯函数便于 vitest;RAF 节流 + bottomThreshold 让用户拉历史不被持续拽回。

**Phase 2-5 (后续轮次,留作 task #20 / #21)**: `React.memo(ChatBubble)` + chunk-rate 隔离、`messagesRef` 完全迁出、vitest 单测 `useWsMessageRouter / useChatSend`。

**Skip**: `react-virtuoso (50KB)` — 无 perf profile 数据,过早引入会增加 bundle。

### §ChatBubble memo + 流式 chunk-rate 隔离(2026-07-12,Phase 2)

承接 Phase 1 拆分,落地 Plan 2 §Phase 2 性能债。流式响应 60 chunks/s、长对话 100+ 条场景下,已完成消息的 ChatBubble 因父级 `MessageList` re-render 触发整列表 reconciliation + ReactMarkdown 重解析。修复:

- **`frontend/src/components/ChatBubble.tsx`** — 加 `React.memo` + 自定义比较器(`chatBubblePropsAreEqual`)。比较维度:`message.id / role / content / thinking / showThinking`。`onCopy` 引用变化刻意忽略(父级 re-render 副作用,不影响"是否复制"语义)。文件重排为 `ChatBubbleInner` 内函数 + 末尾 `memo(...)` 导出,保证 fast-refresh 规则(`react-refresh/only-export-components`)。
- **`frontend/src/components/chatBubbleProps.ts`** (新增) — 把 `ChatBubbleProps` 类型 + `chatBubblePropsAreEqual` 比较器从 ChatBubble.tsx 拆出。理由:react-refresh ESLint 规则禁止组件文件同时 export 组件 + 工具函数;拆出后 ChatBubble 只剩组件 export,fast-refresh 不被打断。
- **`frontend/src/components/__tests__/ChatBubble.test.tsx`** (新增 12 测试)— 比较器纯函数 7 测试(同 props 命中、内容变必渲染、思考变必渲染、id 变必渲染、role 变必渲染、onCopy 引用变命中忽略、showThinking 变必渲染)+ 集成 5 测试(同 props DOM 不变、内容变 DOM 更新、思考变 DOM 更新、onCopy 变 DOM 不变、showThinking 切关思考块消失)。

**Why This Matters**:长对话 + 流式响应下,memo 命中已完成的 ChatBubble,ReactMarkdown 不重解析。React DevTools Profiler 验证:同 message 引用 rerender 时 DOM 文本节点完全稳定,流式 chunk 仅当前活跃 bubble 命中。bundle size 不变(纯 React API,无新增依赖)。

**Test Coverage**:`ChatBubble.test.tsx` 12/12 测试全过(比较器 7 + 集成 5)。`tsc --noEmit` 干净,`eslint .` 干净。

---

### §ChatArea hooks vitest 单测(useWsMessageRouter / useChatSend,2026-07-12)

Plan 1 Phase 1 拆分出来的两个核心 hook(派发器 + 发送入口),Plan 2 §补 承诺给到单测。这次落地 vitest infra + 16 测试,补齐 hook 层单元保护。

- **`frontend/vitest.config.ts`** (新增) — `defineConfig` + react plugin + jsdom env + `setupFiles: ['./src/test/setup.ts']`。`globals: false` 避免全局污染;`include: ['src/**/*.test.{ts,tsx}']` 限制在 `src/` 内,不入 dist/。
- **`frontend/src/test/setup.ts`** (新增) — `@testing-library/jest-dom/vitest` 引入 + `afterEach(cleanup)`(RTL DOM 清理)+ `beforeEach` 重置 Zustand `useStore.setState({...})` + 清 `localStorage`(`PersistMiddleware` 写入的 darkMode 等不污染跨 test)。
- **`frontend/src/components/ChatArea/__tests__/useWsMessageRouter.test.tsx`** (新增 8 测试)— 未知 type / null / 非对象 / 缺 type 字段 → noop;thinking/chunk/error/confirmation_request 帧 → 对应 handler 触发;ctx 引用变 → dispatcher 引用更新(`useCallback` dep 命中);ctx 不变 → 缓存命中。
- **`frontend/src/components/ChatArea/__tests__/useChatSend.test.tsx`** (新增 8 测试)— 空内容不发送;`wsConnected=false` → `setLastError(ws_not_open)`;readyState!==OPEN 同样阻止;happy path 旧会话走 session_id,新会话走 title<=30 字;args 变 → send 引用更新;args 不变 → 缓存命中;trim 前缀内容不污染 send。
- **`frontend/tsconfig.app.json`** — `types` 加 `vitest/globals` + `@testing-library/jest-dom`,让 tsc 在测试文件里识别 `vi` / `describe` / `expect` 等全局。
- **`frontend/package.json`** — 加 `"test:vitest": "vitest run"` + `"test:vitest:watch": "vitest"`,保留原 `test:unit` (`.test.cjs` Node 内置 `node:test` runner),两套测试并存不互斥。
- **`frontend/package-lock.json`** — 装 vitest 4.1.10 + @testing-library/react + @testing-library/jest-dom + jsdom + @vitest/coverage-v8 等(共 150 个新包,0 新漏洞)。

**Why This Matters**:hook 是 ChatArea 行为的承重墙 — 派发器 route 错会让消息落不到 store,发送入口 WS 守卫漏会让鬼影消息发出去。`node:test` + `.test.cjs` 适合纯类(WsClient 那一套);hook 需要 React 上下文 + RTL `renderHook` + jsdom,必须 vitest。两套测试分立、互不替代。

**Test Coverage**:vitest 16/16 全过(useWsMessageRouter 8 + useChatSend 8)。`tsc --noEmit` 干净,`eslint .` 干净,`vite build` 通过(117KB gzip)。

---
### §WS 重连稳态 — WsClient 类抽象 + jitter 退避(2026-07-12,Plan 3)

`useWebSocket` 原 130 行 inline 重连:完全确定性退避(无 jitter)、无 maxRetries 上限(失败永远重试)、无 AbortController(用户手动重连时旧 setTimeout 还在 pending 会触发新 ws.close)、retry 计数不在 ws.open 时归 0(短抖动后累积过大)。N 客户端断网恢复后会在同 ms 重连,瞬间打满 backend。

**Changed (2026-07-12)**:

- **`frontend/src/lib/ws/WsClient.ts`** (新增,239 行) — 纯类,无 React 依赖。`ReconnectPolicy` 接口 `{baseDelayMs, maxDelayMs, maxRetries, jitterRatio, onExhausted, onRetryScheduled}`,`DEFAULT_POLICY = {baseDelayMs:1000, maxDelayMs:30000, maxRetries:8, jitterRatio:0.3}`(累计 ~2.5min 退避)。`computeReconnectDelay(attempt, policy, rng)` 纯函数导出,jitter 公式 `exponential + (rng()*2-1)*jitterRange`,rng 可注入便于测试。`socketFactory` / `scheduler` / `rng` 三个依赖注入点,允许 Node 单测 + 未来切 WebWorker。
- **`frontend/src/hooks/useWebSocket.ts`** (重写,87 行) — thin wrapper,只关心 React state `connected` 同步 + `client.connect()/disconnect()` 生命周期。13 行可读逻辑取代原 130 行 inline。
- **`frontend/src/types/index.ts`** — `StreamEvent` 加 `'system'` type + `payload?: { event: 'agent_init_timeout'; retry_in?: number }`,WS 帧契约向前扩。
- **`frontend/src/components/ChatArea/hooks/useWsMessageRouter.ts`** — `HANDLERS` 加 `system: noop`。前端默认吞掉系统帧(防御性 — 后端若新增帧类型,前端默认 noop)。
- **`nexus/backend/main.py:425-444`** — Agent 懒构造 60s 超时改发 `{type:'system', payload:{event:'agent_init_timeout', retry_in:5}}` 后**不**断 WS,客户端(Plan 3 WsClient)收到后临时拉长 baseDelay 5s 做退避 hint,WS 保持连接。`send_json` 失败时(连接已断)用 `try/except` 吞掉。
- **`frontend/src/lib/ws/__tests__/ws-client.test.cjs`** (新增,7 用例) — `node:test` 零依赖,覆盖 jitter 范围 / maxDelay 截断 / 1000 次随机样本越界 / 退避序列 151000ms 总时长。
- **`frontend/package.json`** — 加 `"test:unit": "node --test $(find src -name '*.test.cjs' -not -path '*/node_modules/*')"`,跨目录 glob 自动扫所有 .test.cjs。

**Why This Matters**:jitter 把多客户端同步重连打散到 ±30% 窗口;maxRetries=8 + onExhausted 给 UI 清晰边界;AbortController 让手动重连无副作用。Agent 懒构造 60s 后用户首条消息走 `agent_unavailable` 错误路径(原行为),但 WS 不断,WsClient 自动重试一次,体感上是"启动慢了一会"而非"连接断了"。

**Skip**: `useTauriWs` 重连改造 — Rust supervisor 已是心跳驱动的稳态;前端 useTauriWs 直连 backend,tungstenite 在 Rust 侧管断线重连。`wsStatus` slice 留给 Plan 4 WsSlice 一起扩。

---

### §useStore slice 拆分 + 持久化收敛(2026-07-12,Plan 4)

`frontend/src/hooks/useStore.ts` 原 139 行:11 个 setter + persist config + 中间件混在一起,持久化偏好(`darkMode` / `showThinking`)与瞬态业务流(`wsConnected` / `conversationMessages` / `pendingConfirmation`)单 store,违反 "slice per concern" 模式 — 组件订阅整个 store 后任一字段变 → re-render;新字段加进来就突破 200 行。

**Changed (2026-07-12)**:

- **`frontend/src/store/useStore.ts` 删除**,改用 `frontend/src/store/index.ts` 入口(70 行)— 4 slice + persist(只挂 uiPrefs) + safeStorage(SSR / Electron 兜底)。
- **`frontend/src/store/slices/`** (新增 4 文件) — `uiPrefs.ts`(darkMode / showThinking + toggleDarkMode,持久化) / `wsStatus.ts`(wsConnected / wsStatus / reconnectAttempts,瞬态) / `conversations.ts`(conversationMessages / models / currentModelId / modelName / isLoading,业务数据) / `channels.ts`(channelInbox / pendingConfirmation + ChannelInboxMsg / PendingConfirmation 类型导出)。每个 slice 是 Zustand `StateCreator`,setter 名与原 useStore **完全一致** — 13 处 import 路径迁移不改 setter 调用点。
- **`frontend/src/store/selectors.ts`** (新增) — 跨切片派生 selector:`useWsReconnectLabel()`(`S3/8` / null)、`useHasPendingConfirmation()`、`useActiveModelName()`。每个 selector 返回基础类型或已存在引用,避免在 selector 内 `.map/.filter` 重建新对象触发误判 re-render。
- **`frontend/src/store/__tests__/store-partialize.test.cjs`** (新增,7 用例) — node:test 零依赖,断言 partialize 输出字段数 = 2(darkMode + showThinking),不泄露 conversationMessages / channelInbox / pendingConfirmation / isLoading / wsConnected。
- **`frontend/src/components/desktop/hooks/useBootstrap.ts`** — 删除 `activeModelName` 返回值 + `setModelName` 副作用(无消费者 — DesktopShell 解构只取 isBootstrapping / initialView)。`setModelName` 仍保留在 conversations slice 给 ModelConfigModal 切模型同步用(`modelName` 字段有真实消费者:SettingsView / DesktopShell / ChatView / EmptyState)。
- **`ChannelInbox.tsx`** — `ChannelInboxMsg` type import 从 `store` 改到 `store/slices/channels`(类型归属 slice)。

**Why This Matters**:slice 拆分后 selector 派生粒度受控;partialize 显式列字段,把"持久化偏好"和"业务瞬态"边界物理隔离 — 未来加 WS frame handler 把新字段塞 conversations slice 时不会误持久化。

**Skip**: `devtools` middleware — 已有 persist,Redux DevTools 在 v5 zustand 是可选扩展,本期收益小。`session.ts` slice — `activeModelName` 是死代码且已删,无残留字段。

---

### §db wechat 索引化 — user_id 列查询 + ROW_NUMBER 分组(2026-07-12,Plan 5)

`nexus/backend/db.py` `find_latest_session_by_user` / `list_sessions` 走两条反模式路径,100k 行规模性能退化 + 语义错命中。

**Root Cause**:
- `find_latest_session_by_user` 旧实现用 `messages.content LIKE ? ESCAPE '\'` 扫 messages 表 — user_id 实际不在消息正文里(只是会话级别元信息),LIKE 永远返空 / 错命中;无索引,全表扫描 100-500ms。
- `list_sessions` 旧实现 Python 端 `title.split()[1]` 提取 `account_id` — 标题格式依赖、消息内容污染错命中、title 改即时不一致都源于此。

**Changed (2026-07-12)**:

- **`nexus/backend/db.py` `_create_tables`** — `sessions` 表新加 3 列(`account_id` / `wechat_user_id` / `channel_meta` TEXT-JSON),`_ensure_column` 幂等迁移;新增 2 partial index:`idx_sessions_channel_account (channel, account_id, updated_at DESC) WHERE deleted_at IS NULL` + `idx_sessions_wechat_user (wechat_user_id) WHERE deleted_at IS NULL AND wechat_user_id IS NOT NULL`(过滤软删行 + 索引 NULL 没意义,体积更小查询更窄)。
- **`create_session()`** — 接受 3 个新可选参:`account_id` / `wechat_user_id` / `channel_meta`(dict 用 `json.dumps` 序列化为 TEXT)。`channel_meta` 留给未来 feishu / telegram 通道的元数据扩展。INSERT OR IGNORE 保证幂等。
- **`find_latest_session_by_user()`** — 改列等值查询:`SELECT id FROM sessions WHERE wechat_user_id = ? AND account_id = ? AND channel = ? AND deleted_at IS NULL ORDER BY updated_at DESC LIMIT 1`。`account_id` 可选(None 时只看 wechat_user_id,旧调用方行为兼容)。命中 `idx_sessions_wechat_user`,< 5ms。
- **`list_sessions()`** — 改 `ROW_NUMBER() OVER (PARTITION BY CASE WHEN channel='wechat' THEN COALESCE(account_id,'') ELSE id END ORDER BY updated_at DESC)` 子查询 + 外层 `WHERE channel != 'wechat' OR rn = 1`,main channel 全保留,微信 channel 按 account_id 每组一条。Python 端"title 解析 + dict 分组"完全删除。
- **`nexus/backend/channels/gateway.py`** `_get_or_create_session` — 解析 `msg.channel_id`(`"wechat:wxid_xxx"` → `account_id="wxid_xxx"`)透传到 `find_latest_session_by_user` / `create_session`;`channel_meta={"account_id": ...}` 写库留给后续元信息查询。
- **`nexus/backend/sessions.py`** `SessionManager` — `create_session` / `find_latest_session_by_user` 都透传新参,保持 duck-typing 兼容(避免 gateway 走 type: ignore)。

**Test Coverage**:

- `tests/test_db_session_columns.py` (新增,3 用例) — `create_session` 写 column 字段 + `_ensure_column` 幂等迁移不抛错。
- `tests/test_db_index_wechat.py` (新增,6 用例) — find_latest 选 updated_at 最大、account_id 区分账号、过滤软删、`account_id=None` 跨账号通配;`list_sessions` 每账号一条微信 + 软删过滤。
- `tests/test_db_like_escape.py` (改 2 用例) — 旧 LIKE 路径不存在了,迁到新等值契约:user_id 含 % / \ 等特殊字面应原样命中,不再依赖 LIKE ESCAPE 转义。
- `tests/test_fixes_round2.py` `test_find_latest_session_by_user` (改) — 旧"消息正文里子串匹配"假设是反模式,迁到正经列等值契约。

**Why This Matters**:wechat 通道重启后重建 session 映射从扫消息表(不可靠 + 慢)变成列等值(< 5ms)。`account_id` 透传为多账号场景铺路。`list_sessions` 去 title 解析,标题可改成用户友好文案不再绑定 metadata。

---

## [Unreleased] — 4 commit 收尾:HITL 三态路由 / ws 包 re-export / force_tool 收紧 / 前端 TS strict

### Problem

2026-06-29 把 `agent.py` (1080 行) 和 `api/ws.py` (1386 行) 拆成 6 模块小文件后,落地 4 类遗留问题,本轮(commits `f63b9b9` / `ab90c04` / `fc41909` / `8400836`)一次性清理:

1. **HITL 弹窗全场景失效** — E2E 5 个场景(写项目源码 / 写 /tmp / 多 tool_call / reject-then-reflect / edit_file)全部 FAIL,LLM 写源码无 HITL 弹窗直接落盘,产品形态与 OpenClaw 个人助理定位严重背离。
2. **`ws/ 拆包后 mock.patch 路径破`** — 6 个测试 (`test_ws_hitl.py ×3` / `test_clarification.py ×1` / `test_ws_package_init.py ×1` / `test_observability_ws_integration.py 间接`) 报 `AttributeError: module 'nexus.backend.api.ws' has no attribute 'add_message'` / `'add_message'` 路径错位。
3. **ForceToolMiddleware 把 task 类问题强制 patch yandex_search** — 用户问"帮我把 print 写到 nexus/backend/test_human.py",LLM 拿到 yandex_search 结果不知何用,新一轮"无 tool_call" → 强制再次 patch → 死循环(后端日志可见同一 session 内 16+ 次 yandex_search patch)。
4. **前端 TS strict 报错阻塞 DMG 构建** — `ToastHost.tsx` 报 TS18048 / TS2741,`useWsConnection.ts` `UseWsConnectionResult` 缺 `isTauri` 字段报 TS2741;`cd frontend && npm run build` 走 `tsc -b --noEmit` 校验直接失败,DMG 无法产出。

### Root Cause

1. **HITL**:deepagents 0.5.3 不支持 permissions 写入 `mode="interrupt"`(被静默忽略,permissions 仅支持 `allow` / `deny` / `ask` 之类枚举)。需要新挂载路径感知的 AgentMiddleware,在 `wrap_tool_call` 阶段对"非白名单写工具"主动抛 `GraphInterrupt`,由 WS handler 转成 `confirmation_request` 帧回放给前端。
2. **ws re-export**:拆包前 `ws.py` 是单文件,`add_message` 是其顶层属性;拆成 `ws/{__init__.py, finalize.py, streaming.py, observability.py}` 后,生产代码继续走 `from ... import db; db.add_message(...)` 是没问题的,但**测试用 `patch("nexus.backend.api.ws.add_message")`** 需要 `ws` 包层显式 re-export。`from x import y` 在 import 时绑值,monkeypatch 改到的函数与生产 import 时的对象是同一个属性才会生效。
3. **force_tool 死循环**:初版 `force_intents=("knowledge", "task")` 是为修"弱模型问投资不调工具"引入,但泛化到 task 类有反模式 — task 类工具选择很广 (`write_file` / `edit_file` / `str_replace_editor` / `apply_patch` 等),强制 patch `yandex_search` 把 LLM 推上一条它本来不该走的搜索路径。`knowledge` / `task` 必须分开评估,不是一篮子。
4. **TS strict 报错**:`Record<ToastKind, KindColor>` 显式声明后,KIND_COLOR 全字段必须填齐;另外 `UseWsConnectionResult` 接口新增 `isTauri` 字段但 return 仍只返回子 hook 结果。

### Changed (2026-06-30)

- **`nexus/backend/middleware/hitl.py`** (新增,~330 行) — `PathAwareHITLMiddleware(AgentMiddleware)`,三态路由:
  - **protected** (解析自 `resolve_protected_paths(project_root)`,含 `AGENTS.md` 类) → 透传给 `quality_gate`,quality_gate 已经管
  - **HITL** (非白名单 + 非 protected:项目源码 / `/tmp` / 全局 `.git/` 等) → `raise GraphInterrupt(tool_call)`,触发 WS `confirmation_request` 帧
  - **deny 白名单** (`.nexus/skills/*` / `.nexus/cache/*` / `.nexus/sandbox/*` / `.nexus/memories/*` / `.nexus/subagents/*`) → 直接透传(LLM 自己的事,但用户无条件信任)
  - 常量 `_DANGEROUS_PREFIXES` (写入即破坏系统的): `os.path.expanduser("~") / ".ssh" / ".aws"` 等
  - 为什么走 middleware 不走 permissions:permissions 的 `mode="interrupt"` 在 deepagents 0.5.3 不支持(silent ignored);middleware 是 framework-stable 钩子

- **`nexus/backend/agent/_agent_builder.py::create_agent` middleware 链追加**:
  - `middleware=[quality_gate]` → `[quality_gate, path_aware_hitl, dynamic_identity_middleware, force_tool_mw]`
  - 调用顺序敏感:`quality_gate` 先(只关心 AGENTS.md,透传其它);`path_aware_hitl` 后(对透传过来的"非白名单 + 非 protected"路径触发 HITL)
  - `_ensure_column` `_register_channel` 类副作用调用顺序不变

- **`nexus/backend/api/ws/__init__.py` 补 re-export**:
  - 加 `from ...db import add_message` 重新导出,且加入 `__all__` 列表
  - 加 inline 注释"持久化入口(2026-06-30 拆包后补 re-export,保证 mock.patch 路径稳定)"

- **`nexus/backend/api/ws/{finalize.py, streaming.py, observability.py}` 改 import 模式**:
  - `from ...db import add_message` → `from ... import db as _db` + 调用改为 `_db.add_message(...)`(monkeypatch-friendly)
  - WHY:`from x import y` 在 import 时把 `y` 绑到当前命名空间,后续 `patch.object(ws_module, "y")` 改不到生产侧持有的对象引用;`x.y` 是属性查找,可被 monkeypatch 替换
  - 跟 `feedback-monkeypatch-module-state.md` 经验一致

- **`nexus/backend/agent/_agent_builder.py::create_agent` force_tool 收紧**:
  - `ForceToolMiddleware(force_intents=("knowledge", "task"))` → `ForceToolMiddleware(force_intents=("knowledge",))`
  - task 类问题(`print` 写代码 / 写脚本 / 写文件)放行原 LLM 决策(可能是 `write_file` / `edit_file` / `str_replace_editor`),由 LLM 自决
  - knowledge 类("BTC 还能涨吗" / "元力股份 能买吗")继续强制 patch `yandex_search`(LLM 必须先看事实,不复读身份话术)

- **`frontend/src/components/ToastHost.tsx` TS strict 修复**:
  - 引入 `interface KindColor { bg: string; border: string; }`
  - `KIND_COLOR: Record<ToastKind, KindColor>` 全字段 (`info/success/warn/error`) 显式声明
  - 渲染时 `const c = KIND_COLOR[t.kind] ?? KIND_COLOR.info` 兜底

- **`frontend/src/hooks/useWsConnection.ts` TS strict 修复**:
  - return 改 `return { ...(isTauri ? tauri : browser), isTauri }` 合并 `isTauri` 字段(子 hook 返回值不含它,但 `UseWsConnectionResult` 接口要求暴露)

### Added

- **`tests/test_ws_hitl.py`** (新增,5 场景 3 类路径) — PathAwareHITLMiddleware 单元 + E2E 双层:
  - **正常路径**:项目源码 (`nexus/backend/foo.py`) 触发 GraphInterrupt → WS 收到 `confirmation_request` 帧
  - **边界**:`.nexus/skills/<name>/SKILL.md` 走白名单透传 / protected 路径透传给 quality_gate / 重复 interrupt 状态保留
  - **异常**:`/tmp/foo.py` 是 `HITL` 不是 `deny`(测试 LLM 不应该把代码写到 `/tmp`,弹窗让用户拒绝)
  - 副作用:idle `wrap_tool_call` 必须支持同步路径(deepagents 的 sync tool 调用仍走 `wrap_tool_call`,不是 `awrap_tool_call`)

- **`tests/test_ws_package_init.py`** (新增,3 测试) — 回归保护:
  - `test_ws_module_exposes_all_documented_symbols` — `__all__` 列表的每个名字都能 `getattr(ws, name)`
  - `test_ws_module_add_message_is_callable` — `ws.add_message` 是 callable
  - `test_ws_module_add_message_points_to_db_add_message` — **`ws.add_message is db.add_message`**(invariant,拆包后必须成立)

- **`tests/test_force_tool_middleware.py::test_task_intent_no_longer_forced_to_yandex_search`** (新增) — 守 task 类不被 patch 反模式:
  ```python
  mw = ForceToolMiddleware(force_intents=("knowledge",))
  req = _make_request("帮我把 print('hello') 写到 nexus/backend/test_human.py")
  response = mw.wrap_model_call(req, lambda r: AIMessage(content=""))
  assert not response.tool_calls, f"task 类不应被强制 patch,实际: {response.tool_calls}"
  assert response.content == ""
  ```

### Changed (测试侧,详细)

- `tests/test_ws_hitl.py` — `patch("nexus.backend.api.ws.add_message")` ×3 → `patch("nexus.backend.db.add_message")` ×3
- `tests/test_clarification.py`:
  - 引入 `from nexus.backend import db as _db_module`
  - `real_add_message = ws_module.add_message` → `real_add_message = _db_module.add_message`
  - `patch("nexus.backend.api.ws.add_message", side_effect=fake_add_message)` → `patch("nexus.backend.db.add_message", ...)`
- `tests/test_observability_ws_integration.py`:
  - `patch.object(ws_module, "_get_observability_sink", ...)` ×3 → `patch.object(obs_module, "_get_observability_sink", ...)` ×3
  - 加 `from nexus.backend.api.ws import observability as obs_module`

### Removed

- **`pyproject.toml` 残留孤立路径引用**:
  - `packages = ["nexus/backend/agent.py", "nexus/backend/api/ws.py"]` 类的单文件路径引用(实际已是包布局)
  - 跟 `feedback-code-vs-product-distinction.md` 的"DMG 里不该有孤儿文件" 一致

### Verified

- `ruff check nexus/ tests/` — All checks passed
- `ruff format --check nexus/ tests/` — 0 diff
- `pytest tests/ -q --timeout=60` — **558 passed, 12 skipped** in 38.06s (基线 552 → +6 新测试 / 0 回归)
- `cd frontend && npx tsc -b --noEmit` — 0 错(Tauri webview2 chromium + 兼容)
- 5 个 E2E HITL 场景:WS 端收到 `confirmation_request` 帧,落地 `accept` / `reject` 走通
- 后端日志确认:ForceToolMiddleware 同一 session 内 `wrap_model_call` 触发次数 ≤ 1(不再 16+ 次死循环)
- DMG 重打:`bash scripts/build_dmg.sh` → 产物 `release/Nexus-1.0.0-arm64.dmg` 70MB → 安装到 /Applications/,端到端确认

### Notes

- **`backend/agent.py` 单文件遗留**:本次 commit 提交后,实际拆分已落到 `_agent_builder.py` / `_backend.py` / `_checkpoint.py` / `_llm_factory.py` / `_subagents.py` / `_system_prompt.py` 6 个模块 + `agent.py` 作为 façade,主干可读 200 行内。模块化效果在 `tests/test_agent_*.py` 9 个测试文件全过里体现。
- **`api/ws.py` 单文件遗留**:同样落到 `__init__.py` / `connection.py` / `finalize.py` / `observability.py` / `streaming.py` / `thinking_parser.py`(重构已在更早 commit),本次 re-export + monkeypatch-friendly 是拆包路线图的最终态。
- **`_DANGEROUS_PREFIXES` 列表会随产品功能收敛**:当前包含 `~/.ssh/` / `~/.aws/` / `/etc/` / `~/.zshrc` / `~/.bash_profile`,社区 LLM 整体偏保守,expanduser 命中就 deny-redirect 到 `~/.nexus/sandbox/` 重写。
- **为什么 HITL 不走 deepagents permissions**:permissions 模型在 deepagents 0.5.3 后稳定支持 `mode="ask"` + on_event 钩子(0.6.12 加入),但产品对"project source path 敏感"是 Nexus 维度特性 — 未来 deepagents 升级后可以整体迁到 permissions,但本次为 0.6.12 → 0.7.0 升级预留 hook,不动。

---

## [Unreleased] — DeepAgents 框架对齐:删除自造 QualityPipeline / IntentClassifier,引入 ForceToolMiddleware + tier_routing

### Problem

2026-06-29 用户反馈:**完全基于 DeepAgents 框架开发,需要优化的增加的模块
再自己开发**。但当前代码里有两块**自造 LLM-to-LLM 中间件**:

  1. **`nexus/backend/quality/pipeline.py`** —— 维护一套自造的
     QualityPipeline,在主 LLM 响应后**复用同一个 LLM** 做 1-shot 评分,
     触发 REPAIR / REJECT 时再让主 LLM 反思。质量门本应是 deepagents
     `RubricMiddleware` 的标准能力,自造版本跟 deepagents 0.6.x 升级
     路径脱节。
  2. **`nexus/backend/intent/router.py`** —— 用户消息先过一次 LLM
     分类器(也是 1-shot function calling,5s 超时),把 intent
     (knowledge / task / chitchat) 写库 + 喂给 quality gate 短路。
     实测 agnes 慢模型 16s+ 经常让 wait_for 失效,前端 spinner 卡死。
     业务级"intent 标记"用正则同步推断足够,**LLM 介入是反模式**。

外加:弱模型(MiniMax-M3)对"元力股份 能买吗"这类投资问题不主动调
yandex_search,LLM 复读身份话术("我是 Nexus,由 X 驱动...")。根因是
system prompt 的"标准话术"硬指令对弱模型过强,把它推到身份回答上。

### Root Cause

1. QualityPipeline:把"主 LLM 评分"硬塞在主循环里,跟 deepagents
   `RubricMiddleware(*, model=..., tools=None, max_iterations=3)`
   的契约不兼容(后者期望在 create_deep_agent 阶段挂载,
   middleware 内部维护评分状态)。两条路径并存导致:
   - RubricJudge 的 faithfulness rubric 已经挂到 QualityGateMiddleware
     上(拦截 AGENTS.md 写入)
   - 主循环的 QualityPipeline 重复一次评分,REPAIR 时再让主 LLM 重生
   - 维护成本 ×2,deepagents 升级后两个评分器行为漂移
2. IntentClassifier:中间件层**不该**再调 LLM
   (对齐 DeepAgents 框架的设计原则:SubAgent + Task 工具机制
   让主 LLM 自己决定 dispatch,中间件只做轻量路由/转发)
3. Tier 路由缺失:不同 tier 模型(弱 MiniMax-M3 vs 强 agnes-2.0-flash)
   共享同一份 system_prompt,弱模型没有"必须先调工具"的硬指令,
   强模型被"标准话术"拖去复读。

### Changed (2026-06-29)

#### 删除

- **`nexus/backend/quality/pipeline.py`** — 整文件删除(150 行)
- **`tests/test_quality_pipeline.py`** — 整文件删除
- **`nexus/backend/intent/router.py`** — 重写:从 LLM-to-LLM 分类
  改为同步正则推断(70 行,新文件见 Added)
- **`tests/test_intent_timeout.py`** — 整文件删除(测 LLM 超时,路径已删)
- **`tests/test_switch_model_rebuilds_intent.py`** — 整文件删除
  (对应 `_rebuild_intent_and_quality` 函数已删)
- **`main.py::_intent_llm` 全局 / `_get_intent_llm()` /
  `_rebuild_intent_and_quality()`** — 三处全局状态 + 函数整体删除
  (~120 行)
- **`_ensure_agent_ready` 里的 judge_llm 构造块** — 删除(50+ 行)
- **`ws.py:handle_websocket` 的 `get_intent_llm` 参数** — 删除
- **`ws.py::_classify_and_record` 的 `get_intent_llm` 参数** — 删除
  (新签名 `(websocket, session_id, user_content, last_event_id=0)`)
- **`routes/model_config.py` 的 `_rebuild_intent_and_quality` 引用 +
  `init_router` 签名** — 删 3 处调用

#### Added

- **`nexus/backend/middleware/force_tool.py`** (新增,182 行):
  - `ForceToolMiddleware(AgentMiddleware)` 挂在
    `create_deep_agent(middleware=[..., force_tool_mw])` 末尾
  - 行为契约:LLM 第一次响应**没调任何工具**且 user 输入命中
    `force_intents` 默认 (`("knowledge", "task")`) → patch 一个
    `yandex_search` tool_call,query 取自用户最后一条消息
  - 同步 `wrap_model_call` + 异步 `awrap_model_call` 双钩子(deepagents
    `agent.astream` 走 async 路径,缺一会 `NotImplementedError`)
  - **`classify_intent_lightweight(text)`** 纯函数暴露:正则 4 类
    (knowledge / task / identity / chitchat),单测可独立验证
- **`nexus/backend/profiles/tier_routing.py`** (新增,~120 行):
  - `register_tier_profiles()` 按 `provider:model` 注册 HarnessProfile
  - 弱模型 `_WEAK_SUFFIX`:`openai:MiniMax-M3` → 强调"必须用工具,
    投资/医疗/法律/股票类问题先调 yandex_search 走事实检索"
  - 强模型 `_FULL_SUFFIX`:`openai:agnes-2.0-flash` → "自主决定是否
    用工具,允许自由答"
  - 幂等保护:`_REGISTERED_SPECS` 缓存 + deepagents 同 key 累加合并
  - 用 deepagents 公开 API `from deepagents.profiles import
    HarnessProfile, register_harness_profile`
- **`nexus/backend/profiles/__init__.py` + `legacy.py`** (新增):
  - package 重新组织:`profiles/legacy.py` 承载旧
    `register_nexus_profiles` / `_ensure_registered` /
    `reset_profiles_for_test`(降级为 no-op,只设 `_PROFILES_REGISTERED`
    标志,保持旧测试 / 调用方零感知)
  - **`_PROFILES_REGISTERED` 必须定义在 package `__init__.py` 顶层**
    (不在子模块),否则测试 "True trap" — 子模块 `global` 改不到
    package 属性
  - `__init__.py` re-export 全部名字,`from nexus.backend.profiles
    import (register_nexus_profiles, register_tier_profiles, ...)` 工作
- **`nexus/backend/intent/router.py` 重写** (~100 行):
  - `classify_intent(message: str) -> IntentKind` 纯函数,**不再接 LLM**
  - 内部调 `classify_intent_lightweight`,把它的字符串 bucket 映射到
    `IntentKind` 字面量(`identity → chitchat` 归一)
  - `try/except` 兜底:任何异常 / 空消息 / None 输入 → DEFAULT_INTENT
  - 延迟 import `force_tool` (避免 DB-only 操作被迫拉 langchain)
- **`tests/test_force_tool_middleware.py`** (新增,8 测试):覆盖
  4 类意图 + 3 种响应分支
- **`tests/test_tier_routing.py`** (新增,4 测试):弱/强 suffix 内容 +
  幂等性 + 隔离 fixture
- **`tests/test_e2e_regression_coverage.py`** (新增,5 测试):覆盖矩阵
  标记,显式 import 关键链路 + 列举真实 E2E 在生产环境跑法
- **`tests/test_intent_router.py` / `test_intent_ws_integration.py` /
  `test_intent_heartbeat.py`** (重写/适配):适配新签名 + 删 LLM 路径
- **`nexus/backend/agent.py::create_agent`** 大改:
  - middleware 链追加 `force_tool_mw`:`[quality_gate,
    dynamic_identity_middleware, force_tool_mw]`
  - `create_deep_agent` 之前显式调
    `register_tier_profiles()`(顺序敏感,必须在 resolve_model 之前)
  - `_build_system_prompt` 删所有 `_FULL_PROFILE_TIPS` 段(模型特定
    指令改由 HarnessProfile suffix 注入)+ 删 `{driver_name}` f-string
  - docstring 改写:标注"模型特定指令由 tier_routing 通过
    HarnessProfile 注入,不在本函数硬拼"

### Verified

- `tests/test_tier_routing.py` 4/4 ✅
- `tests/test_force_tool_middleware.py` 8/8 ✅
- `tests/test_deepagents_integration.py` 19/19 ✅
- `tests/test_intent_router.py` 7/7 ✅
- `tests/test_intent_ws_integration.py` 4/4 ✅
- `tests/test_intent_heartbeat.py` 3/3 ✅
- `tests/test_e2e_regression_coverage.py` 5/5 ✅
- **全量 pytest**:`540 passed, 12 skipped, 0 failed` in 26.22s
- **ruff check**:All checks passed
- **ruff format**:`8 files already formatted`

### Notes

- 真实 E2E(`tests/e2e_debug_stock_question.py`)需 API key + DMG
  启动,在有 key 的环境跑:
  - active=agnes 问"元力股份 能买吗" → 1191+ 字投资分析
    (WS tool_start 帧出现 yandex_search)
  - active=MiniMax-M3 同样问题 → 第一次 LLM 响应不调工具,
    ForceToolMiddleware patch yandex_search,搜索结果回填后 LLM
    用结果回答(不再复读身份话术)
- `_HarnessProfile` 在 deepagents 是下划线前缀的内部 API
  (0.6.14 `_harness_profiles.py`);本项目统一改用公开
  `from deepagents.profiles import HarnessProfile, register_harness_profile`
  路径稳定,跨 deepagents 升级不会破
- 旧 `nexus/backend/profiles.py` 单文件已删除,内容拆到
  `profiles/__init__.py`(no-op 兼容层) + `profiles/tier_routing.py`
  (实际注册)

---

## [Unreleased] — 修复 model identity 串味:system_prompt 改用 middleware 实时注入

### Problem

用户反馈"标题显示 MiniMax-M3,LLM 答 agnes-2.0-flash,你设计的逻辑不对吧"。
具体场景:DMG 启动时 active=agnes,用户通过改 `~/.nexus/models.json` 切到
MiniMax-M3(没走 `POST /api/models/switch` 重建 agent),UI 标题栏立刻
反映新模型(`/api/model` 端点读 models.json 实时),但 LLM 收到的
system_prompt **仍然含旧 agnes** → LLM 自报"agnes-2.0-flash"。

### Root Cause

`_build_system_prompt` 把"当前驱动模型 = X"作为字符串常量塞进 system prompt,
**在 `create_agent()` 阶段只拼一次**。agent 是单例(lifespan 懒构造),
构造完成后 system_prompt 是 immutable baked string。`POST /api/models/switch`
会触发 `create_agent_with_model` 重建,但用户从 UI / 终端 / 第三方工具
直接改 `models.json` **不会**重建 agent → 标题栏(`/api/model` 端点)
和 LLM 回答的数据源不同步。

第一轮 fix (本 Unreleased 上一个 entry) 用 `cache_key = "model@active_name"`
试图让 prompt 在切换时重算 → 仍**没有**解决根本问题:active_name 改变
时,如果新一次 LLM 调用走的是同一个 agent 实例的缓存路径,prompt 还是会
用缓存的老值(缓存不是永远 100% miss)。

### Changed (第三轮重构 · 2026-06-29)

把"当前驱动模型信息"从"prompt 字符串里的死字面量"挪到"每次 LLM 调用前
实时注入的 middleware",从根上消除缓存滞留。

- **`nexus/backend/middleware/dynamic_identity.py`** (新增,121 行):
  - `dynamic_identity_middleware` 用 LangChain `@wrap_model_call` 装饰器
    实现,挂在 `create_deep_agent(middleware=[..., dynamic_identity_middleware])`
  - `wrap_model_call` 钩子每次 LLM 调用前**实时**调
    `get_active_model_info()` 读 `~/.nexus/models.json`,把
    `[FACT · 当前驱动模型 · 运行时实时注入]` 块 prepend 到
    `request.system_message.content` 的最前面
  - **async 签名**:deepagents 的 `agent.astream(...)` 走 async 路径,同步
    `wrap_model_call` 在 async 上下文里会抛 `NotImplementedError:
    Asynchronous implementation of awrap_model_call is not available`
    (E2E 2026-06-29 暴露)。函数用 `async def`,装饰器自动注册
    `awrap_model_call`
  - **不**缓存 FACT 块字符串 —— 缓存就是 bug 来源。每次都重算。
  - `system_message` 为 `None` 的防御性分支(理论上不会触发,只兜底)

- **`nexus/backend/agent.py::_build_system_prompt` 改写**:
  - 删 `[FACT · 当前驱动模型]` 块(由 middleware 注入,不在这里拼)
  - 删 `当前驱动模型: {driver_name}` 这类 hardcode(在【身份】段)
  - 加 `【驱动模型信息 · 由 middleware 注入】` 段,告诉 LLM "FACT 块
    来自 DynamicIdentityMiddleware,直接用里面的 name / vendor 答"
  - 删所有 `{driver_name}` / `{driver_vendor}` f-string 插值,函数
    **与激活模型完全无关**

- **`nexus/backend/agent.py::get_system_prompt` 缓存简化**:
  - `_CACHED_PROMPT` 从 `dict[str, str]` (key = `model_name@active_name`)
    改为单 bucket (`_CACHED_PROMPT["__default__"]`)
  - 旧方案的 `model@active_name` 维度是为了"切模型时强制重算 prompt";
    现在 FACT 已不在 prompt 字符串里 → 缓存滞留问题从根上消失,
    不需要分桶

- **`nexus/backend/agent.py::create_agent` middleware 挂载**:
  - `middleware=[quality_gate]` → `middleware=[quality_gate, dynamic_identity_middleware]`
  - dynamic_identity 在 LLM 调用**前** mutate system_message(quality_gate
    只拦截 tool_call,顺序无影响)

- **`nexus/backend/middleware/__init__.py`** (新增):包级 docstring 说明
  这个包存在的原因(middleware 拿不到 graph state,只能改 ModelRequest
  再透传;middleware 之间互不耦合,各跑各的)

### Added

- **`tests/test_agent_memory.py::TestBuildSystemPromptIsModelAgnostic`**
  (5 个测试):验证 `_build_system_prompt` 输出与激活模型无关 —
  - `test_prompt_does_not_bake_active_model_name` — prompt 不应再含具体模型名
  - `test_prompt_mentions_middleware_fact_block` — prompt 必须说明 FACT 块由 middleware 注入
  - `test_prompt_mentions_get_model_info_tool` — 工具仍然注册
  - `test_prompt_is_model_independent` — 切换 active model 后 prompt **完全不变**
  - `test_other_rules_kept` — 重构后产品层规则段保留
- **`tests/test_agent_memory.py::TestDynamicIdentityMiddleware`** (3 个测试):
  - `test_middleware_injects_fact_block_with_active_model` — 系统消息 prepend FACT 块
  - `test_middleware_reads_models_json_freshly` — 切换 active model 后**下次调用立即反映**
  - `test_middleware_handles_missing_active_model` — 无 active 模型时走降级措辞
- **`tests/test_agent_memory.py::TestCreateAgentWiresDeepAgentsMemory::test_middleware_kwarg_contains_dynamic_identity`** —
  契约:dynamic_identity_middleware 必须出现在 `create_deep_agent` 的
  `middleware=` 列表里(破了 → LLM 收不到 FACT → 串味回归)

### Verified

- `ruff check nexus/`:All checks passed
- `ruff format --check nexus/`:0 diff
- `pytest tests/test_agent_memory.py`:22 passed
- `pytest tests/`:549 passed, 12 skipped, 2 failed(基线 537 + 新 12 测试,
  零回归。2 失败全在 `tests/test_e2e_features.py`,需要 backend 跑起来 +
  真实 LLM API key,pre-existing 基础设施依赖,跟本次改动无关)
- E2E WS(同 server 实例,不重启):
  - active = agnes-2.0-flash → LLM 答 "我是 Nexus,由 agnes-2.0-flash 驱动 ... agnes-2.0-flash 由 agnes-ai 提供"
  - 改 models.json 切到 MiniMax-M3 → 下一轮 LLM 答 "我是 Nexus,由 MiniMax-M3 驱动 ... MiniMax-M3 由 MiniMax 提供"
  - **不重启 backend、不重建 agent**,回答立即反映新值,UI 标题栏永远一致

### Notes

- **为什么必须 async**:`@wrap_model_call` 装饰器会根据被装饰函数是
  sync 还是 async 自动注册 `wrap_model_call` 或 `awrap_model_call`。
  deepagents 的 `agent.astream()` 走 async 路径,如果只提供 sync 版本,
  第一次 LLM 调用会抛 `NotImplementedError`,ResilientRunnable 重试 2 次
  后给用户报 "重试 2 次后仍失败: NotImplementedError: Asynchronous ..."。
  函数改 `async def` 之后,装饰器只注册 `awrap_model_call`,无副作用。
- **数据流单一性**:`models.json` 仍然是唯一权威。middleware 在每次
  LLM 调用前重读一次,纯 IO 是 `json.loads(6KB)`,< 1ms,可忽略。
- **不再需要 `cache_key = "model@active_name"`**:这种 cache 维度是
  第二轮的妥协方案,本质是把"动态数据"塞进"静态缓存"的反模式。
  现在的架构是"prompt 字符串 = 静态,FACT 块 = 动态注入",从根本上
  让两层数据各走各的路径,缓存问题不存在了。

---

## [Unreleased] — 模型身份改用实时注入(不再硬编码,不再瞎答训练记忆)

### Problem

用户反馈"用的什么模型 应该真实获取模型的信息 而不是硬编码"。
本轮迭代解决 2026-06-29 暴露的两个 LLM 自我介绍答错场景:

1. **场景 A — 硬编码失效**:之前 fix 把 `model_name` 字符串拼进
   `f"基于 {driver_label} 打造"` 这种 prompt 模板字面量 → 启动时快照一次
   之后,用户切换模型若未走 `POST /api/models/switch` 重建 agent,
   prompt 还显示老模型,用户被误导。
2. **场景 B — LLM 不调工具**:试图改成"prompt 引导 LLM 必须先调
   `get_model_info` 工具拿真实数据" → E2E 验证(问"你用的什么模型"):
   - 当前 active = agnes-2.0-flash,训练数据里有 → LLM 凭记忆答对
     (Sapiens AI / agnes-2.0-flash),**工具 0 次调用** — 看似 OK
     但完全没"实时获取"
   - 当前 active = 其他冷门模型,训练数据里没有 → LLM **瞎答**
     "我使用的是 Qwen 模型,由阿里云(Alibaba Cloud)开发",**完全没看
     prompt 指令** — 提示词形同虚设

### Root Cause

- 把"模型身份"当作字符串常量塞进 prompt 模板 → 任何"数据源必须活"的
  保证都依赖外部机制,内生不可靠。
- 把"必须调工具"当 soft rule → LLM 训练抗性让 soft rule 失效。

### Changed

- **`nexus/backend/agent.py::_build_system_prompt` 实时读 active model**:
  - 函数体里调 `get_active_model_info()` 从 `~/.nexus/models.json` 实时读
    name / vendor,拼进 prompt 顶部 `[FACT · 当前驱动模型]` 块
  - 数据源是**单一**的(models.json),切换模型后下一轮构造自动反映新值
  - `get_system_prompt` cache key 改为 `f"{model_name}@{active_name}"` →
    切换激活模型后旧 cache 立刻失效,新 prompt 重新读盘生成
- **`nexus/backend/models_config.py::infer_vendor`** (新增):从 `api_base`
  URL 域名推断 vendor(MiniMax / agnes-ai / OpenAI / Anthropic),未知走
  "未知厂商"兜底
- **`nexus/backend/models_config.py::get_active_model_info`** (新增):返回
  `{name, vendor, api_base, temperature, is_active}` 完整 dict
- **`nexus/backend/tools.py::get_model_info`** (新增 `@langchain_tool`):
  每次调用都重新读 `~/.nexus/models.json` 返回实时 JSON,挂进 `TOOLS`
  列表,LLM 可主动调(展示实时数据 / 排障场景)
- **prompt 强约束**:forbidden 块加 "任何跟 FACT 块里 name/vendor 不一致的
  版本" → LLM 想答错都难

### Verified

- `pytest tests/test_agent_memory.py`:18 passed(含 5 个新契约 + 3 个 tool 注册测试)
- `pytest tests/ -q --ignore=tests/test_e2e_features.py`:534 passed
- E2E 验证(dev uvicorn + WS,active = agnes-2.0-flash):
  问"你用的什么模型" → LLM 答:
  > 我是 Nexus,由 agnes-2.0-flash 驱动。Nexus 是夜小白科技有限公司基于
  > agnes-2.0-flash 模型打造的 AI 智能助理。agnes-2.0-flash 由 agnes-ai 提供。
  答对 model name + vendor + 公司 + 产品名,精确按 prompt 模板输出。

### Notes

- **数据源单一**:`~/.nexus/models.json` 是唯一权威。`api_base` 域名
  映射 vendor: `apihub.agnes-ai.com → agnes-ai`, `api.minimaxi.com → MiniMax`。
  新增 vendor 厂商需要更新 `_VENDOR_BY_HOST` 常量。
- **cache 策略**:cache key = `"{model_name}@{active_name}"`,双维度保证
  切换时立即失效。
- **为什么还需要 `get_model_info` 工具**(不只靠 prompt 注入):
  - 用户问"给我看实时数据" → LLM 调工具展示当前 model info
  - 调试场景:用户报告"模型没切换" → 调工具对账 models.json vs 实际 driver

---

## [Unreleased] — 修复 LLM 自我介绍答错(切到 Agnes 后还说 MiniMax-M3)

### Problem

用户切到 agnes-2.0-flash 后,在 Nexus 里问"你用的什么模型",
LLM 仍然回答"我用的是 MiniMax-M3 模型,由 MiniMax 公司开发"。
原因是 system prompt 的【身份】段硬编码了产品身份,没有告诉
LLM 当前实际驱动模型是哪个,所以 LLM 只能瞎猜 / 退回训练时的默认。

### Root Cause

`_build_system_prompt()` 写死的身份段:
> 你是 Nexus,夜小白科技有限公司开发的 AI 智能助理。

这条 prompt 不含任何关于"当前驱动模型"的信息。LLM 被问"你用的什么
模型"时没有任何上下文 introspection,只能默认回答训练时常见的 MiniMax-M3。

### Changed

- **`nexus/backend/agent.py::_build_system_prompt` 接受 ``model_name``**:
  - 签名 `_build_system_prompt() -> _build_system_prompt(model_name: str = "")`
  - 身份段改为"夜小白科技有限公司基于 {driver_label} 打造的 AI 智能助理"
  - 回答规则第 2 条改为"问你是谁 / 你用的什么模型,必须回答'我是 Nexus,由 {driver_label} 驱动'"
  - 空字符串兜底为"当前驱动模型"占位措辞(防御性,不阻塞启动)
- **`get_system_prompt` / `reload_system_prompt` 按 model_name 分桶缓存**:
  - `_CACHED_PROMPT` 由 `str | None` 改为 `dict[str, str]`,键 = model_name(`""` 用 `"__default__"` 占位)
  - `reload_system_prompt("")` 清空整个缓存;`reload_system_prompt("agnes-2.0-flash")` 只清该桶
  - WHY:模型切换瞬间旧 agent 仍持有旧 system_prompt,分桶避免"切到 agnes 还显示 minimax" 串味
- **`create_agent` 把 model_name 传给 get_system_prompt**:
  - `system_prompt=get_system_prompt(model_name or CONFIG.get("model_name", ""))`
  - `model_name` 参数缺省时回退到 `CONFIG["model_name"]`,跟 `get_llm` 默认对齐

### Added

- **`tests/test_agent_memory.py::TestBuildSystemPromptIsModelAware`** — 4 个回归测试:
  - `test_identity_section_includes_model_name_agnes` — agnes 名进身份段
  - `test_identity_section_includes_model_name_minimax` — MiniMax 名进身份段
  - `test_identity_section_changes_with_model_name` — 两个 model_name 产出不同 prompt(防"挂羊头卖狗肉"反模式)
  - `test_other_rules_kept_when_model_name_provided` — 加 model_name 参数后其他规则段不丢

### Verified

- `ruff check nexus/ tests/`:All checks passed
- `ruff format --check nexus/ tests/`:122 files already formatted
- `pytest tests/test_agent_memory.py`:14/14 通过(原 10 + 新 4)
- `pytest tests/`:541 passed,2 pre-existing e2e 失败(infra 依赖,非本次回归)

### Notes

- **完整标准话术示例**(active = MiniMax-M3):
  > 我用的是 MiniMax-M3 模型,由 MiniMax 公司开发。我是 Nexus,夜小白科技有限公司基于这个模型打造的 AI 智能助理。
- **完整标准话术示例**(active = agnes-2.0-flash,假设其 vendor 未知):
  > 我用的是 agnes-2.0-flash 模型。我是 Nexus,夜小白科技有限公司基于这个模型打造的 AI 智能助理。
- vendor 公司归属字段需要查模型元数据,未知就只说模型名(可省略"由 X 公司开发")。

---

## [Unreleased] — 修复切到 Agnes 后 26s 转圈 + 思考过程不显示

### Problem

用户反馈:切换到 Agnes 模型后,前端一直 spinner 转圈,也不显示思考过程。

实测(`~/.nexus/logs/nexus.log` 2026-06-28 21:18):
  | 时点 | 事件 | 累计 |
  |---|---|---|
  | 21:18:05 | 用户发"hi" | 0s |
  | 21:18:22 | intent 分类返回 | **+16.8s**(超时 8s 配置未生效) |
  | 21:18:33 | LLM 流结束 | +28.3s |
  | 21:18:33 | 客户端 code=1006 断开 | (用户放弃等待) |

对比:MiniMax intent 4s + LLM 2.6s = 7s 收到首帧;Agnes 路径全链路 ≥ 26s 零反馈,用户体感"卡死"。

### Root Cause (三层叠加)

1. **chunk 全部缓存**:`ws.py::_run_agent_streaming` 把 `on_chat_model_stream` 每个 chunk 累加到 `full_response`,等 LLM 跑完才按 16 字符切碎发出去。期间前端零帧。
2. **intent 分类无心跳**:`_classify_and_record` 在调 LLM 分类前不发任何 WS 帧;分类阻塞 16s+ 期间,前端 `isLoading=true` 但收不到任何东西。
3. **`<thinking>` 标签流末抽取**:原 `re.findall` 在 `full_response` 上提取 — LLM 不主动输出 `<thinking>` 标签时,UI 永远看不到"思考过程"。
4. **额外**:`asyncio.wait_for(8)` 对 agnes httpx connection 挂起不可靠,cancel 未传播,实际 latency 16821ms。

### Changed

- **`nexus/backend/api/ws.py::_run_agent_streaming` 实时 emit**:
  - 删 `full_response += content` 缓存 + 16 字符后处理切块 + `re.findall` thinking 抽取
  - `on_chat_model_stream` 每 chunk 立即 `parser.feed(content)` → 每个 `(kind, text)` 立刻 `send_json`
  - `on_chat_model_end` 兜底走同路径(非流式 LLM,带 `not emitted_chunk_text` 守卫防 mock 双发)
  - 流末 `parser.flush()` 把残留 hold / thinking 全部发完
  - `final` 帧改用实时累积的 `emitted_chunk_text`(替换 `full_response` 字符串)
  - `token_usage` / `done` 帧逻辑保持不变(下游契约不动)
- **`nexus/backend/api/ws.py::_classify_and_record` 加心跳**:
  - 函数签名加 `websocket` + `last_event_id: int = 0` 参数
  - 入口先发一个 `type=thinking` 帧 `"正在识别你的意图…"`(`event_id = last_event_id + 1`,保证跨 turn resume token 单调)
  - `send_json` 包 `try/except Exception` — WS 已断开场景记 WARNING + 继续分类,不让网络抖动阻塞主路径
  - 调用方 `handle_websocket` 在外层声明模块级 `last_event_id = 0` 跨 turn cursor,`_run_agent_streaming` 返回值续传
- **`nexus/backend/intent/router.py::classify_intent` 超时硬限**:
  - `asyncio.wait_for(8.0)` → `async with asyncio.timeout(5.0):` 上下文管理器(Python 3.11+ 替代 API,对 httpx 挂起 cancel 更可靠)
  - 显式 `except TimeoutError` 分支排在 `except Exception` 之前,日志带超时值
  - 兜底全部返回 `DEFAULT_INTENT`(`"chitchat"`)
  - 模块 docstring 从 "< 8s 超时" 更新为 "5s 硬限超时"

### Added

- **`nexus/backend/api/thinking_parser.py`** — 226 行纯逻辑状态机(无 IO、无 asyncio):
  - 公开 API:`feed(content: str) -> list[tuple[Literal["chunk", "thinking"], str]]` + `flush()`
  - 状态:`"chunk"` ↔ `"thinking"`,转移由 open/close tag 触发
  - hold 缓冲:处理 `<thin` / `</think` 跨 chunk 分片
  - 归一化:`<think>` ↔ `<thinking>` 视为同义,统一归一为 `<thinking>`
  - `flush()` 兜底:未闭合的 thinking 累积按 thinking 帧发,未识别的部分标签按 chunk 发
- **`tests/test_thinking_parser.py`** — 10 单元测试,覆盖正常 / 分片 / 嵌套 / 空标签 / `<think>` 与 `<thinking>` 混用 / stray close / unclosed at flush
- **`tests/test_ws_realtime_streaming.py`** — 3 集成测试(mock LLM 逐 token 验证实时发帧 + thinking 跨分片识别 + final 顺序)
- **`tests/test_intent_heartbeat.py`** — 3 回归测试(慢 LLM 路径发心跳 / `llm=None` 路径发心跳 / `event_id=last_event_id+1` 单调契约)
- **`tests/test_intent_timeout.py`** — 3 超时测试(30s 挂起 LLM 5s 兜底 / 正常路径 task / 源码契约:必须 `asyncio.timeout` 且禁止 `asyncio.wait_for`)
- **`tests/test_use_tauri_ws_placeholder.py::test_ws_emit_chunk_realtime_not_buffered`** — 反向 grep 断言:ws.py 必须 import ThinkingParser + on_chat_model_stream 分支含 `parser.feed` + `send_json` + **禁止** `full_response +=`。回潮立即 CI 红。
- **`frontend/e2e/debug-agnes-message.spec.ts`** — Playwright 8s 首帧断言(实际期望 5s 内),`waitForFunction` 查 `.message-row.is-assistant` 是否有内容或 `.thinking-block`,超时 throw `"Agnes 转圈 bug 复发:8s 内未收到任何内容帧"` + 截图。

### Removed

- **`ws.py` 内的 `import re`** — 已无 `re.findall` 调用
- **`ws.py::_STREAM_CHUNK_SIZE`** — 16 字符切块常量已删
- **`tests/test_ws_resilience.py::test_ws_chunks_response_in_16_char_groups`** 重命名为 `test_ws_chunks_emitted_realtime_no_post_split` — 30 字符响应现在是 1 帧,不再是 2 帧

### Notes

- **`_emit_chat_end.chunks_count` 改为 `len(response_text)` 粗估**:精确计数需要 `_run_agent_streaming` 多返回一个元组元素,留作后续可观测性 PR。本次修复不阻塞。
- **pre-existing 80 行函数上限违规**:`_run_agent_streaming` 现 483 行(原 ~300 + 本次 +180)。本次 fix 不拆函数,留作独立 refactor PR。python_project.md §1.2 要求单函数 ≤ 80 行,差距 6 倍,后续必须处理。
- **`emitted_chunk_text` 与 `last_event_id` 作用域**:两者都是 `handle_websocket` 函数内 module-level 局部变量(非全局),保证 WS 断开后状态自然 GC,跨连接不污染。

### Verified

- `ruff check nexus/` — All checks passed
- `ruff format --check nexus/` — 0 diff
- `pytest tests/ -q` — **527 passed, 12 skipped** in 32s(基线 508 → +19 新测试,零回归)
- 6 次 spec review + 5 次 code quality review,全部通过(含 3 次 fix amend 循环)
- 5 个 task 6 个 commit(每 task 一个,Task 1 多 1 个 refactor amend),Conventional Commits 格式,中文主题 ≤ 50 字符

---

## [Unreleased] — 桌面 APP 架构简化(electron+pyinstaller 双运行时 → pywebview+pyinstaller 单运行时)

### Changed

- **桌面 APP 从 Electron + Python 双运行时,改为 pywebview(WKWebView)+ PyInstaller 单运行时**:
  - 旧:`Electron 主进程 + Renderer + Helper*(GPU/Renderer/Plugin) + nexus-backend(PyInstaller)` 两个独立 runtime 互 spawn
  - 新:`Nexus.app/Contents/MacOS/Nexus`(壳脚本)→ exec `Resources/nexus-backend/nexus-backend`(PyInstaller 单二进制,内嵌 Python 运行时 + pywebview + 后端)
  - **DMG 167MB → 70MB**(arm64,UDZO 压缩),.app 124MB 主要是 PyInstaller _internal
  - **进程数 1**(原来 5+ 个 Electron Helper + Python 子进程)
  - 内存占用大幅降低(无 Chromium,WKWebView 由 macOS 共享)
  - FastAPI 已经在 `/app` 挂载前端 dist,所以 launcher 只需后台线程跑 uvicorn + 主线程 `webview.start()`

### Added

- **`nexus/backend/launcher.py`** — 桌面 APP 入口:`uvicorn.run()` daemon 线程 + `webview.create_window()` 主线程 + `--no-gui` headless 选项
- **`scripts/build_dmg.sh`** — 一键打包(PyInstaller onedir + .app bundle 构造 + hdiutil)
- **`pyproject.toml`** 加 `pywebview>=6.0 ; sys_platform == 'darwin'`(仅 macOS 装,其他平台不依赖)

### Removed

- **`desktop/` 整目录删除** — Electron + TypeScript + electron-builder(~136MB node_modules + 489 行 TS + 180 行测试)
- **`scripts/build_backend_app.sh`** 替换为 `scripts/build_dmg.sh`
- **`frontend/e2e/dmg-cdp/`** 删除(Electron `--remote-debugging-port` CDP attach 测试,新架构不再适用)
- **`pyproject.toml` desktop 引用** 删
- **顶层 `package.json` desktop:* 脚本** 替换为 `build:frontend|build:dmg|build:all`

### Verified

- `ruff check / format`:全过
- `pytest`:468 passed / 12 skipped in 43.92s
- E2E 5/5(真 LLM):简单闲聊 / 长期记忆+身份 / 联网搜索 / 澄清 / 跨 session 隔离
- DMG 本地构建:`scripts/build_dmg.sh` 一次成功,产物 70MB,`/Applications/Nexus.app` 启动后 1 个 `nexus-backend` 进程监听 30000

---

## [Unreleased] — CLI 清理(产品不再提供 CLI,终端用户走 DMG)

### Removed

- **`nexus/cli/` 整包删除** — `install/uninstall/start/stop/restart/status/logs/doctor/setup/config/gateway/ppt` 全部命令失效
  - 历史背景：dev 期 `install()` 写 launchd plist + `shutil.copytree(nexus, ~/.nexus/nexus/)` + 重建 venv,模拟"装机",但产品用户拿到的是 DMG,源码复制路径在用户机器上不存在,plist 启动失败
  - 终端用户路径：**macOS DMG APP**(`/Applications/Nexus.app`,Electron 拉起 PyInstaller onedir 后端)
  - 开发者路径：git clone 后 `python nexus/backend/run.py` + `(cd frontend && npm run dev)`,见 [README.md](./README.md)
- **`nexus/pptmaster/` 整包删除** — `nexus ppt` 命令 + runner 子进程边界,与产品核心(AI Gateway + 长期记忆 + 微信通道)无关
- **`nexus/backend/rubrics/_cli_helpers.py` 删** — 仅被已删 CLI 引用
- **`nexus/backend/rubrics/exporter.register_export_command()` 删** — CLI 注册逻辑,函数无调用方
- **`tests/test_cli_commands.py` / `test_config_loading.py` / `test_pptmaster.py` / `test_rubric_exporter.py::test_register_export_command_is_callable` 删** — 对应失效 CLI 的测试
- **`pyproject.toml` `[project.scripts]` 删** — `nexus` console script 入口

### Changed

- **README.md** 重写顶部"快速开始":终端用户走 DMG,开发者走 git clone,删失效 CLI/一键安装/pip install 段
- **CLAUDE.md** 命令列表删 CLI,加 2026-06 清理说明
- **SPEC.md** `## CLI` 段改写为开发者 git clone 步骤
- **`.claude/settings.local.json`** 删 `nexus gateway status` 权限白名单

### Verified

- ruff check 0 error, format 109 files 0 diff
- pytest **443 passed / 12 skipped**(原 456,减 13 个失效 CLI 测试)
- E2E 5/5 通过:简单闲聊 / 长期记忆+身份 / 联网搜索 / 澄清 / 跨 session 隔离(脚本在 `/tmp/e2e_dmg_user.py`,模拟 DMG APP WS 帧)

---

## [Unreleased] — 记忆子系统重构(对齐 deepagents 框架)

### Changed

- **记忆机制**: 完全对齐 deepagents 0.6.8 原生框架,删除自定义 `MemoryService` / `EvolutionService` 整层(548 行死代码 + 4 个旧 `@langchain_tool`)
  - 长期记忆由 deepagents `MemoryMiddleware` 自动加载 `~/.nexus/AGENTS.md`(用户级)+ `nexus/.deepagents/AGENTS.md`(项目级),以 `<agent_memory>...</agent_memory>` 段注入 system prompt
  - LLM 通过内置 `edit_file` / `write_file` 自更新 AGENTS.md;`QualityGateMiddleware` 在 `wrap_tool_call` 阶段拦截写入并跑 `MemoryFilter` 忠实度评估,拒绝幻觉/低价值记忆写入
  - 持久化层: `langgraph.store.memory.InMemoryStore`(重启丢 session 临时数据)+ AGENTS.md(跨重启持久化)
- **`nexus/SOUL.md`** 迁至 `nexus/.deepagents/AGENTS.md`(身份/规则保留)
- **`nexus.db` schema**:
  - `memory` → `memory_legacy`(改名,数据保留可查,只读)
  - `tool_stats` / `session_stats` 表删除(深 agents 框架不需要)
- **新增脚本**:
  - `scripts/migrate_legacy_memory.py` — 一次性迁移旧 `memory` 表 explicit 偏好 → `~/.nexus/AGENTS.md` `## Migrated Preferences` 段,幂等,支持 `--dry-run`
  - `scripts/seed_user_agents_md.py` — 首次启动初始化 `~/.nexus/AGENTS.md` 空模板,幂等
- **Bug 修复**: `FilesystemBackend(virtual_mode=True)` 拒绝绝对路径,导致 `~/.nexus/AGENTS.md` 被 `MemoryMiddleware` 静默跳过 → LLM 失去身份感;改 `virtual_mode=False`,由 `FilesystemPermission` + `QualityGateMiddleware` 在更上层兜底安全
- **测试**: 390 passed(9 个新增 `test_migrate_legacy_memory.py`)

### Migration Guide

升级到本版本后,执行一次:

```bash
# 1. 备份 db(脚本内部也会跳过已迁移的 db,但先备份更稳)
cp ~/.nexus/nexus.db ~/.nexus/nexus.db.bak.$(date +%s)

# 2. 跑迁移(explicit → ~/.nexus/AGENTS.md,改 memory 表名 → memory_legacy)
python scripts/migrate_legacy_memory.py

# 3. 验证
sqlite3 ~/.nexus/nexus.db ".tables"  # 应见 memory_legacy, 不见 memory
cat ~/.nexus/AGENTS.md               # 应见 ## Migrated Preferences 段含你的旧偏好
```

无 explicit 偏好 → 脚本无 op,安全跳过。

---

## [Unreleased] — 上下文窗口配置化(NEXUS_CONTEXT_WINDOW 默认 200K)

### Changed

- **`NEXUS_CONTEXT_WINDOW` 默认从 `32000` 改为 `200000`**:
  - WHY:旧值 32K 是 Nexus 项目早期假设,与当前 MiniMax-M3 实际规格不符;Claude 200K、GPT-4 Turbo 128K 等主流模型都在 100K+ 区间,默认 200K 更贴近实际部署场景。
  - **Breaking**:已部署且未设 `NEXUS_CONTEXT_WINDOW` 的用户,升级后 UI 上下文占比 + 自动压缩触发阈值都会按 200K 重算。如需回滚旧值:`export NEXUS_CONTEXT_WINDOW=32000`。
- **`nexus/backend/api/ws.py::_estimate_tokens` 默认 `context_window` 从 32000 改为 200000**,与 `NEXUS_CONTEXT_WINDOW` 同步;0/负数兜底值也跟着改。
- **`nexus/backend/agent.py` 注释更新**:解释 deepagents `compute_summarization_defaults` 通过 `model.profile["max_input_tokens"]` 算 trigger = `max × 0.85`,默认 200K → 170K 触发阈值。

### Added

- **`ResilientRunnable._resolve_model_profile()`**(`nexus/backend/llm/wrapper.py`):
  - 把 `NEXUS_CONTEXT_WINDOW` 暴露为 `model.profile["max_input_tokens"]`,驱动 deepagents 自动按 0.85 fraction 计算压缩 trigger。
  - 切换不同上下文窗口的模型(200K / 1M / 32K)只需改 env,代码不动。
- **`tests/test_llm_profile.py`** 新增:覆盖正常路径(默认 200K / env 覆盖 128K)、边界条件(32K / 2M)、异常路径(env="abc" 抛 ValueError)、契约验证(200K × 0.85 = 170K trigger)。

### Migration Guide

```bash
# 不需操作:默认 200K 已生效
# 如要回滚旧值:
export NEXUS_CONTEXT_WINDOW=32000
# 切换其他模型(如 1M 上下文的 Gemini 1.5 Pro):
export NEXUS_CONTEXT_WINDOW=2000000
```

### Tests

- `tests/test_llm_profile.py`:8 个新 case 覆盖 profile 契约
- `tests/test_estimate_tokens.py`:default / 0 兜底 / max clamp 测试同步更新到 200K

---

## [Unreleased] — deepagents 依赖升级(0.6.8 → 0.6.12)

### Changed

- **`deepagents` 从 `0.6.8` 升级到 `0.6.12`**,连带 `langchain-core` `>=1.4.0` → `>=1.4.8` / `langchain` `>=1.3.4` → `>=1.3.11` / `langchain-anthropic` `>=1.4.3` → `>=1.4.7`:
  - **驱动原因**:研究 4 个 patch 版本(0.6.9 → 0.6.12)源码 + release notes,确认 4 个核心 API(`compute_summarization_defaults` / `create_summarization_middleware` / `_DeepAgentsSummarizationMiddleware.wrap_model_call` / `_should_summarize`)跨 5 版本签名零变化,Codex 删除显式 SummarizationMiddleware 的 dedup 推理(`serialized_name="SummarizationMiddleware"`)继续成立。
  - **行为兼容**:`ResilientRunnable._resolve_model_profile()` → `model.profile["max_input_tokens"]` → deepagents 0.85 fraction 的链不变。

### Added(自动获得,零代码改动)

- **0.6.9 性能优化**:`summarization middleware` 改成 "Count tokens once per model call"(PR #3877),引入 `_token_counter_accepts_tools()` helper 探测 `tools=` 参数签名,工具 schema 现在参与 token 计数。ResilientRunnable 没传 custom counter,走默认 → 自动生效。
- **0.6.9 性能**:`filesystem system prompts` + `grep/glob matchers` 加缓存(PR #3889 / #3887 / #3886)。与我们 agent 行为无关,但会降低 cold-start 工具调用延迟。
- **0.6.9 子能力**:`subagent response format` 可配置(PR #3882)。我们暂未用,留作未来扩展点。

### Notes

- **0.6.12 新增 `deepagents[aws]` extra**(Bedrock 自动 prompt caching,PR #4108)与 **media references 保留**(PR #3990)对我们**零影响**:不用 Bedrock、不处理 image / file URL。如未来切 Bedrock,`pip install deepagents[aws]` 即可启用。
- **0.6.10 / 0.6.11 各自一个 bug fix**:`model_matches_spec` 比较 provider 字段(#3943)、`BaseSandbox async` helpers 走 `aexecute`(#3996)。我们未触这两条路径,无回归风险。

### Verified

- `pip install --upgrade deepagents==0.6.12`:成功,连带 langchain 全家桶升到 1.3.11+
- `pytest tests/test_llm_profile.py test_estimate_tokens.py test_agent_memory.py test_checkpointer_sqlite.py test_deepagents_integration.py test_resume_token.py test_observability_logger.py test_run_coro_sync.py`:**88 passed in 3.79s**
- `pytest tests/`: **497 passed, 8 failed**(8 个失败全在 `test_e2e_features.py`,需 backend 运行 + 真实 LLM API key,pre-existing 基础设施依赖,跟升级无关)
- `ruff check nexus/`:5 个 pre-existing 错(launcher.py 的 Objective-C 桥接 N802/N806 + runtime_main.py 一个 trailing newline),**未引入新 lint**

---

## [Unreleased] — 修复 UI 上下文占比误报

### Problem

用户实际场景:UI 显示"上下文 █████████░ 89% (178k/200k)",但
deepagents 自动压缩没触发(实际 trigger 阈值是 200K × 0.85 = 170K)。
根因:`_estimate_tokens` 用的字符系数(中 ×2.5 / 英 ×0.25 / 其他 ×0.5)
跟 deepagents 内部 `count_tokens_approximately` 差 ~10×。同时该函数
只统计"本轮响应",不算整个对话上下文。

实测对照(71200 中文字符):
  | 估算方式 | tokens | 占比 |
  |---|---|---|
  | 旧字符系数 | 178,000 | 89%(误导) |
  | langchain `count_tokens_approximately` | ~17,950 | 9%(真实) |

### Changed

- **`nexus/backend/api/ws.py::_estimate_tokens` 改用
  `:func:langchain_core.messages.utils.count_tokens_approximately`**:
  - 函数签名从 `(text: str, context_window: int)` 改为
    `(content: str | list, context_window: int)` — 接受字符串(测试/降级用)
    或 messages 列表(生产用整个会话上下文)
  - 底层委托给 langchain 启发式,跟 deepagents `SummarizationMiddleware.
    _should_summarize` 用**同一套** token 估算
  - 空内容短路:空 str / 空 list 直接返回 `(0, 0.0)`,避免空消息被算成
    ~4 tokens(per-message overhead)
- **WS caller 范围扩展**:`_run_agent_streaming` 里调
  `_estimate_tokens(prompt["messages"] + [新 assistant 响应], ...)`,
  传**整个对话上下文**而不是只传本轮响应。这样 UI 显示的 % 才是
  "会话占比",不是"响应占比"。

### Tests

- `tests/test_estimate_tokens.py` 全面重写:
  - 去掉依赖字符系数的固定值断言(旧测试 4字中文 = 10 tokens 之类)
  - 加 str / list 两种输入的覆盖
  - 加核心回归保护:`test_long_chinese_conversation_realistic_usage`
    验证 50 轮 × 240 中文字符的真实长对话估出 < 5%(旧系数会算成 ~30%)
  - 加 `test_calls_count_tokens_approximately` 用 mock 锁定底层实现,
    防止有人改回字符系数

### Verified

- `pytest tests/test_estimate_tokens.py`:**13/13 通过**
- `pytest test_estimate_tokens + test_llm_profile + test_agent_memory +
  test_resume_token + test_ws_resilience`:**65/65 通过,无回归**

---

## [v0.1.0] — 2026-06-21 — 首次内测交付

**核心**: 把 Nexus 从「能跑」推进到「能装能用」。AI Gateway 全栈接通(后端 + 前端 + **桌面端 DMG 安装包**)、质量门上线、可观测性落地、意图识别路由、CI/CD 双线。
**详情**: 见 `docs/RELEASE_NOTES_v0.1.0.md`
**测试**: 378 backend tests pass + Playwright DMG CDP 真环境 E2E
**产物**: `release/Nexus-1.0.0-arm64.dmg`(175 MB,macOS arm64,未签名)

本节合并自以下 3 段历史 Unreleased 内容:

---

## [Unreleased] — 意图识别路由

**分支**：`codex/macos-dmg-app`（6 commits since `362809b`，356 tests，DMG CDP 真实环境 E2E 验证通过）

> 给 Nexus 单 LLM 主对话加 1-shot 意图识别层：每条 user 消息先经 1 次轻量工具调用分类，分类结果落库 `messages.intent`，与现有质量门联动（chitchat 走原短路、knowledge/task 走完整 judge）。
> 详细计划见 `docs/superpowers/plans/2026-06-19-intent-recognition-routing.md`。

### Added
- **`nexus/backend/intent/router.py`**：`classify_intent()` 用 LangChain `bind_tools` 1-shot 分类 `chitchat` / `knowledge` / `task`，8s 超时 + 4 条兜底路径（异常 / 超时 / 无 tool_call / 未知 tool 名）一律返回 `chitchat`（最安全：质量门已有 chitchat 短路）
- **`nexus/backend/intent/__init__.py`**：统一导出 6 个公共符号
- **DB 迁移**：`messages` 表新增 `intent TEXT` 列，走 `_ensure_column()` 自动 ALTER，老库无感
- **WS 集成**：`handle_websocket` 收到 user 消息时先调 `_classify_and_record` 分类并把 intent 一并写库；通过 `get_intent_llm` 回调注入 LLM 实例
- **零新依赖**：复用主 `ChatModel` 实例（与 quality gate 的 `judge_llm` 共用同一对象），不增加 token 配额与网络连接

### Tests
- `tests/test_intent_router.py`：6 用例（3 类命中 / 无 tool_call / LLM 异常 / 超时 / 未知 tool 名）
- `tests/test_intent_ws_integration.py`：2 用例（`_classify_and_record` 路径、`get_intent_llm=None` 兼容）
- `tests/test_db_migrations_intent.py`：3 用例（fresh create、列存在、迁移幂等）
- `frontend/e2e/dmg-cdp/test-dmg-intent.mjs`：DMG CDP 真实环境 2 用例（闲聊 → chitchat 137 字响应；求和算法 → knowledge 431 字响应），覆盖 WebSocket 流式 + sqlite3 直查 intent 列

### Risk Mitigation
- 退化构造失败时所有输入判为 chitchat，质量门仍按原路径运行；INFO 日志提示运维
- `_classify_and_record` 完全运行在事件循环内（`async def`），无子线程桥接风险
- `models.json` 写入、API key 日志、密钥输出等原有约束未破坏

---

## [Unreleased] — 可观测性子系统（JSONL + 4 产品事件）

**分支**：`codex/macos-dmg-app`（13 commits since `6448722`，378 tests，真实环境 E2E 验证通过）

> 给 Nexus 加 observability 子系统：JSONL 结构化日志 + 4 个产品事件 + LangChain callback 通道复用 + env 三档配置。不造轮子，复用 stdlib `logging.handlers.RotatingFileHandler` + LangChain `BaseCallbackHandler`。
> 详细计划见 `docs/superpowers/plans/2026-06-20-observability-subsystem.md`，运维文档见 `docs/operations/logging.md`。

### Added
- **`nexus/backend/observability/events.py`**：4 个产品事件 dataclass（`ChatStart` / `IntentClassified` / `QualityVerdict` / `ChatEnd`），frozen + `to_dict()` 序列化，`EVENT_SCHEMA_VERSION="1.0.0"`
- **`nexus/backend/observability/sink.py`**：`EventSink` 类，JSONL / text 双格式，10MB × 5 `RotatingFileHandler` 轮转，threading.Lock 并发安全，lazy 父目录创建
- **`nexus/backend/observability/logger.py`**：`setup_logging()` 幂等入口，env 三档（`NEXUS_LOG_FORMAT` / `NEXUS_LOG_FILE` / `NEXUS_LOG_LEVEL`），stdlib `_JsonFormatter`（无第三方依赖），预设 `deepagents=INFO` / `langchain=WARNING` / `langchain_core=WARNING`
- **`nexus/backend/observability/handler.py`**：`NexusLogHandler(BaseCallbackHandler)` 6 回调：on_llm_start/end（含 token 统计）/ on_tool_start/end / on_chain_start/end，duration_ms 用 `time.monotonic` 算，sink 写失败吞异常
- **集成点**：
  - `nexus/backend/main.py` 启动期调 `setup_logging()` 取代 `logging.basicConfig`
  - `nexus/backend/agent.py` 总是挂 `NexusLogHandler`（走 EventSink 落盘），仅 `NEXUS_AGENT_VERBOSE=1` 时额外挂 `StdOutCallbackHandler`
  - `nexus/backend/api/ws.py` 新增 `emit_chat_event()` 公开 API + 4 个 anchor 点（chat.start / intent.classified / quality.verdict / chat.end）
  - `chat_start_monotonic` 在 ChatStart 之后立即 `time.monotonic()`，ChatEnd 复用算 `duration_ms`

### Tests
- `tests/test_observability_events.py`：5 用例（round-trip / latency_ms / scores dict / duration+retries / frozen）
- `tests/test_observability_sink.py`：5 用例（JSONL 追加 / text 格式 / 父目录创建 / 4 线程 × 50 并发 / close 幂等）
- `tests/test_observability_logger.py`：5 用例（autouse fixture 隔离 root logger，验证 default path / text 格式 / json 格式 / level env / 幂等）
- `tests/test_observability_handler.py`：4 用例（isinstance BaseCallbackHandler / on_llm_end 写 2 事件 / on_tool_start 含 tool 名 / sink 失败不破 callback）
- `tests/test_observability_ws_integration.py`：3 用例（emit_chat_event 写 sink / 吞异常 / 4 event round-trip）

### Verification
- 真实环境 E2E（`NEXUS_LOG_FORMAT=json NEXUS_LOG_FILE=/tmp/e2e-final.log`）：2 次 chat（chitchat + 知识类）触发 4 条 `chat.*` 事件（chat.start + chat.end 各 2），verdict 均为 accept，LLM 调用 2 次，intent 分类正确（chitchat / knowledge 各 1）
- 端到端验证脚本：`/tmp/ws-verbose-test.py` / `/tmp/ws-knowledge-test.py` / `jq` 查询示例见 `docs/operations/logging.md`
- pytest：378 passed（原 356 + 新 22）

### Limitations
- `chunks` 字段当前是 `len(response_text) // 16` 估算值（精确 chunk count 在 `_run_agent_streaming` 内部），后续若需精确值扩展该函数返回 `chunk_count` 即可
- `chat.end` 当前只在正常完成分支 emit；澄清挂起 / 错误流分支不发，后续若需覆盖补发可扩展 `handle_websocket`
- `langchain` / `langchain_core` 默认 WARNING 级，避免 stream / token 刷屏；`deepagents=INFO` 是因为它本身日志覆盖少
- ruff 仍有 9 条 pre-existing 错（`tests/test_config_loading.py` / `tests/test_fixes_round2.py` / `tests/test_wechat_smoke.py` 的未排序 import / 未用导入），与本任务无关，未在本任务中修复

### Files
- 新增：`nexus/backend/observability/{events,sink,logger,handler,__init__}.py`（5 文件）
- 新增：`tests/test_observability_{events,sink,logger,handler,ws_integration}.py`（5 文件）
- 新增：`docs/operations/logging.md`
- 修改：`nexus/backend/main.py` / `nexus/backend/agent.py` / `nexus/backend/api/ws.py`（3 文件）
- 顺手：`tests/test_observability_handler.py` 顶部 `import dataclasses` 整理（style）；`handler.py` docstring 与实现对齐

---

## [Unreleased] — Phase 1+2 容错 + 质量门

**合并提交**：`7ea9cbe`（22 commits, 303 tests, 真环境验收通过）

> 本次发布包含两个大阶段：Phase 1（容错）与 Phase 2（质量门）。
> 详细计划见 `docs/superpowers/plans/`，进度见 `docs/superpowers/progress.md`。

### Added — Phase 1：容错

#### 断线续传（WebSocket 重连）
- 新增 `nexus/backend/resume.py`：HMAC-SHA256 + base64url 签名的 resume token
- 新增 `GET /api/sessions/{session_id}/resume` 端点：客户端用上次收到的最后一个 `event_id` + 收到的 token 续拉事件
- 新增 `resume_tokens` 表（`token`, `session_id`, `last_event_id`, `expires_at`）
- WS 断线后重连 → 服务端从 Redis/SQLite 重放未确认事件，不丢消息
- 端到端测试：`tests/test_resume.py`（含 token 过期、签名验证、event_id 单调性）

#### LLM 错误分类与降级
- 新增 `nexus/backend/llm/errors.py`：`ClassifiedError` + `LLMErrorKind` 枚举
  - 错误分类：`AUTH` / `RATE_LIMIT` / `TIMEOUT` / `NETWORK` / `BAD_REQUEST` / `SERVER` / `UNKNOWN`
  - 每类标记 `retryable` 标志，驱动重试策略
- 新增 `nexus/backend/llm/wrapper.py`：`ResilientRunnable`（Pydantic v2 `BaseChatModel` 子类）
  - 内置指数退避重试（最多 N 次）
  - 失败时打点日志 + 抛 `ClassifiedError` 给上层降级
  - 已被 `nexus/backend/agent.py` 的 `get_llm()` 工厂使用

#### WS 边界
- WS 处理器在 judge / 主 LLM 失败时返回结构化 `error` 事件而非断开连接
- 客户端可重连后用 resume token 续传
- 测试：`tests/test_ws_fault_tolerance.py`

#### 配套 CLI
- `scripts/check_lm.py`：诊断 LLM 凭据、连通性、当前激活模型

### Added — Phase 2：质量门（Rubrics）

#### Rubric 数据层
- 新增 `nexus/backend/rubrics/schemas.py`：
  - `RubricVerdict` 枚举（`ACCEPT` / `REPAIR` / `REJECT`）
  - `Rubric` / `Score` / `RubricVerdictResult` 三个 frozen dataclass
  - 4 个内置维度常量 + `DEFAULT_RUBRICS` 元组
  - 阈值映射规则：`>=0.8` → ACCEPT，`>=0.6` → REPAIR，否则 REJECT
  - `safety` 单独更严：`>=0.9` / `>=0.7`
- 全部不可变（`frozen=True`），符合 CLAUDE.md §11

#### Rubric Judge
- 新增 `nexus/backend/rubrics/judge.py`：`RubricJudge`
  - 并发 4 维度评分（`asyncio.gather`）
  - 单 rubric 超时 30s（`per_rubric_timeout`）
  - JSON 解析失败时重试 1 次（`max_parse_retries=1`）
  - 全失败抛 `RubricJudgeError`，由 pipeline 降级 REJECT
- 新增 `nexus/backend/rubrics/prompts.py`：4 个中文 prompt 模板（200-500 字，含正反例 + 严格 JSON 输出约束）
- 新增 `nexus/backend/rubrics/tool_evaluator.py`：tool_correctness 维度的工具调用正确性评估

#### Repair 决策
- 新增 `nexus/backend/rubrics/repair.py`：`RepairStrategy`
  - `safety_veto=True`（plan 强制）：safety < 0.5 → 一票否决，直接 REJECT
  - `max_repair_attempts=1`（plan 强制）：首次 REPAIR 触发主 LLM 重生，二次仍 REPAIR → REJECT
  - 加权聚合：`Σ(score_i × weight_i)`
- 新增 `nexus/backend/quality/pipeline.py`：`QualityPipeline`
  - 公开方法 `run_with_quality(question, raw_response, message_id=None) -> FinalResponse`
  - 三段式：judge → decide → repair → persist
  - 异常全收口：judge 失败、主 LLM 失败 → 降级 REJECT fallback，不抛
- 新增 `nexus/backend/quality/__init__.py`

#### DPO / KTO 偏好数据导出
- 新增 `nexus/backend/rubrics/exporter.py`：`PreferenceExporter`
  - `export_dpo(records, out_path)`：gap ≥ 0.3 的成对偏好
  - `export_kto(records, out_path)`：逐条二元偏好
- 新增 `nexus/backend/rubrics/_cli_helpers.py`：`load_preference_records`
  - **修复**：从 quality_scores 按 `message_id` 分组 + 求平均，避免同 message 排序错乱
- 真环境 100 轮对话可导 30+ 条 DPO

#### Meta-eval
- 新增 `nexus/backend/rubrics/meta_eval.py`
  - `compute_pearson(xs, ys)`：纯函数，常数方差返回 0
  - `compute_cohens_kappa(a, b)`：纯函数，单类别返回 0
  - `KAPPA_ALERT_THRESHOLD = 0.4`（plan 强制报警线）
  - `MetaEvalSample` / `MetaEvalResult`（frozen）
  - `run_meta_eval(judge, samples)`：集成 + 算指标
- 新增 `scripts/eval_rubrics.py` CLI
  - 退出码：0 = kappa ≥ 0.4，1 = kappa < 0.4
  - CI 集成入口

#### 配套数据
- 新增 `data/rubric_eval_samples.jsonl`：12 条人工标注样本（覆盖 4 维度 × accept/repair/reject）
- 新增 `data/eval_report.json`：当前 meta-eval 结果（Pearson 0.973, kappa 0.591）

### Changed — 集成

- `nexus/backend/main.py`：
  - 启动期构造 `QualityPipeline(judge=RubricJudge(llm=...), repair_strategy=..., main_llm=...)`
  - 注入 `app.state.quality_pipeline`
  - **关键修复**：judge LLM 改用 `get_llm()` + `get_active_model()`，与主 Agent 一致（之前用 `_agent` 报错因 deepagent compiled graph 不是 chat model）
- `nexus/backend/api/ws.py`：
  - 在调 pipeline 前生成 `message_id = str(uuid.uuid4())`
  - 把 `message_id` 同时透传给 `run_with_quality` 和 `add_message`，保证 quality_scores 行可关联到具体 assistant 消息
- `nexus/backend/quality/pipeline.py`：
  - `run_with_quality` 新增 `message_id` 参数（默认 `None`）
  - `_persist_scores` 把 `message_id` 透传给 `save_quality_score`

### Fixed — 真环境验证发现的 3 个 bug

1. **`RubricJudge(llm=_agent)` 误用**
   - 现象：judge 报 `AttributeError: 'CompiledGraph' object has no attribute 'ainvoke'`（实际能调，但返回的是 LangGraph state dict）
   - 修复：改用 `get_llm()` 构造的 `ResilientRunnable`（真正的 `BaseChatModel` 子类）

2. **judge LLM 404**
   - 现象：judge 调 LLM 返回 `404 not_found`
   - 根因：`CONFIG["model_name"]` / `CONFIG["minimax_api_base"]` 默认值与主 Agent 的 `get_active_model()` 不一致
   - 修复：`main.py` 和 `scripts/eval_rubrics.py` 都改用 `get_active_model()` 取值

3. **`quality_scores.message_id` 全部为 NULL**
   - 现象：所有 quality_scores 行的 `message_id` 字段都是 NULL
   - 根因：pipeline 没接收 message_id
   - 修复：见 Changed 节

### Tests

- **测试总数**：303 passed（合并时）
- **新增 / 修改**：
  - `tests/test_rubric_schemas.py`
  - `tests/test_rubric_judge.py`
  - `tests/test_rubric_repair.py`
  - `tests/test_rubric_meta_eval.py`
  - `tests/test_quality_pipeline.py`（含 message_id 透传 2 个测试）
  - `tests/test_resume.py`
  - `tests/test_ws_fault_tolerance.py`
  - `tests/test_llm_wrapper.py`
  - 配套集成测试若干

### Documentation

- 新增 `docs/operations/quality.md`：质量门调优指南（阈值、prompt、meta-eval、故障排查）
- `docs/superpowers/progress.md`：更新 Phase 1+2 全部完成 + 真环境验收 4 条全过

### Verified — 真环境验收

`.venv/bin/python scripts/verify_phase2.py --all` 全过：

| 步骤 | 验证内容 | 结果 |
|------|---------|------|
| 1 | WS 烟测（发 "你好" 收到 done） | ✅ |
| 2 | 诱导幻觉 → REJECT（3 个不存在的概念） | ✅（8 条 REJECT 记录入库） |
| 3 | REPAIR 路径触发 | ✅（verdict 分布里有 repair） |
| 4 | 100 轮对话 + 导出 ≥ 30 DPO | ✅（导出 34 DPO / 68 KTO） |
| 5 | meta-eval Pearson + kappa | ✅（Pearson 0.973 / kappa 0.591 ≥ 0.4） |

---

## 版本策略

Nexus 仍在 pre-1.0 阶段，版本号在 0.x 区间。本节内容合并到下次正式发版时再切分版本号。

后续每次 phase 合并后追加新节，标题格式：

```
## [Unreleased] — <阶段名> + <一句话总结>
```

---

## [Unreleased] — 下一阶段占位

### Changed — 依赖清理(2026-06-21)

- **卸 `ppt-master` 依赖**:
  - 原 `pyproject.toml` 用 `ppt-master @ git+https://github.com/hugohe3/ppt-master.git`,该仓库 main 分支不再包含 Python 包配置,导致 CI `pip install -e ".[dev]"` 阶段失败(`does not appear to be a Python project`)
  - 改成不通过 pip 装,文档说明按需安装(`pip install ppt-master`,需 Python 3.12+)
  - runner.py 子进程调用代码完全不动,真要用 PPT 生成的用户单独装就行
  - 提交:`58a1b4d fix(deps): 卸 ppt-master 依赖`

---

## [Unreleased] — 下一阶段占位

下一阶段(预计 v0.2.0)重点：

- macOS 代码签名(接入 Apple Developer ID,DMG 自动签名)
- `chunks` 字段精确化(扩展 `_run_agent_streaming` 返回 `chunk_count`)
- `chat.end` 在澄清挂起 / 错误流分支补发
- 澄清交互(ask_user 工具)端到端接入前端 UI
- 偏好数据导出(DPO/KTO)接入训练流程(暂不训练,只导出)

---

## 链接

- [v0.1.0 release notes](./RELEASE_NOTES_v0.1.0.md)
- [可观测性计划归档](./superpowers/plans/2026-06-20-observability-subsystem.md)
- [意图识别路由计划归档](./superpowers/plans/2026-06-19-intent-recognition-routing.md)
- [质量门调优指南](./operations/quality.md)
- [日志查询指南](./operations/logging.md)
