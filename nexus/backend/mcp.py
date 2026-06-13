"""MCP (Model Context Protocol) 集成模块。

支持从 .mcp.json 配置文件加载 MCP 服务器工具。
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def find_mcp_config() -> list[dict[str, Any]]:
    """查找并解析 .mcp.json 配置文件。

    搜索顺序：
    1. ~/.mcp.json（用户级配置）
    2. 项目根目录/.mcp.json（项目级配置）

    Returns:
        MCP 服务器配置列表
    """
    configs = []

    # 用户级配置（新版：~/.nexus/mcp/config.json）
    nexus_mcp = Path.home() / ".nexus" / "mcp" / "config.json"
    if nexus_mcp.exists():
        configs.append(nexus_mcp)

    # 用户级配置（旧版：~/.mcp.json，兼容）
    user_mcp = Path.home() / ".mcp.json"
    if user_mcp.exists():
        configs.append(user_mcp)

    # 项目级配置
    project_root = Path(__file__).parent.parent
    project_mcp = project_root / ".mcp.json"
    if project_mcp.exists():
        configs.append(project_mcp)

    all_servers = []
    for config_path in configs:
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            servers = data.get("mcpServers", {})
            for name, server_config in servers.items():
                server_config["name"] = name
                server_config["source"] = str(config_path)
                all_servers.append(server_config)
            logger.info(f"从 {config_path} 加载了 {len(servers)} 个 MCP 服务器")
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            logger.warning(f"解析 {config_path} 失败: {e}")

    return all_servers


async def _load_tools_for_server(
    server_name: str,
    server_config: dict[str, Any],
) -> list[Any]:
    """为单个服务器加载工具，使用持久会话。

    Args:
        server_name: 服务器名称
        server_config: 服务器配置

    Returns:
        工具列表
    """
    from langchain_mcp_adapters.sessions import StdioConnection

    command = server_config.get("command")
    args = server_config.get("args", [])
    env = server_config.get("env", {})

    if not command:
        logger.warning(f"MCP 服务器 {server_name} 缺少 command")
        return []

    conn_config = StdioConnection(
        transport="stdio",
        command=command,
        args=args,
        env=env if env else None,
    )

    try:
        from langchain_mcp_adapters.tools import load_mcp_tools

        # 使用 session=None + connection 参数
        # 这样工具会在每次调用时创建新的临时会话，避免会话生命周期问题
        tools = await asyncio.wait_for(load_mcp_tools(session=None, connection=conn_config), timeout=8.0)
        logger.info(f"从 MCP 服务器 {server_name} 加载了 {len(tools)} 个工具")
        return tools

    except TimeoutError:
        logger.error(f"加载 MCP 服务器 {server_name} 超时（8秒）")
        return []
    except Exception as e:
        logger.error(f"加载 MCP 服务器 {server_name} 失败: {e}")
        return []


async def load_all_mcp_tools() -> list[Any]:
    """加载所有配置的 MCP 服务器工具。

    关键：每个 server 的加载并发跑（asyncio.gather），总时间 ≈ max(server_time)
    而不是 sum(server_time)。单个 server 上限 8s（之前 30s）。

    Returns:
        所有 MCP 服务器的工具列表
    """
    servers = find_mcp_config()
    if not servers:
        logger.debug("未找到 MCP 服务器配置")
        return []

    tasks = [_load_tools_for_server(server_config.get("name", "unknown"), server_config) for server_config in servers]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    all_tools = []
    for result in results:
        if isinstance(result, Exception):
            logger.error(f"MCP 加载失败: {result}")
            continue
        all_tools.extend(result)

    # 过滤掉与内置工具重复的工具（按名称）
    from .tools import TOOLS

    built_in_names = {t.name for t in TOOLS}
    filtered_tools = [t for t in all_tools if t.name not in built_in_names]

    duplicate_count = len(all_tools) - len(filtered_tools)
    if duplicate_count > 0:
        logger.warning(
            f"过滤了 {duplicate_count} 个与内置工具重复的 MCP 工具: {[t.name for t in all_tools if t.name in built_in_names]}"
        )

    logger.info(f"共加载 {len(filtered_tools)} 个 MCP 工具（过滤后）")
    return filtered_tools
