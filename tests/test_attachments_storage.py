"""附件 storage helper 单测 — 文件落盘 + mime 嗅探 + 大小校验。"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from nexus.backend.attachments import (
    MAX_FILE_SIZE,
    SUPPORTED_MIMES,
    save_attachment,
)


def test_save_attachment_writes_file(tmp_path: Path) -> None:
    """附件落盘成功 → 返回 id + 文件存在 + size 一致。"""
    project_dir = tmp_path / "default"
    project_dir.mkdir()
    payload = b"hello world"
    att = save_attachment(
        project_dir=project_dir,
        original_name="note.txt",
        content=payload,
        mime="text/plain",
    )
    UUID(att["id"])
    stored = project_dir / "uploads" / att["stored_filename"]
    assert stored.exists()
    assert stored.read_bytes() == payload
    assert att["size"] == len(payload)
    assert att["mime"] == "text/plain"
    assert att["original_name"] == "note.txt"


def test_save_attachment_rejects_oversize(tmp_path: Path) -> None:
    """超过 20MB 抛 ValueError(转 413 给 route)。"""
    project_dir = tmp_path / "default"
    project_dir.mkdir()
    payload = b"x" * (MAX_FILE_SIZE + 1)
    with pytest.raises(ValueError, match="文件过大"):
        save_attachment(
            project_dir=project_dir,
            original_name="big.bin",
            content=payload,
            mime="text/plain",
        )


def test_save_attachment_rejects_unsupported_mime(tmp_path: Path) -> None:
    """不支持的 mime 抛 ValueError。"""
    project_dir = tmp_path / "default"
    project_dir.mkdir()
    with pytest.raises(ValueError, match="不支持的附件类型"):
        save_attachment(
            project_dir=project_dir,
            original_name="x.exe",
            content=b"x",
            mime="application/x-msdownload",
        )


def test_save_attachment_sanitizes_extension(tmp_path: Path) -> None:
    """文件名包含 ../ 会被剥离,只保留扩展名。"""
    project_dir = tmp_path / "default"
    project_dir.mkdir()
    att = save_attachment(
        project_dir=project_dir,
        original_name="../../etc/passwd.txt",
        content=b"safe",
        mime="text/plain",
    )
    assert ".." not in att["stored_filename"]
    assert att["stored_filename"].endswith(".txt")


def test_supported_mimes_includes_image_text_pdf() -> None:
    """白名单含 SPEC §4.3 要求的 mime。"""
    assert "image/png" in SUPPORTED_MIMES
    assert "image/jpeg" in SUPPORTED_MIMES
    assert "text/plain" in SUPPORTED_MIMES
    assert "application/pdf" in SUPPORTED_MIMES
