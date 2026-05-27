"""测试 models_config.py 模块。"""

import json
import pytest
from unittest.mock import patch, MagicMock, mock_open
from nexus.backend.models_config import load_models, save_models, get_active_model, set_active_model


class TestLoadModels:
    """测试 load_models 函数。"""

    @patch("nexus.backend.models_config.MODELS_FILE")
    def test_file_not_exists(self, mock_file):
        """配置文件不存在时创建默认配置。"""
        mock_file.exists.return_value = False
        mock_file.parent = MagicMock()

        with patch("nexus.backend.models_config.save_models") as mock_save:
            result = load_models()
            assert "models" in result
            assert len(result["models"]) == 1
            assert result["models"][0]["id"] == "default"

    @patch("nexus.backend.models_config.MODELS_FILE")
    def test_file_exists_valid(self, mock_file):
        """配置文件存在且有效时加载。"""
        mock_file.exists.return_value = True

        test_data = {"models": [{"id": "test", "name": "Test Model", "is_active": True}]}
        m = mock_open(read_data=json.dumps(test_data))

        with patch("builtins.open", m):
            result = load_models()
            assert len(result["models"]) == 1
            assert result["models"][0]["id"] == "test"

    @patch("nexus.backend.models_config.MODELS_FILE")
    def test_file_exists_invalid_json(self, mock_file):
        """配置文件存在但 JSON 无效时返回空列表。"""
        mock_file.exists.return_value = True

        with patch("builtins.open", mock_open(read_data="invalid json")):
            result = load_models()
            assert result == {"models": []}


class TestGetActiveModel:
    """测试 get_active_model 函数。"""

    @patch("nexus.backend.models_config.load_models")
    def test_has_active_model(self, mock_load):
        """有激活模型时返回该模型。"""
        mock_load.return_value = {
            "models": [
                {"id": "a", "is_active": False},
                {"id": "b", "is_active": True},
            ]
        }

        result = get_active_model()
        assert result["id"] == "b"

    @patch("nexus.backend.models_config.load_models")
    def test_no_active_model(self, mock_load):
        """没有激活模型时返回 None。"""
        mock_load.return_value = {
            "models": [
                {"id": "a", "is_active": False},
                {"id": "b", "is_active": False},
            ]
        }

        result = get_active_model()
        assert result is None


class TestSetActiveModel:
    """测试 set_active_model 函数。"""

    @patch("nexus.backend.models_config.save_models")
    @patch("nexus.backend.models_config.load_models")
    def test_set_active(self, mock_load, mock_save):
        """设置激活模型。"""
        mock_load.return_value = {
            "models": [
                {"id": "a", "is_active": True},
                {"id": "b", "is_active": False},
            ]
        }

        result = set_active_model("b")
        assert result["id"] == "b"
        assert result["is_active"] is True
        mock_save.assert_called_once()
