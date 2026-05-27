"""测试 tools.py 模块。"""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from nexus.backend.tools import _get_save_path


class TestGetSavePath:
    """测试 _get_save_path 函数。"""

    @patch("nexus.backend.tools.CONFIG")
    def test_default_path(self, mock_config):
        """默认路径应该使用配置的保存目录。"""
        mock_config.__getitem__.return_value = str(Path.home() / "Documents" / "Nexus")

        result = _get_save_path("test.txt", None)
        assert result.name == "test.txt"
        assert result.parent.name == "Nexus"

    @patch("nexus.backend.tools.CONFIG")
    def test_absolute_path(self, mock_config):
        """绝对路径应该直接返回。"""
        mock_config.__getitem__.return_value = str(Path.home() / "Documents" / "Nexus")

        result = _get_save_path("test.txt", "/tmp/test.txt")
        assert result == Path("/tmp/test.txt")

    @patch("nexus.backend.tools.CONFIG")
    def test_add_txt_extension(self, mock_config):
        """没有后缀名时应该添加 .txt 后缀。"""
        mock_config.__getitem__.return_value = str(Path.home() / "Documents" / "Nexus")

        result = _get_save_path("test", None)
        assert result.name == "test.txt"


class TestGetCurrentDate:
    """测试 get_current_date 函数。"""

    def test_date_format(self):
        """日期格式应该是 YYYY-MM-DD。"""
        from nexus.backend.tools import get_current_date

        result = get_current_date.func()
        assert len(result) == 10
        assert result[4] == "-"
        assert result[7] == "-"


class TestWriteFile:
    """测试 write_file 函数。"""

    @patch("nexus.backend.tools._get_save_path")
    def test_write_file_success(self, mock_get_path):
        """写文件成功。"""
        from nexus.backend.tools import write_file

        mock_path = MagicMock()
        mock_path.parent = MagicMock()
        mock_get_path.return_value = mock_path

        result = write_file.func("test.txt", "content")
        mock_path.parent.mkdir.assert_called_once()
        mock_path.write_text.assert_called_once_with("content", encoding="utf-8")
        assert "已保存" in result


class TestYandexSearch:
    """测试 yandex_search 函数。"""

    @patch("nexus.backend.tools.requests.get")
    def test_search_success(self, mock_get):
        """搜索成功时返回解析后的内容。"""
        from nexus.backend.tools import yandex_search

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><p>这是一个搜索结果片段，长度超过20个字符</p></html>"
        mock_get.return_value = mock_resp

        result = yandex_search.func("test query")
        assert "Yandex搜索结果" in result

    @patch("nexus.backend.tools.requests.get")
    def test_search_http_error(self, mock_get):
        """HTTP 错误时返回错误信息。"""
        from nexus.backend.tools import yandex_search

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp

        result = yandex_search.func("test query")
        assert "失败" in result

    @patch("nexus.backend.tools.requests.get")
    def test_search_timeout(self, mock_get):
        """超时时返回错误信息。"""
        import requests
        from nexus.backend.tools import yandex_search

        mock_get.side_effect = requests.RequestException("timeout")

        result = yandex_search.func("test query")
        assert "错误" in result
