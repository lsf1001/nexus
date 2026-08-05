"""share_tokens 持久化层(Round 3 Task 3.3)。

WHY 独立模块:``db.py`` 已逼近 800 行硬约束(§1.2),share helper 属于
业务级 CRUD,跟核心 messages/sessions 持久化分层后,db.py 留余量给
未来 sessions / messages 改动。

依赖单向:``share_store`` 调 ``db.get_session / get_db``,``share.py``
调 ``share_store``;**不**做 ``db.create_share_token = share_store.create_share_token``
这类 re-export,因为 mypy 对属性赋值后的符号追踪不到(db.py 没了定义,
share.py 仍然 ``from . import db`` 然后 ``db.create_share_token`` 会
报 missing attribute)。
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Any

from . import db


def create_share_token(session_id: str, ttl_days: int = 7) -> dict[str, Any]:
    """创建会话分享 token。

    Args:
        session_id: 所属会话 ID。
        ttl_days: 有效期天数(默认 7 天,产品语义固定,不在 UI 暴露配置)。

    Returns:
        ``{"token": str, "expires_at": str}``。token 用
        :func:`secrets.token_urlsafe(32)` 生成,32 字节 url-safe,
        实际串长 43 字符,碰撞概率忽略。

    Raises:
        ValueError: ``session_id`` 不存在(避免 FK violation 抛裸 sqlite 异常)。
    """
    # 显式校验 session 存在;FK 失败也是 IntegrityError,但业务层希望更明确
    if db.get_session(session_id) is None:
        raise ValueError(f"session 不存在: {session_id}")

    token = secrets.token_urlsafe(32)
    now = datetime.now()
    expires_at = (now + timedelta(days=ttl_days)).isoformat()
    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO share_tokens (token, session_id, created_at, expires_at, revoked_at)
            VALUES (?, ?, ?, ?, NULL)
            """,
            (token, session_id, now.isoformat(), expires_at),
        )
    return {"token": token, "expires_at": expires_at}


def get_share_token(token: str) -> dict[str, Any] | None:
    """读取 share_tokens 行,过期或撤销返回 None。

    WHY 在 db 层判 expired/revoked:让 router 层只管 HTTPException 映射,
    业务逻辑(7 天滚动 + revoke 语义)集中在持久化层一处,易测易改。

    Returns:
        含 ``token`` / ``session_id`` / ``created_at`` / ``expires_at`` /
        ``revoked_at`` 的 dict;无效 token(None 行 / 过期 / 撤销)→ None。
    """
    with db.get_db() as conn:
        row = conn.execute(
            "SELECT token, session_id, created_at, expires_at, revoked_at FROM share_tokens WHERE token = ?",
            (token,),
        ).fetchone()
    if row is None:
        return None
    data = dict(row)
    if data["revoked_at"] is not None:
        return None
    if data["expires_at"] <= datetime.now().isoformat():
        return None
    return data


def revoke_share_token(token: str) -> None:
    """撤销 share token(``revoked_at = now``)。

    WHY 签名改 ``-> None``:二次撤销的「是否命中行」语义对调用方无用 ——
    router 层不论命中与否都返回 410(GET 同 token 一律 410,前端不分
    支),而单测用 ``assert db.revoke_share_token(...) is True`` 只是
    误打误撞的乐观断言;改 ``-> None`` 后重复调用走 ``UPDATE ... WHERE
    revoked_at IS NULL`` 命中 0 row,自然 no-op,不抛错。
    """
    now = datetime.now().isoformat()
    with db.get_db() as conn:
        conn.execute(
            "UPDATE share_tokens SET revoked_at = ? WHERE token = ? AND revoked_at IS NULL",
            (now, token),
        )
