"""Round 3 Task 3.3:share token CRUD + 会话 markdown 分享渲染。

三个 endpoint:
- ``POST /api/sessions/{session_id}/share`` — 创建 7 天 token
- ``GET /api/share/{token}`` — 拿 markdown(撤销 / 过期 → 410)
- ``DELETE /api/share/{token}`` — 撤销(返回 410,后续 GET 也拿不到)

``render_session_markdown()`` 是公开 helper:同时被本文件的
``GET /api/share/{token}`` 和 ``sessions.py`` 的
``GET /api/sessions/{sid}/export.md`` 复用,确保 share 公开链接
和「导出到本地」看到的格式一致(用户不会因为两个出口不同而困惑)。

WHY 不复用 sessions router:share 路由前缀 ``/api/share/{token}``
跟 ``/api/sessions/{sid}/share`` 嵌套结构不同,合一起两个 prefix
难以一眼看清;单独 router 与 search.py / attachments.py 同模式,
测起来一个 client fixture 复用全部 share 测试。

WHY require_token:share 本身是公开 URL,但**创建**动作必须经
REST 鉴权(防止脚本批量创建);**消费**(GET /api/share/{token})
走同鉴权,避免匿名抓取 — 真正「公开分享」未来可以走独立 anonymous
router + 短 TTL,本轮不做。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from . import db
from .api.ws import require_token

router = APIRouter(prefix="/api", tags=["share"], dependencies=[Depends(require_token)])


def render_session_markdown(session: dict[str, Any], messages: list[dict[str, Any]]) -> str:
    """把 session + messages 序列化为 markdown(share + export 共享格式)。

    格式:
        # {title}
        **Session ID**: `{sid}`
        **Created**: {created_at}
        **Messages**: {count}
        ---
        ## {role} · {created_at}
        {content}
        ...

    WHY thinking_content 不导出:普通 markdown 用户(公众号 / GitHub)
    用不到内部推理;放在「会话内嵌图片」之外属于隐私级细节。

    Returns:
        末尾带 ``\\n`` 的完整 markdown 文本。
    """
    title = session.get("title") or "未命名会话"
    sid = session["id"]
    created_at = session.get("created_at", "")
    count = len(messages)

    lines: list[str] = [
        f"# {title}",
        "",
        f"**Session ID**: `{sid}`",
        f"**Created**: {created_at}",
        f"**Messages**: {count}",
        "",
        "---",
        "",
    ]
    for msg in messages:
        role = msg["role"].capitalize()  # user -> User, assistant -> Assistant
        msg_created = msg.get("created_at", "")
        lines.append(f"## {role} · {msg_created}")
        lines.append("")
        lines.append(msg["content"])
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


@router.post("/sessions/{session_id}/share")
async def create_share(session_id: str) -> dict[str, Any]:
    """创建会话分享 token,7 天有效。

    Returns:
        ``{"token": str, "url": "/api/share/{token}", "expires_at": str}``。
        url 用 path-only(无 host),由前端拼 origin;这样 DMG 内嵌 webview
        和外网部署都走同一逻辑。

    Raises:
        HTTPException 404: session 不存在。
    """
    try:
        result = db.create_share_token(session_id, ttl_days=7)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "token": result["token"],
        "url": f"/api/share/{result['token']}",
        "expires_at": result["expires_at"],
    }


@router.get("/share/{token}", response_class=PlainTextResponse)
async def get_share_markdown(token: str) -> PlainTextResponse:
    """根据 token 返回会话 markdown;撤销 / 过期 / session 已删 → 410。

    WHY 410 Gone 而非 404:410 明确告诉客户端「这个资源曾经存在但永久
    失效」,跟 404(从未存在)语义不同;前端可以基于此显示"链接已撤销"
    而不是"链接打错"。
    """
    record = db.get_share_token(token)
    if record is None:
        raise HTTPException(status_code=410, detail="分享链接已撤销或已过期")

    session = db.get_session(record["session_id"])
    if session is None:
        # session 物理删除但 share_tokens 行还在(罕见):同样 410,
        # 不暴露内部状态,也不让用户继续拿到残留快照。
        raise HTTPException(status_code=410, detail="分享链接已撤销或已过期")
    messages = db.get_messages(record["session_id"])
    body = render_session_markdown(session, messages)
    return PlainTextResponse(content=body, media_type="text/markdown; charset=utf-8")


@router.delete("/share/{token}")
async def revoke_share(token: str) -> None:
    """撤销 share token,返回 410 Gone(GET 同 token 也拿不到)。

    WHY 二次撤销也 410:与 GET 路径语义对齐,前端不用区分"刚撤"与
    "早就没了",统一走"链接不可用"提示;避免 204 vs 410 让 UI 写两套分支。
    """
    db.revoke_share_token(token)
    raise HTTPException(status_code=410, detail="分享链接已撤销")
