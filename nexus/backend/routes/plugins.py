"""GET /api/plugins。

WHY 单独 router:跟 skills / mcp / settings 这些 router 同辈;
扫描逻辑放 plugins_scanner.py,这里只做 HTTP 包装。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..api.ws import require_token
from ..plugins_scanner import scan_plugins

router = APIRouter(prefix="/api/plugins", tags=["plugins"], dependencies=[Depends(require_token)])


@router.get("")
async def list_plugins() -> dict:
    """列出 ~/.nexus/plugins/ 下所有 manifest。

    无目录 / 无 plugin → 200 + 空 list(不是 404)。
    """
    return {"plugins": scan_plugins()}
