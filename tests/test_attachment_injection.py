"""附件注入 LLM multi-part 单测。"""

from __future__ import annotations

from pathlib import Path


def test_read_attachment_text_under_limit(tmp_path: Path) -> None:
    """< 20000 字符 全文返回。"""
    from nexus.backend.attachments import read_attachment_text

    p = tmp_path / "a.txt"
    p.write_text("hello", encoding="utf-8")
    text = read_attachment_text(str(p))
    assert text == "hello"


def test_read_attachment_text_truncates(tmp_path: Path) -> None:
    """> 20000 字符 末尾加截断标记。"""
    from nexus.backend.attachments import read_attachment_text

    p = tmp_path / "a.txt"
    p.write_text("x" * 25000, encoding="utf-8")
    text = read_attachment_text(str(p))
    assert text.startswith("x" * 20000)
    assert "已截断" in text
    assert "25000" in text


def test_read_attachment_image_b64_roundtrip(tmp_path: Path) -> None:
    """图片按后缀判 mime + 返原 bytes。"""
    from nexus.backend.attachments import read_attachment_image_b64

    p = tmp_path / "x.png"
    raw = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    p.write_bytes(raw)
    mime, data = read_attachment_image_b64(str(p))
    assert mime == "image/png"
    assert data == raw


def test_build_messages_with_attachment_text(tmp_path: Path) -> None:
    """build_messages_with_attachments(纯文本附件)→ content 是 multi-part text 数组。"""
    from nexus.backend.agent import build_messages_with_attachments
    from nexus.backend.attachments import save_attachment

    p = tmp_path / "default"
    p.mkdir()
    att = save_attachment(
        project_dir=p,
        original_name="note.txt",
        content=b"file content",
        mime="text/plain",
    )
    msgs = build_messages_with_attachments(
        user_text="解释这个文件",
        attachments=[att],
    )
    assert len(msgs) == 1
    content = msgs[0]["content"]
    assert isinstance(content, list)
    assert content[0] == {"type": "text", "text": "解释这个文件"}
    assert content[1]["type"] == "text"
    assert "file content" in content[1]["text"]
    assert "note.txt" in content[1]["text"]


def test_build_messages_with_attachment_image(tmp_path: Path) -> None:
    """图片附件 → image multi-part(Anthropic 格式)。"""
    import base64

    from nexus.backend.agent import build_messages_with_attachments
    from nexus.backend.attachments import save_attachment

    p = tmp_path / "default"
    p.mkdir()
    raw = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
    att = save_attachment(
        project_dir=p,
        original_name="snap.png",
        content=raw,
        mime="image/png",
    )
    msgs = build_messages_with_attachments(
        user_text="这张图是什么?",
        attachments=[att],
    )
    content = msgs[0]["content"]
    assert content[1]["type"] == "image"
    src = content[1]["source"]
    assert src["type"] == "base64"
    assert src["media_type"] == "image/png"
    assert base64.b64decode(src["data"]) == raw


def test_build_messages_no_attachments_returns_text() -> None:
    """无附件 → 返原纯 text 路径(零回归)。"""
    from nexus.backend.agent import build_messages_with_attachments

    msgs = build_messages_with_attachments(user_text="hi")
    assert msgs == [{"role": "user", "content": "hi"}]


def test_build_messages_empty_attachments_returns_text() -> None:
    """空 attachments 列表 → 同样走纯 text 路径(边界)。"""
    from nexus.backend.agent import build_messages_with_attachments

    msgs = build_messages_with_attachments(user_text="hi", attachments=[])
    assert msgs == [{"role": "user", "content": "hi"}]
