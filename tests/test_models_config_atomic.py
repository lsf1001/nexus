"""测试 models_config 原子写入。"""

import json
import os
from pathlib import Path
from unittest.mock import patch

from nexus.backend.models_config import save_models, MODELS_FILE


class TestAtomicWrite:
    """save_models 应使用临时文件 + os.replace 原子写入。"""

    def test_no_temp_files_left_on_success(self, tmp_path: Path) -> None:
        """成功保存后，~/.nexus 下不应残留 .models.*.json.tmp。"""
        test_file = tmp_path / "models.json"
        with patch("nexus.backend.models_config.MODELS_FILE", test_file):
            save_models({"models": [{"id": "x", "name": "X", "is_active": True}]})

        leftovers = list(tmp_path.glob(".models.*.json.tmp"))
        assert leftovers == []
        assert test_file.exists()

    def test_cleans_tmp_on_failure(self, tmp_path: Path) -> None:
        """写入过程中抛错时，临时文件应被清理。"""
        test_file = tmp_path / "models.json"

        with patch("nexus.backend.models_config.MODELS_FILE", test_file):
            with patch("os.fsync", side_effect=OSError("disk full")):
                try:
                    save_models({"models": []})
                except OSError:
                    pass

        leftovers = list(tmp_path.glob(".models.*.json.tmp"))
        assert leftovers == []

    def test_content_written_correctly(self, tmp_path: Path) -> None:
        """保存的内容应能被正确读回。"""
        test_file = tmp_path / "models.json"
        cfg = {
            "models": [
                {
                    "id": "m1",
                    "name": "Model 1",
                    "api_key": "secret",
                    "api_base": "https://api.example.com",
                    "temperature": 0.5,
                    "is_active": True,
                }
            ]
        }
        with patch("nexus.backend.models_config.MODELS_FILE", test_file):
            save_models(cfg)

        loaded = json.loads(test_file.read_text(encoding="utf-8"))
        assert loaded == cfg
