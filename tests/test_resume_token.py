"""Resume Token 模块的测试。

该文件验证 `nexus.backend.resilience.resume` 模块的核心契约：
  - `make_token(session_id, last_event_id)` 生成 HMAC-SHA256 短 token
  - `verify_token(token, session_id)` 校验签名/绑定/过期
  - 篡改、错配、过期、空值、格式错都抛 `InvalidResumeToken`
  - 入参非法（空/负数/0）抛 `ValueError`
"""

from __future__ import annotations

import base64
import time

import pytest

from nexus.backend.resilience.resume import (
    InvalidResumeToken,
    make_token,
    verify_token,
)


@pytest.fixture
def fixed_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    """注入一个固定的 resume secret，避免测试依赖 CONFIG 默认值。"""
    from nexus.backend import config as config_module

    monkeypatch.setitem(config_module.CONFIG, "resume_secret", "test-secret-xyz-123")
    return "test-secret-xyz-123"


# ---------------- make_token: 基本形态 ----------------


def test_make_token_returns_string(fixed_secret: str) -> None:
    """make_token 返回非空字符串，且包含两段分隔符（exp.event_id.sig）。"""
    token = make_token("sess-1", 42, ttl_seconds=60)
    assert isinstance(token, str)
    assert len(token) > 20
    assert token.count(".") == 2  # exp.event_id.sig


def test_make_token_different_sessions_differ(fixed_secret: str) -> None:
    """不同 session_id 签出的 token 不应相同（签名段会不同）。"""
    t1 = make_token("sess-1", 42, ttl_seconds=60)
    t2 = make_token("sess-2", 42, ttl_seconds=60)
    assert t1 != t2


def test_make_token_different_event_ids_differ(fixed_secret: str) -> None:
    """不同 last_event_id 签出的 token 不应相同。"""
    t1 = make_token("sess-1", 42, ttl_seconds=60)
    t2 = make_token("sess-1", 99, ttl_seconds=60)
    assert t1 != t2


# ---------------- make_token: 参数校验 ----------------


def test_make_token_rejects_empty_session_id(fixed_secret: str) -> None:
    """session_id 为空字符串时抛 ValueError。"""
    with pytest.raises(ValueError, match="session_id"):
        make_token("", 42, ttl_seconds=60)


def test_make_token_rejects_negative_event_id(fixed_secret: str) -> None:
    """last_event_id < 0 时抛 ValueError。"""
    with pytest.raises(ValueError, match="last_event_id"):
        make_token("sess-1", -1, ttl_seconds=60)


def test_make_token_rejects_zero_ttl(fixed_secret: str) -> None:
    """ttl_seconds <= 0 时抛 ValueError（避免立即过期）。"""
    with pytest.raises(ValueError, match="ttl_seconds"):
        make_token("sess-1", 42, ttl_seconds=0)


def test_make_token_rejects_negative_ttl(fixed_secret: str) -> None:
    """ttl_seconds < 0 时抛 ValueError。"""
    with pytest.raises(ValueError, match="ttl_seconds"):
        make_token("sess-1", 42, ttl_seconds=-10)


# ---------------- verify_token: 正常路径 ----------------


def test_verify_token_returns_last_event_id(fixed_secret: str) -> None:
    """verify_token 成功时应返回签发时绑定的 last_event_id。"""
    token = make_token("sess-1", 42, ttl_seconds=60)
    # now 推进 1 秒但远未到 60s 边界
    assert verify_token(token, "sess-1", now=int(time.time()) + 1) == 42


def test_verify_token_zero_event_id_works(fixed_secret: str) -> None:
    """last_event_id = 0 是合法值（新会话从未收到事件时）。"""
    token = make_token("sess-1", 0, ttl_seconds=60)
    assert verify_token(token, "sess-1", now=int(time.time()) + 1) == 0


def test_default_ttl_is_30_minutes(fixed_secret: str) -> None:
    """不传 ttl 时默认 1800 秒（30 分钟）。"""
    token = make_token("sess-1", 0)  # 默认 ttl
    now = int(time.time())
    # 1799 秒后还应有效
    assert verify_token(token, "sess-1", now=now + 1799) == 0
    # 1801 秒后应过期
    with pytest.raises(InvalidResumeToken, match="过期"):
        verify_token(token, "sess-1", now=now + 1801)


# ---------------- verify_token: 过期 ----------------


def test_token_expiration(fixed_secret: str) -> None:
    """超过 ttl 时间后 verify_token 抛 InvalidResumeToken('过期')。"""
    token = make_token("sess-1", 42, ttl_seconds=10)
    with pytest.raises(InvalidResumeToken, match="过期"):
        verify_token(token, "sess-1", now=int(time.time()) + 11)


# ---------------- verify_token: 篡改与错配 ----------------


def test_tampered_signature_raises(fixed_secret: str) -> None:
    """签名段有效位被改应抛 InvalidResumeToken。"""
    token = make_token("sess-1", 42, ttl_seconds=60)
    parts = token.split(".")
    replacement = "A" if parts[2][0] != "A" else "B"
    tampered = ".".join([parts[0], parts[1], replacement + parts[2][1:]])
    with pytest.raises(InvalidResumeToken, match="签名"):
        verify_token(tampered, "sess-1", now=int(time.time()) + 1)


def test_noncanonical_signature_encoding_raises(fixed_secret: str) -> None:
    """解码字节相同但文本不同的 Base64URL 签名也必须拒绝。"""
    token = make_token("sess-1", 42, ttl_seconds=60)
    exp, event_id, signature = token.split(".")
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    replacement = alphabet[alphabet.index(signature[-1]) ^ 1]
    noncanonical = signature[:-1] + replacement

    padding = "=" * (-len(signature) % 4)
    assert base64.urlsafe_b64decode(signature + padding) == base64.urlsafe_b64decode(noncanonical + padding)

    with pytest.raises(InvalidResumeToken, match="签名"):
        verify_token(f"{exp}.{event_id}.{noncanonical}", "sess-1", now=int(time.time()) + 1)


