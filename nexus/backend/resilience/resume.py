"""基于 HMAC-SHA256 的会话续传 token。

设计目标：
  - 给客户端一个短 token，断线重连时带回，服务端可据此从 `last_event_id`
    继续下发事件，避免从头重放。
  - token 绑定 `session_id`（防跨会话冒用）+ `last_event_id`（断点）+ `exp`（过期）。
  - 篡改/过期/错配/格式错都通过 :class:`InvalidResumeToken` 异常统一暴露。

token 格式（3 段，base64url 编码无 padding）：
    "{exp}.{last_event_id}.{sig_b64url}"

其中：
    exp           = 签发时的过期时间（Unix 秒，int）
    last_event_id = 客户端最后收到的事件 ID（int，>= 0）
    sig_b64url    = HMAC-SHA256(secret, f"{session_id}:{last_event_id}:{exp}") 的 base64url 编码

签名输入的 payload 形如 "sess-1:42:1717700000"，验证时只要 payload 与签发时一致，
HMAC 校验通过即视为未被篡改。

secret 取值：
  1. 优先从 CONFIG['resume_secret'] 取（环境变量 NEXUS_RESUME_SECRET）；
  2. 缺省回退到 CONFIG['ws_token']（避免历史部署直接无法签发）；
  3. 两者都为空时抛 :class:`RuntimeError`（绝不静默用空 secret）。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from typing import Final

from ..config import CONFIG

__all__ = [
    "InvalidResumeToken",
    "make_token",
    "verify_token",
]


# 默认有效期 30 分钟。客户端断线后能续传的最长窗口；超过则视为新会话。
_DEFAULT_TTL_S: Final[int] = 1800


class InvalidResumeToken(Exception):  # noqa: N818  # 计划文档固定命名
    """Resume token 无效（篡改/过期/session 不匹配/格式错/字段为空）。"""


def _get_secret() -> str:
    """从 CONFIG 取 NEXUS_RESUME_SECRET，缺省用 ws_token 兜底。

    Raises:
        RuntimeError: 两个 secret 都没配置时。
    """
    resume_secret = CONFIG.get("resume_secret") or ""
    if resume_secret:
        return resume_secret

    ws_token = CONFIG.get("ws_token") or ""
    if ws_token:
        return ws_token

    raise RuntimeError("未配置 NEXUS_RESUME_SECRET 或 ws_token，无法签发 resume token")


def _b64url_encode(raw: bytes) -> str:
    """base64url 编码并去掉 padding，便于作为 token 段。"""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    """补回 padding 后 base64url 解码；输入非法时抛 ValueError。"""
    padding = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + padding)


def make_token(
    session_id: str,
    last_event_id: int,
    ttl_seconds: int = _DEFAULT_TTL_S,
) -> str:
    """签发 HMAC-SHA256 resume token。

    Args:
        session_id: 会话唯一标识（绑定到 token 中，校验时必须一致）。
        last_event_id: 客户端最后收到的事件 ID（>= 0，用于续传定位）。
        ttl_seconds: 有效期（秒），必须 > 0。默认 1800（30 分钟）。

    Returns:
        base64url 编码的短 token，形如 ``"1717700000.42.AbC123..."``。

    Raises:
        ValueError: session_id 为空、last_event_id < 0、ttl_seconds <= 0。
        RuntimeError: CONFIG 中 resume_secret 和 ws_token 都未配置。
    """
    if not session_id:
        raise ValueError("session_id 不能为空")
    if last_event_id < 0:
        raise ValueError("last_event_id 必须 >= 0")
    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds 必须 > 0")

    exp = int(time.time()) + ttl_seconds
    payload = f"{session_id}:{last_event_id}:{exp}"
    secret = _get_secret()
    sig = hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return f"{exp}.{last_event_id}.{_b64url_encode(sig)}"


def verify_token(
    token: str,
    session_id: str,
    now: int | None = None,
) -> int:
    """校验 resume token，返回绑定的事件 ID。

    校验顺序：
      1. 非空检查（token / session_id 都不能为空）。
      2. 段数 = 3 且前两段是合法 int。
      3. 签名段可 base64url 解码。
      4. HMAC-SHA256 重算签名，与 token 签名段做 **常数时间** 比较。
      5. exp > now（未过期）。

    任一步失败抛 :class:`InvalidResumeToken`，错误信息按步骤区分以便日志诊断。

    Args:
        token: 待校验的 token。
        session_id: 当前会话 ID（必须与签发时一致）。
        now: 当前 Unix 秒（默认 ``int(time.time())``；测试时可注入避免 sleep）。

    Returns:
        解码后的 ``last_event_id``。

    Raises:
        InvalidResumeToken: token 格式错/字段空/签名失配/已过期。
        RuntimeError: CONFIG 中 secret 未配置（理论上不会到这里，
            因为 make_token 已经校验过；但 verify_token 被独立调用时
            仍可能命中）。
    """
    if not token or not session_id:
        raise InvalidResumeToken("token 或 session_id 为空")

    parts = token.split(".")
    if len(parts) != 3:
        raise InvalidResumeToken("token 格式错误（段数不对）")

    exp_str, event_id_str, sig_b64 = parts
    try:
        exp = int(exp_str)
        last_event_id = int(event_id_str)
    except ValueError as err:
        raise InvalidResumeToken("token 格式错误（exp 或 last_event_id 不是整数）") from err

    if last_event_id < 0:
        raise InvalidResumeToken("token 格式错误（last_event_id < 0）")

    try:
        sig = _b64url_decode(sig_b64)
    except (ValueError, TypeError, base64.binascii.Error) as err:  # type: ignore[attr-defined]
        # base64 模块在不同版本下抛不同的异常类；都归为格式错。
        raise InvalidResumeToken("token 签名段无法 base64url 解码") from err

    payload = f"{session_id}:{last_event_id}:{exp}"
    secret = _get_secret()
    expected_sig = hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(sig, expected_sig):
        # 注意：先比签名再判过期，避免泄露过期时间。
        raise InvalidResumeToken("token 签名不匹配（可能篡改或 session 错配）")

    current = now if now is not None else int(time.time())
    if exp < current:
        raise InvalidResumeToken("token 已过期")

    return last_event_id
