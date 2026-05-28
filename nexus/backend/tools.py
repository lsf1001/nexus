import datetime
import requests
from pathlib import Path
from typing import Optional, List
from langchain_core.tools import tool as langchain_tool
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_community.tools.wikipedia.tool import WikipediaQueryRun
from langchain_community.tools.file_management import (
    ReadFileTool,
    WriteFileTool,
    ListDirectoryTool,
    CopyFileTool,
    MoveFileTool,
    DeleteFileTool,
)
from langchain_community.utilities.wikipedia import WikipediaAPIWrapper

from .config import CONFIG
from .memory import MemoryService, EvolutionService, CATEGORY_PREFERENCE, CATEGORY_KNOWLEDGE, CATEGORY_CONTEXT

# 全局服务实例
_memory_service: Optional[MemoryService] = None
_evolution_service: Optional[EvolutionService] = None


def get_memory_service() -> MemoryService:
    """获取记忆服务实例（延迟初始化）。"""
    global _memory_service
    if _memory_service is None:
        _memory_service = MemoryService()
    return _memory_service


def get_evolution_service() -> EvolutionService:
    """获取进化服务实例（延迟初始化）。"""
    global _evolution_service
    if _evolution_service is None:
        _evolution_service = EvolutionService(get_memory_service())
    return _evolution_service


def _get_save_path(filename: str, path: str | None) -> Path:
    """解析文件路径，默认为配置目录。"""
    base = Path(CONFIG["default_save_path"]).expanduser()
    base.mkdir(parents=True, exist_ok=True)

    if path:
        p = Path(path).expanduser()
        if p.is_absolute():
            if p.suffix:  # 完整文件路径
                return p
            base = p.parent
            filename = p.name
        else:
            base = base / p

    # 确保文件名有后缀
    if "." not in Path(filename).suffix:
        filename += ".txt"

    return base / filename


@langchain_tool
def write_file(filename: str, content: str, path: str | None = None) -> str:
    """写入内容到文件。

    Args:
        filename: 文件名（必填，自动添加到默认目录）
        content: 要写入的内容（必填）
        path: 子目录路径（可选，如 "subdir" 或完整路径）
    """
    save_path = _get_save_path(filename, path)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_text(content, encoding="utf-8")
    return f"已保存到 {save_path}"


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


# 搜索工具
web_search = DuckDuckGoSearchRun(name="web_search", description="搜索网络信息（国外服务，可能超时）")
wikipedia = WikipediaQueryRun(name="wikipedia", api_wrapper=WikipediaAPIWrapper())

# 文件管理工具
read_file = ReadFileTool()
write_file_tool = WriteFileTool()
copy_file = CopyFileTool()
move_file = MoveFileTool()
delete_file = DeleteFileTool()


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


# ============================================================================
# 记忆工具
# ============================================================================

@langchain_tool
def save_memory(category: str, key: str, value: str) -> str:
    """保存记忆。

    用于保存用户偏好、知识或重要信息，方便后续会话使用。

    Args:
        category: 分类，取值：preference(偏好), knowledge(知识), context(上下文)
        key: 记忆键，用于标识这条记忆
        value: 记忆内容，要保存的具体信息
    """
    ms = get_memory_service()
    result = ms.save_memory(category=category, key=key, value=value, memory_type="explicit")
    return f"已保存记忆：[{category}] {key} = {value}"


@langchain_tool
def read_memory(category: Optional[str] = None) -> str:
    """读取已保存的记忆。

    Args:
        category: 可选，筛选特定分类的记忆（preference/knowledge/context）
    """
    ms = get_memory_service()
    memories = ms.list_memory(category=category)

    if not memories:
        return "没有找到记忆"

    lines = ["已保存的记忆："]
    for m in memories:
        lines.append(f"- [{m['category']}] {m['key']}: {m['value']}")

    return "\n".join(lines)


@langchain_tool
def search_memory(keyword: str, limit: int = 5) -> str:
    """搜索记忆。

    通过关键词搜索相关记忆内容。

    Args:
        keyword: 搜索关键词
        limit: 返回数量限制，默认5条
    """
    ms = get_memory_service()
    results = ms.search_memory(keyword=keyword, limit=limit)

    if not results:
        return f"未找到包含「{keyword}」的记忆"

    lines = [f"找到 {len(results)} 条相关记忆："]
    for m in results:
        lines.append(f"- [{m['category']}] {m['key']}: {m['value']}")

    return "\n".join(lines)


@langchain_tool
def delete_memory(memory_id: str, hard: bool = False) -> str:
    """删除记忆。

    Args:
        memory_id: 记忆 ID
        hard: 是否彻底删除（True=彻底删除，False=软删除）
    """
    ms = get_memory_service()
    success = ms.delete_memory(memory_id, hard=hard)

    if success:
        action = "彻底删除" if hard else "已删除"
        return f"记忆 {action}"
    return "记忆不存在或已删除"


TOOLS = [
    get_current_date,
    write_file,  # 自定义的写文件工具
    yandex_search,
    web_search,
    wikipedia,
    read_file,
    write_file_tool,
    list_dir,
    copy_file,
    move_file,
    delete_file,
    # 记忆工具
    save_memory,
    read_memory,
    search_memory,
    delete_memory,
]