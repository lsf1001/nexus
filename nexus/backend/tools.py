import datetime
import requests
from pathlib import Path
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
        url = f"https://yandex.com/search/site/?searchid=1&text={query}&web=1&l=10"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            # 简单提取搜索结果片段
            return f"Yandex搜索结果：{resp.text[:500]}"
        return f"Yandex搜索失败：HTTP {resp.status_code}"
    except Exception as e:
        return f"Yandex搜索错误：{str(e)}"


# 搜索工具
web_search = DuckDuckGoSearchRun(name="web_search", description="搜索网络信息（国外服务，可能超时）")
from langchain_community.utilities.wikipedia import WikipediaAPIWrapper
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
]