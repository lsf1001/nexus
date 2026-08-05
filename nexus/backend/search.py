"""Round 3:消息级全文搜索 REST endpoint。

WHY 单独 router:sessions.py 已 800+ 行,加 search 会破单文件 ≤ 800 行约束
(python_project.md §1.2)。新 router 在 main.py 注册,与 sessions / attachments
同辈。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from . import db

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("/messages")
async def search_messages_endpoint(
    q: str = Query(..., min_length=1, description="搜索词(FTS5 syntax)"),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """FTS5 全文搜索消息正文。

    Returns:
        ``{"results": [...], "count": N}``。每条含 session_id / role /
        content / snippet(含 <mark>...</mark> 高亮) / created_at。
    """
    try:
        results = db.search_messages(q, limit=limit)
    except Exception as exc:  # FTS5 syntax 错抛 sqlite3.OperationalError
        raise HTTPException(status_code=400, detail=f"搜索语法错:{exc}") from exc
    return {"results": results, "count": len(results)}
