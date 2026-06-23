"""微信通道 smoke test：覆盖纯数据 / 纯函数 / 文件 I/O / 登录流程 mock。

注意：wechat_qr_login / wait_qr_scan 等会真连微信服务器（FIXED_BASE_URL=https://ilinkai.weixin.qq.com），
      本文件用 monkeypatch 拦截网络调用，不发起真请求。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from nexus.backend.channels import wechat_account, wechat_login
from nexus.backend.channels.wechat_account import (
    _load_account,
    _normalize_account_id,
    _save_account,
)
from nexus.backend.channels.wechat_login import wechat_qr_login
from nexus.backend.channels.wechat_protocol import (
    _build_base_info,
    _build_client_version,
    _build_headers,
)
from nexus.backend.channels.wechat_types import QRSession, WeixinAccount

# ---------- 纯函数测试 ----------


def test_normalize_account_id_basic():
    """_normalize_account_id 应把 '@im.bot' / '@im.wechat' 替换为文件系统安全形式。"""
    assert _normalize_account_id("user@im.bot") == "user-im-bot"
    assert _normalize_account_id("user@im.wechat") == "user-im-wechat"
    assert _normalize_account_id("plain_id") == "plain_id"
    assert _normalize_account_id("") == ""


def test_build_headers_without_token():
    """_build_headers 不带 token 时应返回基础 header（iLink 风格）。"""
    h = _build_headers(token=None)
    assert "iLink-App-Id" in h
    assert h["iLink-App-Id"] == "bot"
    assert h["Content-Type"] == "application/json"
    assert "Authorization" not in h


def test_build_headers_with_token():
    """_build_headers 带 token 时应包含 Bearer Authorization。"""
    h = _build_headers(token="test_token_xyz")
    assert h["Authorization"] == "Bearer test_token_xyz"


def test_build_client_version_standard():
    """_build_client_version 应把 'x.y.z' 编码成整数。"""
    # 实际格式: 主.次.补丁 → (主<<24) | (次<<16) | 补丁
    v = _build_client_version("2.4.4")
    assert isinstance(v, int)
    assert v > 0


def test_build_client_version_zero():
    """_build_client_version '0.0.0' 应返回 0。"""
    assert _build_client_version("0.0.0") == 0


def test_build_base_info_structure():
    """_build_base_info 应返回包含 channel_version / bot_agent 的 dict（OpenClaw 兼容）。"""
    info = _build_base_info()
    assert isinstance(info, dict)
    assert "channel_version" in info
    assert "bot_agent" in info
    assert info["bot_agent"] == "OpenClaw"


# ---------- dataclass 测试 ----------


def test_weixin_account_serialization():
    """WeixinAccount 应可转 dict / 从 dict 还原（dataclass 内置）。"""
    from dataclasses import asdict

    acc = WeixinAccount(
        account_id="abc123",
        user_id="user-001",
        token="tkn_xyz",
    )
    d = asdict(acc)
    assert d["account_id"] == "abc123"
    assert d["user_id"] == "user-001"
    assert d["token"] == "tkn_xyz"
    assert d["cdn_base_url"] == "https://novac2c.cdn.weixin.qq.com/c2c"


def test_qr_session_creation():
    """QRSession 应能直接构造。"""
    s = QRSession(
        session_key="sess-001",
        qrcode="qr-content",
        qrcode_url="data:image/png;base64,xxx",
    )
    assert s.session_key == "sess-001"
    assert s.qrcode == "qr-content"
    assert s.qrcode_url.startswith("data:image/")


# ---------- 文件 I/O 测试（用 tmp_path）----------


def test_save_and_load_account_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """_save_account + _load_account 应能往返。"""
    # 让 wechat 写到 tmp_path 而不是 ~/.nexus/
    monkeypatch.setattr(wechat_account, "_get_state_dir", lambda: tmp_path)

    acc = WeixinAccount(
        account_id="test-acc",
        user_id="user-test",
        token="tkn_001",
    )
    _save_account(acc)

    loaded = _load_account("test-acc")
    assert loaded is not None
    assert loaded.account_id == "test-acc"
    assert loaded.user_id == "user-test"
    assert loaded.token == "tkn_001"


def test_load_nonexistent_account_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """_load_account 加载不存在的账号应返回 None。"""
    monkeypatch.setattr(wechat_account, "_get_state_dir", lambda: tmp_path)
    assert _load_account("nope-not-exist") is None


# ---------- 登录流程 mock 测试 ----------


@pytest.mark.asyncio
async def test_wechat_qr_login_success(monkeypatch: pytest.MonkeyPatch):
    """wechat_qr_login 成功路径：mock _fetch_qrcode 返回有效响应。"""
    # mock _fetch_qrcode 不真发 HTTP
    mock_fetch = AsyncMock(
        return_value={
            "qrcode": "qr-raw-content",
            "qrcode_img_content": "data:image/png;base64,iVBORw0KGgo=",
        }
    )
    monkeypatch.setattr(wechat_login, "_fetch_qrcode", mock_fetch)
    # refactored: 函数体调的是 wechat_login._fetch_qrcode（不是 re-export 引用）
    monkeypatch.setattr("nexus.backend.channels.wechat_login._fetch_qrcode", mock_fetch)

    result = await wechat_qr_login()
    assert "qrcode_url" in result
    assert result["qrcode"] == "qr-raw-content"
    assert "session_key" in result
    assert mock_fetch.await_count == 1


@pytest.mark.asyncio
async def test_wechat_qr_login_network_error(monkeypatch: pytest.MonkeyPatch):
    """wechat_qr_login 网络错误：mock _fetch_qrcode 抛异常，应返回 error 字段而非崩。"""
    mock_fetch = AsyncMock(side_effect=ConnectionError("network unreachable"))
    monkeypatch.setattr("nexus.backend.channels.wechat_login._fetch_qrcode", mock_fetch)

    result = await wechat_qr_login()
    assert "error" in result
    assert "network unreachable" in result["error"]


@pytest.mark.asyncio
async def test_wechat_qr_login_empty_response(monkeypatch: pytest.MonkeyPatch):
    """wechat_qr_login 响应缺字段：应能 fallback 到空字符串。"""
    mock_fetch = AsyncMock(return_value={})  # 没有 qrcode 字段
    monkeypatch.setattr("nexus.backend.channels.wechat_login._fetch_qrcode", mock_fetch)

    result = await wechat_qr_login()
    assert result["qrcode"] == ""
    assert "session_key" in result
