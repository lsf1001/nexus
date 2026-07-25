"""附件 → LLM multi-part 消息注入。

WHY 独立模块:``agent`` 已是拆分后的包,把"附件拼 multi-part"这一单一职责
放独立文件,避免塞进 ``_agent_builder`` 等已满职责的模块,也便于单测隔离。
"""

from __future__ import annotations

import base64

from ..attachments import read_attachment_image_b64, read_attachment_text

# 除 image/* 外,允许提取全文注入的 mime(其余交由路由层 415 拦截,这里防御兜底)
_TEXT_LIKE_MIMES = ("application/json", "application/pdf")


def build_messages_with_attachments(
    user_text: str,
    attachments: list[dict] | None = None,
) -> list[dict]:
    """把 user_text + attachments 组装成 LLM 消息。

    WHY 双路径:无附件时必须原样返回纯字符串 content,保证与既有对话流
    完全一致(零回归);仅当有附件时才升级为 Anthropic multi-part 数组,
    让 LLM 能"看到"文本全文与图片 base64。

    Args:
        user_text: 用户输入文本
        attachments: list[{file_path, mime, original_name}]，来自 /api/attachments

    Returns:
        LLM messages 列表,默认 ``[{"role": "user", "content": ...}]``。
    """
    if not attachments:
        return [{"role": "user", "content": user_text}]

    content: list[dict] = [{"type": "text", "text": user_text}]
    for att in attachments:
        mime = att.get("mime", "")
        if mime.startswith("image/"):
            detected_mime, raw = read_attachment_image_b64(att["file_path"])
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": detected_mime,
                        "data": base64.b64encode(raw).decode("ascii"),
                    },
                }
            )
        elif mime.startswith("text/") or mime in _TEXT_LIKE_MIMES:
            text = read_attachment_text(att["file_path"])
            content.append(
                {
                    "type": "text",
                    "text": (f"--- attachment: {att['original_name']} ---\n{text}\n--- end attachment ---"),
                }
            )
        # 其它 mime 跳过(已在前置路由层 415 拦截,这里防御性兜底)
    return [{"role": "user", "content": content}]
