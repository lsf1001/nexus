"""CLI 辅助：把 quality_scores 历史转成 PreferenceRecord 列表。

这个模块独立成文件以避免 exporter.py 直接依赖 db 模块（也方便测试 mock）。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .exporter import PreferenceRecord

logger = logging.getLogger(__name__)


def load_preference_records(
    min_score: float = 0.0,
    max_records: int = 10_000,
) -> list[PreferenceRecord]:
    """从 quality_scores 表 + messages 表构造 PreferenceRecord 列表。

    构造策略：按 (session_id, rubric_name) 分组，每组内选最高分作
    accepted，最低分作 rejected；要求 score gap >= 0.3（由 exporter
    再做最终过滤）。

    Args:
        min_score: 最低分阈值；低于此分的 score 直接跳过。
        max_records: 最多返回多少条（避免 OOM）。

    Returns:
        :class:`PreferenceRecord` 列表（可能为空）。
    """
    from ..db import get_db
    from .exporter import PreferenceRecord

    records: list[PreferenceRecord] = []
    try:
        with get_db() as conn:
            # 简化查询：取最近 N 条 quality_scores 记录，按 (session_id, rubric) 分组
            rows = conn.execute(
                """
                SELECT session_id, rubric, score, verdict, reasoning, message_id
                FROM quality_scores
                WHERE score >= ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (min_score, max_records),
            ).fetchall()
    except Exception as exc:  # noqa: BLE001 — CLI 容错
        logger.warning("读 quality_scores 失败: %s", exc)
        return records

    # 简化分组（实际可优化；这里只保证正确性）
    by_key: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        key = (row["session_id"], row["rubric"])
        by_key.setdefault(key, []).append(dict(row))

    for (session_id, rubric), entries in by_key.items():
        # 按 message_id 分桶：每个 message_id 可能有 4 个 rubric 的分数（一次响应的所有评分）
        # 选 top/bottom 时按"该 message 在这个 rubric 上的最高分"和"最低分"
        by_message: dict[str, list[dict]] = {}
        for entry in entries:
            mid = entry["message_id"]
            if not mid:
                continue
            by_message.setdefault(mid, []).append(entry)
        if len(by_message) < 2:
            continue
        # 计算每个 message 的平均分作为 ranking key
        message_scores: list[tuple[str, float]] = [
            (mid, sum(e["score"] for e in ents) / len(ents))
            for mid, ents in by_message.items()
        ]
        message_scores.sort(key=lambda x: x[1], reverse=True)
        top_mid = message_scores[0][0]
        bot_mid = message_scores[-1][0]
        if top_mid == bot_mid:
            continue
        # 用任一 entry 拿 session_id / verdict / reasoning（top / bottom 各拿自己的）
        top_entries = by_message[top_mid]
        bot_entries = by_message[bot_mid]
        top = max(top_entries, key=lambda e: e["score"])
        bottom = min(bot_entries, key=lambda e: e["score"])
        # 拿 message 内容
        try:
            with get_db() as conn:
                top_msg = conn.execute(
                    "SELECT content FROM messages WHERE id = ?", (top_mid,)
                ).fetchone()
                bot_msg = conn.execute(
                    "SELECT content FROM messages WHERE id = ?", (bot_mid,)
                ).fetchone()
        except Exception:  # noqa: BLE001 — 容错
            top_msg = bot_msg = None
        if not top_msg or not bot_msg:
            continue
        # 拿 prompt：取 top 消息前一条 user 消息
        try:
            with get_db() as conn:
                prompt_row = conn.execute(
                    """
                    SELECT content FROM messages
                    WHERE session_id = ? AND role = 'user'
                      AND created_at < (SELECT created_at FROM messages WHERE id = ?)
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (session_id, top["message_id"]),
                ).fetchone()
        except Exception:  # noqa: BLE001 — 容错
            prompt_row = None
        prompt = prompt_row["content"] if prompt_row else ""

        records.append(
            PreferenceRecord(
                prompt=prompt,
                accepted=top_msg["content"],
                accepted_score=top["score"],
                rejected=bot_msg["content"],
                rejected_score=bottom["score"],
                session_id=session_id,
                rubric_name=rubric,
            )
        )

    return records
