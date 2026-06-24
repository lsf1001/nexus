import datetime
import logging
from pathlib import Path

import requests
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_core.tools import tool as langchain_tool

from .config import CONFIG

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


TOOLS = [
    get_current_date,
    yandex_search,
    web_search,
    wikipedia,
    list_dir,
    ask_user,
]
TOOLS = [t for t in TOOLS if t is not None]
