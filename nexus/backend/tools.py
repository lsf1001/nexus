import datetime
import logging
import os
import shlex
import subprocess
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_core.tools import tool as langchain_tool

from .config import CONFIG
from .mcp.date_utils import SHANGHAI_TZ
from .models_config import get_active_model_info
from .shell_audit import append_log as _audit_append
from .shell_sandbox import (
    classify_dangerous_command,
    validate_command,
    validate_cwd,
    validate_timeout,
)
from .skills import REGISTRY, SKILLS_DIR

logger = logging.getLogger(__name__)


# 注:文件管理工具(read_file / write_file / edit_file / ls / glob / grep)由
# deepagents 的 FilesystemMiddleware 提供(自带 FilesystemPermission 校验),
# 这里不再重复定义,避免同名工具冲突 + 绕过权限校验。


@langchain_tool
def get_current_date() -> str:
    """获取今天的日期，格式 YYYY-MM-DD。"""
    today = datetime.date.today()
    return today.strftime("%Y-%m-%d")


@langchain_tool
def get_current_time(tz: str | None = None) -> str:
    """返回当前时间(精确到秒),格式 ``YYYY-MM-DD HH:MM:SS``。

    WHY 2026-07-14:之前 Nexus 没有"时分秒"工具,用户问"现在几点了"LLM 只能
    承认"我无法直接获取当前时间"。本工具补齐该能力,与 ``fact_check.today``
    共享 ``SHANGHAI_TZ``(项目事实源),保证 LLM 输出与 fact_check 校验时区一致。

    Args:
        tz: IANA 时区名(如 ``"Asia/Shanghai"`` / ``"UTC"``),传 ``None``
            默认 ``Asia/Shanghai``。

    Returns:
        ``YYYY-MM-DD HH:MM:SS`` 格式字符串(24h)。
    """
    zone = ZoneInfo(tz) if tz else SHANGHAI_TZ
    return datetime.datetime.now(zone).strftime("%Y-%m-%d %H:%M:%S")


@langchain_tool
def yandex_search(query: str) -> str:
    """使用 Yandex 搜索引擎搜索信息（国内可用）。

    Args:
        query: 搜索查询词
    """
    try:
        from bs4 import BeautifulSoup

        url = f"https://yandex.com/search/site/?searchid=1&text={query}&web=1&l=10"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            snippets = []
            for tag in soup.find_all(["p", "span", "div"], limit=10):
                text = tag.get_text(strip=True)
                if len(text) > 20:
                    snippets.append(text)
            if snippets:
                return "Yandex搜索结果：\n" + "\n".join(snippets[:5])
            return "Yandex搜索结果：未找到相关内容"
        return f"Yandex搜索失败：HTTP {resp.status_code}"
    except requests.RequestException as e:
        return f"Yandex搜索错误：{str(e)}"


# 搜索工具（缺对应包时降级为 None，TOOLS 会自动过滤）
try:
    web_search = DuckDuckGoSearchRun(name="web_search", description="搜索网络信息（国外服务，可能超时）")
except ImportError as e:
    logger.warning("DuckDuckGo 工具不可用: %s", e)
    web_search = None

try:
    from langchain_community.tools.wikipedia.tool import WikipediaQueryRun
    from langchain_community.utilities.wikipedia import WikipediaAPIWrapper

    wikipedia = WikipediaQueryRun(name="wikipedia", api_wrapper=WikipediaAPIWrapper())
except ImportError as e:
    logger.warning("Wikipedia 工具不可用: %s", e)
    wikipedia = None

# 文件管理工具(read_file/write_file/edit_file/ls/glob/grep)由
# deepagents FilesystemMiddleware 提供 —— 见模块顶部注释。


@langchain_tool
def list_dir(path: str | None = None) -> str:
    """列出目录下的文件列表。

    Args:
        path: 目录路径，默认为 ~/Documents/Nexus
    """
    if path:
        target = Path(path).expanduser()
    else:
        target = Path(CONFIG["default_save_path"]).expanduser()

    if not target.exists():
        return f"目录不存在: {target}"

    if not target.is_dir():
        return f"不是目录: {target}"

    files = []
    for item in sorted(target.iterdir()):
        files.append(item.name)

    if not files:
        return f"{target} 目录下没有文件"

    return "\n".join(files)


