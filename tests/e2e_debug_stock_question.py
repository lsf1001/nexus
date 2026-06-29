"""E2E 复现 2026-06-29 用户报告的"元力股份 能买吗"LLM 答非所问 bug。

WHY: 用户在前端看到 LLM 回复"我是 Nexus,由 agnes-2.0-flash 驱动..."(系统
prompt FACT 块的自报身份话术),但 yandex_search 已搜到 162 / 135 / 7398 字
的搜索结果,LLM 没用。怀疑是某个 LLM(MiniMax-M3)把投资问题错判为身份问
句,复读 system prompt 硬指令。本脚本通过 WS 直接发问并落盘所有 chunk,
确认 agnes 模型是否能正确用搜索结果回答。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import websockets

WS_URL = "ws://localhost:30000/api/ws?token=nexus-default-token"
TOKEN = "nexus-default-token"
QUESTION = "元力股份 能买吗"
SESSION_ID = "e2e-stock-test-2026-06-29"
USER_ID = "e2e-test"


async def run_one_question() -> dict[str, object]:
    """连一次 WS,发问,把所有 chunk 收集起来返回。"""
    collected: dict[str, object] = {
        "chunks": [],
        "thinking": [],
        "final": None,
        "tool_starts": [],
        "tool_ends": [],
        "errors": [],
        "done_received": False,
    }

    async with websockets.connect(WS_URL, max_size=64 * 1024 * 1024) as ws:
        # 1) 用户消息帧
        await ws.send(
            json.dumps(
                {
                    "type": "chat",
                    "session_id": SESSION_ID,
                    "user_id": USER_ID,
                    "content": QUESTION,
                },
                ensure_ascii=False,
            )
        )

        # 2) 等所有 chunk / final / done
        deadline = asyncio.get_event_loop().time() + 240.0
        while asyncio.get_event_loop().time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=120.0)
            except TimeoutError:
                collected["errors"].append("WS recv timeout (120s)")
                break

            try:
                frame = json.loads(raw)
            except json.JSONDecodeError:
                collected["errors"].append(f"non-JSON frame: {raw[:200]}")
                continue

            frame_type = frame.get("type")
            content = frame.get("content", "")
            event_id = frame.get("event_id")

            if frame_type == "chunk":
                collected["chunks"].append((event_id, content))
            elif frame_type == "thinking":
                collected["thinking"].append((event_id, content))
            elif frame_type == "final":
                collected["final"] = content
            elif frame_type == "tool_start":
                collected["tool_starts"].append((event_id, content))
            elif frame_type == "tool_end":
                collected["tool_ends"].append((event_id, content))
            elif frame_type == "done":
                collected["done_received"] = True
                break
            elif frame_type == "error":
                collected["errors"].append(f"server error: {frame}")
            else:
                collected["errors"].append(f"unknown frame type: {frame_type} content={content[:80]}")

    collected["chunks_full"] = "".join(c for _, c in collected["chunks"])
    return collected


def dump_report(result: dict[str, object], out_path: Path) -> None:
    """把结果写到文件 + 控制台摘要,方便人工对比。"""
    lines: list[str] = []
    lines.append(f"=== E2E 复现: {QUESTION} ===")
    lines.append("active model at start of test (assumed agnes)")
    lines.append(f"chunks 数: {len(result['chunks'])}")
    lines.append(f"thinking 数: {len(result['thinking'])}")
    lines.append(f"tool 数: {len(result['tool_starts'])}")
    lines.append(f"final 非空: {bool(result['final'])}")
    lines.append(f"done_received: {result['done_received']}")
    lines.append("")
    lines.append("--- tool calls ---")
    for eid, content in result["tool_starts"]:
        lines.append(f"  [{eid}] {content[:120]}")
    lines.append("")
    lines.append("--- chunks 拼接 (full response) ---")
    lines.append(result["chunks_full"] or "(空)")
    lines.append("")
    lines.append("--- final frame ---")
    lines.append(str(result["final"]) or "(空)")
    if result["errors"]:
        lines.append("")
        lines.append("--- errors ---")
        for e in result["errors"]:
            lines.append(f"  {e}")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"完整报告写入: {out_path}")
    print(f"chunks 字符数: {len(result['chunks_full'])}")
    print("前 500 字符:")
    print(result["chunks_full"][:500])


async def main() -> int:
    out_dir = Path("/tmp/nexus_e2e_out")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "stock_question_repro.txt"

    result = await run_one_question()
    dump_report(result, out_path)

    # 判定: 如果 chunks 拼接内容是"我是 Nexus"开头 + 没有元力股份实质分析,
    # 说明 LLM 把投资问题错判为身份问题。否则正常。
    full = result["chunks_full"] or ""
    is_identity_reply = "我是 Nexus" in full[:200] and "元力" not in full
    if is_identity_reply:
        print("\n❌ BUG 复现: LLM 答非所问,复读身份话术")
        return 1
    if full and "元力" in full:
        print("\n✅ 正常: LLM 用了搜索结果回答了元力股份")
        return 0
    print("\n⚠️ 异常: chunks 为空或不含元力股份关键词,见报告")
    return 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
