"""测试 setup_logging 的 env 三档配置 + 重复调用幂等。"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from nexus.backend.observability.logger import (
    ENV_LOG_FILE,
    ENV_LOG_FORMAT,
    ENV_LOG_LEVEL,
    setup_logging,
)


@pytest.fixture(autouse=True)
def reset_root_logger():
    """每个测试前重置 root logger,避免跨测试污染 handlers/level/marker。"""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    saved_attr = getattr(root, "_nexus_observability_configured", None)
    root.handlers = []
    root.setLevel(logging.WARNING)
    # 必须在 setup 前清掉 marker,否则 main.py 启动期 setup_logging() 留下
    # 的 _nexus_observability_configured=True 会让下一次 setup_logging() 早退,
    # 不再写日志文件。fixture 末尾按 saved_attr 恢复。
    if getattr(root, "_nexus_observability_configured", False):
        try:
            delattr(root, "_nexus_observability_configured")
        except AttributeError:
            pass
    yield
    # 关闭并清掉本次测试挂上去的 handler,避免 RotatingFileHandler 持有打开的 fd
    for h in list(root.handlers):
        try:
            h.close()
        except Exception:  # noqa: BLE001 — 关闭时出错不影响测试清理
            pass
    root.handlers = saved_handlers
    root.setLevel(saved_level)
    if saved_attr is None:
        try:
            delattr(root, "_nexus_observability_configured")
        except AttributeError:
            pass
    else:
        root._nexus_observability_configured = saved_attr  # type: ignore[attr-defined]


def test_default_log_path_is_under_nexus_home(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv(ENV_LOG_FORMAT, raising=False)
    monkeypatch.delenv(ENV_LOG_FILE, raising=False)
    monkeypatch.delenv(ENV_LOG_LEVEL, raising=False)
    setup_logging()
    expected = tmp_path / ".nexus" / "logs" / "nexus.log"
    # 父目录一定存在;文件本身可能在 setup_logging 的 info log 之后才落地
    assert expected.parent.exists()


def test_text_format_writes_kv_lines(tmp_path: Path, monkeypatch):
    log_file = tmp_path / "test.log"
    monkeypatch.setenv(ENV_LOG_FORMAT, "text")
    monkeypatch.setenv(ENV_LOG_FILE, str(log_file))
    setup_logging()
    logging.getLogger("test.logger").info("hello %s", "world")
    for h in logging.getLogger().handlers:
        h.flush()
    content = log_file.read_text(encoding="utf-8")
    assert "hello world" in content
    assert "test.logger" in content


def test_json_format_writes_json_lines(tmp_path: Path, monkeypatch):
    log_file = tmp_path / "test.jsonl"
    monkeypatch.setenv(ENV_LOG_FORMAT, "json")
    monkeypatch.setenv(ENV_LOG_FILE, str(log_file))
    setup_logging()
    logging.getLogger("test.logger").info("hello %s", "world")
    for h in logging.getLogger().handlers:
        h.flush()
    lines = [ln for ln in log_file.read_text(encoding="utf-8").strip().split("\n") if ln]
    assert len(lines) >= 1
    payload = json.loads(lines[-1])
    assert payload["message"] == "hello world"
    assert payload["name"] == "test.logger"


def test_log_level_env_respected(monkeypatch):
    monkeypatch.setenv(ENV_LOG_LEVEL, "WARNING")
    setup_logging()
    assert logging.getLogger().level == logging.WARNING


def test_setup_logging_is_idempotent(monkeypatch):
    """多次调用不重复挂 handler。"""
    monkeypatch.setenv(ENV_LOG_FORMAT, "text")
    setup_logging()
    handler_count_first = len(logging.getLogger().handlers)
    setup_logging()
    handler_count_second = len(logging.getLogger().handlers)
    assert handler_count_first == handler_count_second