# === 自省工具:get_model_info ===
# WHY(2026-06-29 重构):之前把当前驱动模型名当字符串塞进 system prompt
# (``_build_system_prompt(model_name)``),这种"硬编码到 prompt"做法有几个固有问题:
#   1. 模型切换时若未走 ``POST /api/models/switch`` 重建 agent,prompt 还显示老模型 → 误导
#   2. vendor / api_base / temperature 等其他元数据塞不进去(塞多了爆 LLM 上下文)
#   3. 测试契约脆弱:传不传 model_name,产出的 prompt 字符串易不一致
# 现在 LLM 在被问"你用的什么模型"时主动调本工具 introspect 真实状态;
# prompt 模板只声明"调 get_model_info 拿实时信息",不再烘焙字符串事实。
@langchain_tool
def get_model_info() -> str:
    """返回当前激活 LLM 的实时元数据(name / vendor / api_base / temperature)。

    **这是 introspect 当前驱动模型的唯一可靠方式**:
        - 系统提示词不会预写"当前驱动模型 = X",你必须自己读 ``~/.nexus/models.json``
        - 用户切换模型后,这个工具的返回值会**立刻**反映新模型(每次调用都
          实时读盘),prompt 字符串做不到这一点
        - vendor 字段从 ``api_base`` URL 自动推断(MiniMax / agnes-ai / OpenAI / Anthropic)

    使用场景:
        - 用户问"你用的什么模型" → 先调本工具,再把返回的 ``name`` 拼进回答
        - 用户问"你是谁 / 你是哪个公司的" → 调本工具拿 ``vendor`` 字段
        - 调试/排障:用户报告"换了模型没生效" → 调本工具对账

    Returns:
        JSON 字符串,字段: ``name`` / ``vendor`` / ``api_base`` / ``temperature`` /
        ``is_active``。无激活模型时返回 ``"{}"``。
    """
    import json as _json

    info = get_active_model_info()
    if not info:
        return "{}"
    return _json.dumps(info, ensure_ascii=False)


# === 澄清工具 ===
# 关键设计：ask_user 是一个"被拦截"的工具 —— LLM 调用它的时候,ws.py 会
# 检测到 on_tool_start 事件,把工具入参(问题/候选项)作为 clarification_request
# 帧发给客户端,然后**终止本轮流**(不发送 final / done)。客户端用户在 UI
# 选完答案后,通过 WebSocket 发新消息,LLM 在新的 turn 看到历史里这条 ask_user
# 调用 + 用户回答,继续原任务。
# 因此工具的真实返回值基本不会被消费,这里返回占位说明文本。
_MAX_CLARIFY_OPTIONS = 6


@langchain_tool
def ask_user(question: str, options: list[str] | None = None) -> str:
    """向用户提出澄清问题 —— 当你**对用户意图不明确、有多种合理解释、
    关键参数缺失**时调用。调用的瞬间会中断当前回复,前端弹出澄清表单,
    等用户选完再继续任务。

    Args:
        question: 简洁明确的问题(中文 1-2 句话即可)。
        options: **必须传 2-6 个候选项**(给用户点选)。**不要传 None/空** —
            候选项让用户 1 秒点完,自由输入要打字体验差得多。仅在无法枚举时
            (如开放式问题"你想做什么?")才允许 options=None 让用户自由输入。

    适用场景:
        - 任务有多种合理解释(如"帮我整理项目"→哪种项目?哪些维度?)
        - 关键参数未指定(如"订明早的闹钟"→几点?工作日还是周末?)
        - 用户输入模糊(无主语、无目标、无约束)
        - 工具失败需要回退方案时(让用户二选一)

    候选项生成原则:
        - 数量:2-6 个(覆盖主要场景 + 留"其他"兜底)
        - 长度:每个 2-8 字,简洁明了
        - 互斥:候选项之间不要重叠
        - 默认选项:把最常见的 1 个放第一个

    不适用:
        - 闲聊/打招呼(直接用自然回复)
        - 信息已经充分(直接执行)
        - 用户已经给了完整指令(直接执行)
    """
    # 真正的返回值由 ws.py 拦截后注入,这里只是占位,让 langchain 在
    # tool 异常或流意外结束时不抛错。
    normalized: list[str] = []
    if options:
        normalized = [str(opt).strip() for opt in options if str(opt).strip()][:_MAX_CLARIFY_OPTIONS]
    summary = f"[ask_user] {question}"
    if normalized:
        summary += f" | options={normalized}"
    return summary


# === Skill 调用工具 ===
# WHY(2026-07-15):用户在 ``~/.nexus/skills/<name>/SKILL.md`` 放的 skill
# 需要一个 LLM 入口工具触发。本工具做 3 件事:
#   1. 从 REGISTRY 查 skill(查不到直接报错)
#   2. 检查 ``requires`` env(缺直接报错,**不**触发 HITL——环境变量缺失
#      是配置问题,弹卡给用户看也没用)
#   3. 拼接 cmd + cwd + timeout=120,内部转交给 :func:`shell_run` —— 走
#      现有沙箱 + 审计 + 危险命令 auto-deny
#
# WHY ``skill_args`` 不叫 ``args``:langchain 1.x Pydantic schema 把
# ``args`` / ``kwargs`` 当作 ``*args`` / ``**kwargs`` 的合成字段剔除
# (tools/base.py _parse_input 第 2148 行 filter),同名参数会丢。改叫
# ``skill_args`` 一劳永逸。
#
# HITL:**不**弹 ConfirmationCard(方案 A)。skill 是用户自己写的,
# entrypoint 是绝对路径,cwd 锁在 skill 目录内——再让用户每次确认
# 会变成点 100 次 OK 才能跑。
_RUN_SKILL_TIMEOUT_S = 120


