"""测试 mcp.py 模块。"""

import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from nexus.backend.mcp import find_mcp_config, load_all_mcp_tools


class TestFindMcpConfig:
    """测试 find_mcp_config 函数。"""

    def test_user_config_exists(self, tmp_path):
        """用户级配置文件存在时加载。"""
        user_mcp = tmp_path / ".mcp.json"
        user_mcp.write_text(json.dumps({
            "mcpServers": {"test": {"command": "node"}}
        }))

        with patch("nexus.backend.mcp.Path.home") as mock_home:
            mock_home.return_value = tmp_path

            result = find_mcp_config()
            assert len(result) == 1
            assert result[0]["name"] == "test"
            assert result[0]["command"] == "node"

    def test_invalid_json(self, tmp_path):
        """无效 JSON 时返回空列表。"""
        user_mcp = tmp_path / ".mcp.json"
        user_mcp.write_text("invalid json")

        with patch("nexus.backend.mcp.Path.home") as mock_home:
            mock_home.return_value = tmp_path

            result = find_mcp_config()
            assert result == []

    def test_no_config_files(self, tmp_path):
        """没有配置文件时返回空列表。"""
        with patch("nexus.backend.mcp.Path.home") as mock_home:
            mock_home.return_value = tmp_path

            result = find_mcp_config()
            assert result == []


class TestLoadAllMcpTools:
    """测试 load_all_mcp_tools 函数。"""

    @patch("nexus.backend.mcp.find_mcp_config")
    @pytest.mark.asyncio
    async def test_no_servers(self, mock_find):
        """没有 MCP 服务器时返回空列表。"""
        mock_find.return_value = []
        result = await load_all_mcp_tools()
        assert result == []

    @patch("nexus.backend.mcp.find_mcp_config")
    @patch("nexus.backend.mcp._load_tools_for_server")
    @pytest.mark.asyncio
    async def test_with_servers(self, mock_load, mock_find):
        """有 MCP 服务器时加载工具。"""
        mock_find.return_value = [{"name": "test", "command": "node"}]

        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_load.return_value = [mock_tool]

        result = await load_all_mcp_tools()
        assert len(result) == 1
        assert result[0].name == "test_tool"

    @patch("nexus.backend.mcp.find_mcp_config")
    @patch("nexus.backend.mcp._load_tools_for_server")
    @pytest.mark.asyncio
    async def test_filter_duplicates(self, mock_load, mock_find):
        """过滤与内置工具重复的 MCP 工具。"""
        mock_find.return_value = [{"name": "test", "command": "node"}]

        mock_tool = MagicMock()
        mock_tool.name = "get_current_date"
        mock_load.return_value = [mock_tool]

        result = await load_all_mcp_tools()
        assert len(result) == 0
