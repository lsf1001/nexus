"""附件上传 REST 路由 — multipart/form-data。

WHY 单文件:与 projects.py 同模板,prefix + deps + 一个 router。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from ..api.ws import require_token
from ..attachments import (
    MAX_FILE_SIZE,
    SUPPORTED_MIMES,
    save_attachment,
)
from ..db import get_db

router = APIRouter(
    prefix="/api/attachments",
    tags=["attachments"],
    dependencies=[Depends(require_token)],
)


def _project_dir(project_id: str) -> Path:
    """从 DB 拿 project.path,project 不存在 → 404。"""
    with get_db() as conn:
        row = conn.execute("SELECT path FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Project 不存在: {project_id}")
    return Path(row["path"])


@router.post("", status_code=201)
async def post_attachment(
    project_id: str = Form(...),
    file: UploadFile = File(...),
) -> dict:
    """上传附件 → 写盘 → 落 DB → 返 metadata。"""
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"文件过大(>{MAX_FILE_SIZE // 1024 // 1024}MB)",
        )
    mime = file.content_type or "application/octet-stream"
    if mime not in SUPPORTED_MIMES:
        raise HTTPException(status_code=415, detail=f"不支持的附件类型: {mime}")

    project_dir = _project_dir(project_id)
    try:
        metadata = save_attachment(
            project_dir=project_dir,
            original_name=file.filename or "attachment",
            content=content,
            mime=mime,
        )
    except ValueError as e:
        msg = str(e)
        if "过大" in msg:
            raise HTTPException(status_code=413, detail=msg) from e
        if "不支持" in msg:
            raise HTTPException(status_code=415, detail=msg) from e
        raise HTTPException(status_code=400, detail=msg) from e

    with get_db() as conn:
        conn.execute(
            "INSERT INTO attachments "
            "(id, project_id, original_name, stored_filename, file_path, mime, size, uploaded_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                metadata["id"],
                project_id,
                metadata["original_name"],
                metadata["stored_filename"],
                metadata["file_path"],
                metadata["mime"],
                metadata["size"],
                metadata["uploaded_at"],
            ),
        )
    return {**metadata, "project_id": project_id}


@router.get("/{attachment_id}")
async def get_attachment(attachment_id: str) -> Response:
    """拉 raw 字节,Content-Disposition: inline。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT file_path, original_name, mime FROM attachments WHERE id = ?",
            (attachment_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="附件不存在")
    p = Path(row["file_path"])
    if not p.exists():
        raise HTTPException(status_code=410, detail="文件已被删除")
    return Response(
        content=p.read_bytes(),
        media_type=row["mime"],
        headers={"Content-Disposition": f'inline; filename="{row["original_name"]}"'},
    )


@router.delete("/{attachment_id}", status_code=204)
async def delete_attachment(attachment_id: str) -> Response:
    """删附件(metadata + 文件)。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT file_path FROM attachments WHERE id = ?",
            (attachment_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="附件不存在")
        conn.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
    p = Path(row["file_path"])
    if p.exists():
        p.unlink()
    return Response(status_code=204)