@langchain_tool
def run_skill(skill_name: str, skill_args: str = "") -> str:
    """调用 ``~/.nexus/skills/<name>/`` 下注册的 skill。

    **适用场景**:
        - 用户输入命中了某个 skill 的 trigger(见 system prompt 的
          ``## 已加载 Skills`` 段)
        - skill 是用户自己写的脚本(entrypoint 必须是绝对路径)

    **强制约束**:
        - ``skill_name`` 必须在 REGISTRY 里(查不到 → 错误,不调 shell)
        - skill 声明的 ``requires`` env var 必须都已设置(缺 → 错误)
        - ``skill_args`` 用 :func:`shlex.quote` 转义,空格 / 特殊字符不会
          被 shell 拆成多参数
        - ``cwd`` 强制锁在 ``~/.nexus/skills/<skill_name>/``,不允许
          entrypoint 跑错目录

    沙箱:转交给 :func:`shell_run`,走 ``shell_sandbox`` 危险命令黑名单 +
    cwd 白名单 + ``_audit_append`` 审计。skill 写出 ``rm -rf /`` 仍会被拦。

    Args:
        skill_name: SKILL.md frontmatter 里的 ``name`` 字段。
        skill_args: 传给 entrypoint 的参数,整段会被 ``shlex.quote`` 包成
            一个 shell 参数;传空字符串 = 不传任何参数。

    Returns:
        shell_run 的可读报告字符串(含 exit_code / stdout / stderr)。
        skill 不存在 / 缺 env / 沙箱阻断时返回明确错误。
    """
    # === 步骤 1:查 REGISTRY ===
    manifest = REGISTRY.get(skill_name)
    if manifest is None:
        loaded = sorted(REGISTRY.keys())
        return f"[Skill 错误] 未找到 skill '{skill_name}'。当前已加载: {loaded if loaded else '(无)'}。"

    # === 步骤 2:env 检查 ===
    missing = [name for name in manifest.requires if not os.environ.get(name)]
    if missing:
        return f"[Skill 错误] skill '{skill_name}' 缺环境变量: {missing}。请先 export 后重试。"

    # === 步骤 3:拼 cmd ===
    # skill_args 空 → 不带 trailing space;非空 → shlex.quote 转义
    cmd_parts = [manifest.entrypoint]
    if skill_args:
        cmd_parts.append(shlex.quote(skill_args))
    cmd = " ".join(cmd_parts)

    # cwd = skill 目录(<SKILLS_DIR>/<name>/)
    skill_cwd = SKILLS_DIR / skill_name

    # === 步骤 4:转交 shell_run(走沙箱 + 审计 + HITL)===
    # 直接调底层函数,不调 .invoke —— .invoke 是 langchain ToolNode
    # 给 LLM 用的入口,带 callback 配置 / pydantic schema 校验,
    # 这里已是 Python 内部调用,绕过这层。
    return shell_run(command=cmd, cwd=str(skill_cwd), timeout=_RUN_SKILL_TIMEOUT_S)


# === Shell 执行工具 ===
# 关键设计(2026-07-14):
#   1. HITL 弹窗由 ``ShellHITLMiddleware`` 在 wrap_tool_call 阶段触发,本工具
#      **不**调 ``interrupt()`` —— ``@langchain_tool`` 装饰函数里调
#      ``langgraph.types.interrupt`` 没有 Pregel 上下文,不会抛 GraphInterrupt。
#   2. 沙箱"危险命令 / cwd 越界"在本工具**入口处短路** —— 直接返回 error 字符串,
#      让 LLM 立刻看到错误并改写,**不**触发 HITL 弹窗(用户不该看 rm -rf / 弹卡)。
#   3. 用户批准(HITL 通过) → 走 subprocess.run + audit log 完整记录。
#   4. stdout/stderr 截断 5000 字符,避免 LLM 上下文被一个 100MB 日志撑爆。
_STDOUT_MAX_CHARS = 5000
_STDERR_MAX_CHARS = 5000


