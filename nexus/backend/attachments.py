"""附件 storage helper — 落盘 + mime 校验 + 大小校验。

WHY 独立模块:与 routes/attachments.py 分离,REST 层只做 HTTP 边界,
本模块负责文件 IO + 校验 + filename 安全。便于在 main 启动时 ensure 目录存在。
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB;与 SPEC §4.1 一致

SUPPORTED_MIMES: frozenset[str] = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "application/pdf",
        "text/plain",
        "text/markdown",
        "text/csv",
        "application/json",
        "text/x-python",
        "text/x-javascript",
        "application/javascript",
        "application/typescript",
        "text/jsx",
        "text/tsx",
    }
)


def _safe_ext(original_name: str, mime: str) -> str:
    """从原始文件名提取扩展名,做路径穿越防护。

    只保留字母数字下划线点,其它字符替换为下划线。空扩展时按 mime 给一个 fallback。
    """
    if "." in original_name:
        ext = original_name.rsplit(".", 1)[-1].lower()
        if re.fullmatch(r"[a-z0-9]{1,8}", ext):
            return f".{ext}"
    fallback = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "application/pdf": ".pdf",
        "text/plain": ".txt",
        "text/markdown": ".md",
        "text/csv": ".csv",
        "application/json": ".json",
    }.get(mime, "")
    return fallback


def ensure_uploads_dir(project_dir: Path) -> Path:
    """确保 project_dir/uploads/ 存在,返回 uploads 目录 Path。"""
    uploads = project_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    return uploads


def save_attachment(
    *,
    project_dir: Path,
    original_name: str,
    content: bytes,
    mime: str,
) -> dict[str, str | int]:
    """把附件写到 project_dir/uploads/att_<uuid><ext>,返回 metadata 字典。

    Raises:
        ValueError: size 超限 或 mime 不支持
    """
    if mime not in SUPPORTED_MIMES:
        raise ValueError(f"不支持的附件类型: {mime}")
    if len(content) > MAX_FILE_SIZE:
        raise ValueError(f"文件过大(>{MAX_FILE_SIZE // 1024 // 1024}MB)")
    uploads = ensure_uploads_dir(project_dir)
    ext = _safe_ext(original_name, mime)
    stored_filename = f"att_{uuid.uuid4().hex}{ext}"
    file_path = uploads / stored_filename
    file_path.write_bytes(content)
    return {
        "id": uuid.uuid4().hex,
        "original_name": original_name,
        "stored_filename": stored_filename,
        "file_path": str(file_path),
        "mime": mime,
        "size": len(content),
        "uploaded_at": datetime.now(UTC).isoformat(),
    }


def read_attachment_text(file_path: str, max_chars: int = 20000) -> str:
    """读文本附件内容,超 max_chars 截断并加末尾标记(SPEC §4.4)。"""
    text = Path(file_path).read_text(encoding="utf-8", errors="replace")
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n... (已截断,原 {len(text)} 字符)"
    return text


def read_attachment_image_b64(file_path: str) -> tuple[str, str]:
    """读图片附件,返 (mime, base64-encoded str)。mime 从 file_path 后缀推。"""
    import base64 as _b64

    p = Path(file_path)
    ext = p.suffix.lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(ext, "application/octet-stream")
    return mime, _b64.b64encode(p.read_bytes()).decode("ascii")
