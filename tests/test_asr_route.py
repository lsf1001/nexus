"""POST /api/asr 单测 — Whisper + mock fallback。

WHY 3 个测试覆盖:mock fallback(无 key)/ OpenAI 路径(有 key)/ 空 payload 拒绝。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nexus.backend.main import app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """设 ws_token 让 require_token 通过;DB 不需要(纯 ASR endpoint 不读 DB)。"""
    from nexus.backend import config as config_module

    monkeypatch.setitem(config_module.CONFIG, "ws_token", "test-asr-token")
    return TestClient(app)


AUTH = {"Authorization": "Bearer test-asr-token"}


def test_asr_mock_when_no_openai_key(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """无 OPENAI_API_KEY → 走 mock fallback,返回固定 mock 文本。

    WHY 删 env 而不是 monkeypatch CONFIG:ASR 路由读 os.environ,跟生产路径一致。
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "")  # 显式置空,避免子进程 inherit
    response = client.post(
        "/api/asr",
        headers=AUTH,
        files={"audio": ("clip.webm", b"\x00" * 1024, "audio/webm")},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"text": "语音输入(mock)"}


def test_asr_openai_path_when_key_set(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """有 OPENAI_API_KEY + 注入的转写函数 → 走注入路径,返回 mock 文本。

    WHY monkeypatch 模块级 _call_whisper_fn 而不是 mock openai.OpenAI:
    - 不依赖 OpenAI SDK 内部实现细节
    - 跟 plan 的"函数注入"契约一致
    - 测试只关心路由的"调度逻辑"对不对,不关心 SDK 怎么调
    """
    from nexus.backend.routes import asr as asr_module

    def fake_transcribe(audio_bytes: bytes, mime: str) -> str:
        return "hello world"

    monkeypatch.setattr(asr_module, "_call_whisper_fn", fake_transcribe)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-for-test")
    response = client.post(
        "/api/asr",
        headers=AUTH,
        files={"audio": ("clip.webm", b"\x00" * 2048, "audio/webm")},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"text": "hello world"}


def test_asr_rejects_empty_audio(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """0 bytes payload → 400。

    WHY 测这条:前端录音可能提交空 buffer(用户取消录音),
    后端必须显式拒绝而不是走下游 API 浪费一次调用。
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "")
    response = client.post(
        "/api/asr",
        headers=AUTH,
        files={"audio": ("empty.webm", b"", "audio/webm")},
    )
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_asr_strips_whitespace(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """注入函数返回带空白的文本 → 路由层 .strip() 后返回。

    WHY 单测这条:前端拿到 text 直接塞进 input 框,前后空白会破坏 draft 持久化。
    """
    from nexus.backend.routes import asr as asr_module

    monkeypatch.setattr(
        asr_module,
        "_call_whisper_fn",
        lambda audio_bytes, mime: "  hello  \n",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-for-test")
    response = client.post(
        "/api/asr",
        headers=AUTH,
        files={"audio": ("clip.webm", b"\x00" * 512, "audio/webm")},
    )
    assert response.status_code == 200
    assert response.json()["text"] == "hello"


def test_asr_rejects_oversize(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """>25MB → 413。"""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "")
    big = b"\x00" * (25 * 1024 * 1024 + 1)
    response = client.post(
        "/api/asr",
        headers=AUTH,
        files={"audio": ("big.webm", big, "audio/webm")},
    )
    assert response.status_code == 413


def test_asr_unauthorized(client: TestClient) -> None:
    """缺 token → 401。"""
    response = client.post(
        "/api/asr",
        files={"audio": ("clip.webm", b"\x00" * 64, "audio/webm")},
    )
    assert response.status_code == 401