@langchain_tool
def shell_run(command: str, cwd: str, timeout: int | None = None) -> str:
    """执行一条 shell 命令(需用户在 HITL 弹窗中确认后才会真正跑)。

    适用场景:
        - 用户让 AI 整理 ``~/.nexus/outputs/`` 下的文件(``ls`` / ``mv`` / ``cat``)
        - 用户让 AI 跑一个 Python 数据处理脚本(``python3 script.py``)
        - 用户让 AI 清理日志(``find ~/.nexus/logs -mtime +30 -delete`` —— 注意此
          类命令可能被沙箱拒绝,见下方限制)

    强制约束(沙箱):
        - **必须**显式传 ``cwd``(默认 cwd 不可控,直接拒绝)
        - ``cwd`` **必须**落在 ``~/.nexus/`` 白名单下(其它目录直接拒绝)
        - 命令字符串触发危险模式黑名单(rm -rf / / sudo / fork bomb 等)直接拒绝
        - ``timeout`` clamp 到 ``[1, 300]`` 秒(不传 → 30s 默认)

    审计:无论结果如何,都会写入 ``~/.nexus/logs/shell_executions.log``
    (JSONL + 0600 权限,10MB rotate),用户可在事后回查"AI 跑了什么/我批准了
    什么/结果是什么"。

    Args:
        command: 要执行的 shell 命令字符串。
        cwd: 工作目录绝对路径,**必须**在 ``~/.nexus/`` 下。
        timeout: 超时秒数,clamp 到 [1, 300];不传默认 30s。

    Returns:
        退出码 + 截断 stdout/stderr 的可读报告字符串;失败原因直接说明。
    """
    # === 步骤 1:沙箱前置校验(危险命令短路 / cwd 越界短路)===
    ok_cmd, cmd_reason = validate_command(command)
    if not ok_cmd:
        risk = classify_dangerous_command(command)
        _audit_append(
            command=command,
            cwd=str(cwd),
            exit_code=None,
            user_decision="auto_deny",
            risk_label=risk,
        )
        return f"[Shell 沙箱阻断] {cmd_reason}"

    ok_cwd, resolved_cwd = validate_cwd(cwd)
    if not ok_cwd:
        _audit_append(
            command=command,
            cwd=str(cwd),
            exit_code=None,
            user_decision="auto_deny",
        )
        return f"[Shell 沙箱阻断] {resolved_cwd}"

    # === 步骤 2:HITL 已经通过(middleware 已放行),执行 subprocess ===
    timeout_s = validate_timeout(timeout)
    started_at = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            shell=True,  # noqa: S602 — LLM 工具无法避免 shell parse
            cwd=resolved_cwd,
            timeout=timeout_s,
            capture_output=True,
            text=True,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.monotonic() - started_at) * 1000)
        stderr_preview = (exc.stderr or "")[:_STDERR_MAX_CHARS] if isinstance(exc.stderr, str) else ""
        _audit_append(
            command=command,
            cwd=resolved_cwd,
            exit_code=None,
            stderr_snippet=f"TIMEOUT after {timeout_s}s: {stderr_preview}",
            user_decision="approve",
            duration_ms=duration_ms,
        )
        return f"[Shell 超时] 命令在 {timeout_s}s 内未结束,已被强制终止。stderr: {stderr_preview}"
    except subprocess.SubprocessError as exc:
        duration_ms = int((time.monotonic() - started_at) * 1000)
        _audit_append(
            command=command,
            cwd=resolved_cwd,
            exit_code=None,
            stderr_snippet=str(exc),
            user_decision="approve",
            duration_ms=duration_ms,
        )
        return f"[Shell 子进程错误] {exc}"

    duration_ms = int((time.monotonic() - started_at) * 1000)
    stdout_preview = (proc.stdout or "")[:_STDOUT_MAX_CHARS]
    stderr_preview = (proc.stderr or "")[:_STDERR_MAX_CHARS]
    _audit_append(
        command=command,
        cwd=resolved_cwd,
        exit_code=proc.returncode,
        stdout_snippet=stdout_preview,
        stderr_snippet=stderr_preview,
        user_decision="approve",
        duration_ms=duration_ms,
    )

    if proc.returncode == 0:
        return f"[exit_code=0] (cwd={resolved_cwd}, {duration_ms}ms)\nstdout:\n{stdout_preview}" + (
            f"\nstderr:\n{stderr_preview}" if stderr_preview else ""
        )
    return (
        f"[exit_code={proc.returncode}] (cwd={resolved_cwd}, {duration_ms}ms)\n"
        f"stdout:\n{stdout_preview}\n"
        f"stderr:\n{stderr_preview}"
    )


TOOLS = [
    get_current_date,
    get_current_time,
    yandex_search,
    web_search,
    wikipedia,
    list_dir,
    ask_user,
    get_model_info,
    run_skill,
    shell_run,
]
TOOLS = [t for t in TOOLS if t is not None]