def test_tampered_event_id_raises(fixed_secret: str) -> None:
    """event_id 被改后签名失配，应抛 InvalidResumeToken。"""
    token = make_token("sess-1", 42, ttl_seconds=60)
    parts = token.split(".")
    tampered = f"{parts[0]}.99.{parts[2]}"  # 改 last_event_id 但保留原签名
    with pytest.raises(InvalidResumeToken, match="签名"):
        verify_token(tampered, "sess-1", now=int(time.time()) + 1)


def test_tampered_exp_raises(fixed_secret: str) -> None:
    """exp 被改后签名失配，应抛 InvalidResumeToken。"""
    token = make_token("sess-1", 42, ttl_seconds=60)
    parts = token.split(".")
    tampered = f"{int(parts[0]) + 1}.{parts[1]}.{parts[2]}"  # 改 exp 但保留原签名
    with pytest.raises(InvalidResumeToken, match="签名"):
        verify_token(tampered, "sess-1", now=int(time.time()) + 1)


def test_wrong_session_raises(fixed_secret: str) -> None:
    """token 绑定的 session_id 与校验时给的不一致 → 签名失配。"""
    token = make_token("sess-1", 42, ttl_seconds=60)
    with pytest.raises(InvalidResumeToken, match="签名"):
        verify_token(token, "sess-2", now=int(time.time()) + 1)


# ---------------- verify_token: 格式错 ----------------


def test_malformed_token_raises(fixed_secret: str) -> None:
    """格式不对（段数不对、字段不是数字等）→ InvalidResumeToken。"""
    for bad in [
        "",  # 空
        "abc",  # 一段
        "1.2",  # 两段
        "1.2.3.4",  # 四段
        "a.b.c",  # 字段不是数字
        "1.a.c",  # event_id 不是数字
        "a.1.c",  # exp 不是数字
    ]:
        with pytest.raises(InvalidResumeToken):
            verify_token(bad, "sess-1", now=int(time.time()) + 1)


def test_invalid_base64_signature_raises(fixed_secret: str) -> None:
    """签名段无法 base64url 解码时抛 InvalidResumeToken。"""
    # 字段都是合法数字，但签名段不是合法 base64url
    bad_token = "9999999999.42.!!!notbase64@@@"
    with pytest.raises(InvalidResumeToken):
        verify_token(bad_token, "sess-1", now=int(time.time()) + 1)


def test_empty_inputs_raise(fixed_secret: str) -> None:
    """token 或 session_id 为空时抛 InvalidResumeToken。"""
    with pytest.raises(InvalidResumeToken):
        verify_token("", "sess-1", now=int(time.time()) + 1)
    token = make_token("sess-1", 42, ttl_seconds=60)
    with pytest.raises(InvalidResumeToken):
        verify_token(token, "", now=int(time.time()) + 1)


# ---------------- secret 兜底 ----------------


def test_falls_back_to_ws_token_when_no_resume_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """未配置 NEXUS_RESUME_SECRET 时，应能回退到 CONFIG['ws_token'] 兜底。"""
    from nexus.backend import config as config_module

    # 移除 resume_secret 但保留 ws_token
    monkeypatch.delitem(config_module.CONFIG, "resume_secret", raising=False)
    monkeypatch.setitem(config_module.CONFIG, "ws_token", "ws-fallback-secret-abc")

    token = make_token("sess-1", 7, ttl_seconds=60)
    assert verify_token(token, "sess-1", now=int(time.time()) + 1) == 7


def test_runtime_error_when_no_secret_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """resume_secret 和 ws_token 都未配置时，签发应抛 RuntimeError。"""
    from nexus.backend import config as config_module

    monkeypatch.setitem(config_module.CONFIG, "resume_secret", "")
    monkeypatch.setitem(config_module.CONFIG, "ws_token", "")

    with pytest.raises(RuntimeError, match="resume secret|ws_token"):
        make_token("sess-1", 0, ttl_seconds=60)


# ---------------- 时序安全 ----------------


def test_invalid_signature_raises_invalid_resume_token(fixed_secret: str) -> None:
    """无意义但格式合规的 token：签名段有效 base64 但与期望签名不一致。"""
    # 构造一个时间上有效的 token，签名段是合法的 base64url 但内容错
    bad_token = "9999999999.42.AAAAAAAA"
    with pytest.raises(InvalidResumeToken, match="签名"):
        verify_token(bad_token, "sess-1", now=int(time.time()) + 1)


# ---------------- 模块导出 ----------------


def test_module_exports_expected_symbols() -> None:
    """resume 模块应导出 make_token / verify_token / InvalidResumeToken。"""
    import nexus.backend.resilience.resume as resume_mod

    assert hasattr(resume_mod, "make_token")
    assert hasattr(resume_mod, "verify_token")
    assert hasattr(resume_mod, "InvalidResumeToken")
    assert callable(resume_mod.make_token)
    assert callable(resume_mod.verify_token)
    assert issubclass(resume_mod.InvalidResumeToken, Exception)


def test_invalid_resume_token_is_exception_subclass() -> None:
    """InvalidResumeToken 必须是 Exception 子类（不是 BaseException），便于上层 except Exception 捕获。"""
    err = InvalidResumeToken("test")
    assert isinstance(err, Exception)
    with pytest.raises(InvalidResumeToken):
        raise err
    assert "test" in str(err)
