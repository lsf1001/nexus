"""真实 LLM E2E driver:不 mock,跑 MiniMax-M3 验证 WS 协议 + HITL。

用法:
    # 先启动后端(无 mock)
    .venv/bin/python3 -c "import uvicorn; uvicorn.run('nexus.backend.main:app', host='0.0.0.0', port=30000, log_level='warning')"
    # 再跑 driver
    .venv/bin/python3 tests/real_llm_driver.py

WHY 在 tests/:用户偏好(feedback-test-files-location)项目内统一目录;此 driver
模拟"真实 LLM 接入"的端到端验证,是测试设施,不是运维脚本。
"""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import websockets

ROOT = Path("/Users/yxb/projects/nexus")
VENV_PY = ROOT / ".venv" / "bin" / "python3"
URL = "ws://127.0.0.1:30000/api/ws?token=nexus-default-token"
SERVER_LOG = Path("/tmp/nexus_real_llm_server.log")


@dataclass
class FrameCheck:
    """单条检查结果。"""

    name: str
    passed: bool
    detail: str = ""


@dataclass
class CheckResult:
    """整轮检查汇总。"""

    checks: list[FrameCheck] = field(default_factory=list)
    frames: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.error is None and all(c.passed for c in self.checks)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append(FrameCheck(name=name, passed=ok, detail=detail))


def _port_listening(port: int, timeout: float = 0.5) -> bool:
    """端口是否在监听。"""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except (TimeoutError, ConnectionRefusedError, OSError):
        return False


def ensure_server() -> None:
    """确保 30000 端口有 nexus 后端在跑(无 mock)。"""
    if _port_listening(30000):
        # 检查是不是 nexus 的进程
        out = subprocess.run(
            ["lsof", "-i", ":30000", "-sTCP:LISTEN", "-n", "-P"], capture_output=True, text=True
        ).stdout
        if "nexus.backend.main" in out or "python" in out.lower():
            print("[real_llm] 检测到现有后端,复用")
            return
        raise RuntimeError(f"端口 30000 被其他进程占用:\n{out}")

    print("[real_llm] 启动真实 LLM 后端...")
    with open(SERVER_LOG, "w") as logf:
        subprocess.Popen(
            [
                str(VENV_PY),
                "-c",
                "import uvicorn; uvicorn.run('nexus.backend.main:app', host='0.0.0.0', port=30000, log_level='info')",
            ],
            cwd=ROOT,
            stdout=logf,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    deadline = time.time() + 45
    while time.time() < deadline:
        if _port_listening(30000):
            # 真实 LLM 后端启动慢(要 MCP / 模型连接),再等 5s
            time.sleep(5)
            return
        time.sleep(0.5)
    raise RuntimeError(f"后端 45s 内未就绪,日志:\n{SERVER_LOG.read_text()[-3000:]}")


async def ws_round_trip(
    user_msg: str,
    *,
    approve_hitl: bool = True,
    timeout: float = 120.0,
) -> list[dict[str, Any]]:
    """WS 单轮交互:发 user_msg → 收帧 → HITL 自动 approve/reject → 收 done。"""
    frames: list[dict[str, Any]] = []
    async with websockets.connect(URL, open_timeout=10) as ws:
        await ws.send(json.dumps({"content": user_msg, "title": "real_llm"}))
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            except TimeoutError:
                frames.append({"type": "_timeout"})
                break
            f = json.loads(raw)
            frames.append(f)
            ty = f.get("type")
            if ty == "confirmation_request":
                resp = {
                    "type": "confirmation_response",
                    "event_id": f["event_id"],
                    "interrupt_id": f["interrupt_id"],
                    "decision": "approve" if approve_hitl else "reject",
                }
                await ws.send(json.dumps(resp))
            elif ty in ("done", "error"):
                break
    return frames


# --- 验证用例 ---


def check_protocol_qa(frames: list[dict[str, Any]]) -> CheckResult:
    """用例 1:简单 Q&A,验证 WS 协议帧序列。"""
    r = CheckResult(frames=frames)
    types = [f.get("type") for f in frames]

    # 必须有 session_created + thinking + chunk + final + done
    r.add("session_created", "session_created" in types, f"types={types[:6]}")
    r.add("thinking_frame_present", "thinking" in types, "")
    chunk_count = sum(1 for t in types if t == "chunk")
    r.add("at_least_one_chunk", chunk_count >= 1, f"chunks={chunk_count}")

    chunks = [f.get("content", "") for f in frames if f.get("type") == "chunk"]
    finals = [f.get("content", "") for f in frames if f.get("type") == "final"]
    r.add("exactly_one_final", len(finals) == 1, f"finals={len(finals)}")
    if chunks and finals:
        joined = "".join(chunks)
        r.add(
            "chunks_concat_equals_final", joined == finals[0], f"len(joined)={len(joined)} len(final)={len(finals[0])}"
        )
    r.add("done_frame_present", "done" in types, "")
    r.add(
        "no_error_frame", "error" not in types, f"frames error 出现: {[f for f in frames if f.get('type') == 'error']}"
    )
    return r


def check_hitl_write(frames: list[dict[str, Any]], target_path: Path) -> CheckResult:
    """用例 2:工具调用 HITL,approve 后文件被创建。

    写用户级 AGENTS.md(deepagents FilesystemPermission mode="interrupt"
    唯一会触发 HITL 的路径)。其它路径(项目源码)按设计默认 allow,
    不会触发 HITL — 详见 test_security_e2e:test_interrupt_on_preserves_allowlist。
    """
    r = CheckResult(frames=frames)
    types = [f.get("type") for f in frames]
    hitl = [f for f in frames if f.get("type") == "confirmation_request"]
    r.add("hitl_frame_present", len(hitl) >= 1, f"hitl_count={len(hitl)}")
    if hitl:
        actions = hitl[0].get("actions") or [{}]
        target = actions[0].get("target_path", "") if actions else ""
        r.add("hitl_target_matches", target == str(target_path), f"target={target}")
    r.add("done_frame_present", "done" in types, "")
    r.add("target_file_exists", target_path.exists(), f"path={target_path}")
    if target_path.exists():
        content = target_path.read_text()
        r.add("file_has_content", len(content) > 0, f"len={len(content)}")
    return r


# --- 主流程 ---


def main() -> int:
    """跑 2 个真实 LLM 用例并打印结果。"""
    print("=" * 70)
    print("Nexus 真实 LLM E2E(无 mock)")
    print("=" * 70)
    ensure_server()

    # 用例 1:简单 Q&A
    print("\n[1/2] 简单 Q&A 协议验证")
    try:
        frames = asyncio.run(ws_round_trip("请用一句话介绍你自己,不超过 20 个字。"))
        result = check_protocol_qa(frames)
        for c in result.checks:
            print(f"  {'✅' if c.passed else '❌'} {c.name}: {c.detail}")
        qa_ok = result.passed
    except Exception as e:
        print(f"  💥 {type(e).__name__}: {e}")
        qa_ok = False

    # 用例 2:HITL 触发 — 写到用户级 AGENTS.md(FilesystemPermission
    # mode="interrupt" 唯一会触发 HITL 的路径,详见 permissions.py)。
    # 真实 LLM 路径(nexus/backend/real_e2e_test.md)按设计默认 allow,
    # 不会触发 HITL,所以这里必须选 AGENTS.md 才能命中。
    # 注:即使 HITL approve 后,QualityGateMiddleware 还会再评估内容
    # 忠实度(防 LLM 写测试占位符污染长期记忆),所以文件可能不落盘 —
    # 这是预期行为,详见 nexus/backend/quality/middleware.py。
    print("\n[2/2] 真实 LLM 触发 HITL (AGENTS.md)")
    target = Path.home() / ".nexus" / "AGENTS.md"
    backup = None
    if target.exists():
        backup = target.read_text()
        target.unlink()
    prompt = (
        f"请使用 write_file 工具,把一段关于【用户偏好简洁回答】的描述(50 字以上中文,"
        f"含具体理由)写入路径 {target}。只调用一次工具,不要询问确认。"
    )
    try:
        frames = asyncio.run(ws_round_trip(prompt, approve_hitl=True, timeout=180))
        result = check_hitl_write(frames, target)
        for c in result.checks:
            print(f"  {'✅' if c.passed else '❌'} {c.name}: {c.detail}")
        hitl_ok = result.passed
    except Exception as e:
        print(f"  💥 {type(e).__name__}: {e}")
        hitl_ok = False
    finally:
        # 清理:还原 AGENTS.md
        if backup is not None:
            target.write_text(backup)
        elif target.exists():
            target.unlink()

    # 清理
    if target.exists():
        target.unlink()

    print("\n" + "=" * 70)
    print(f"汇总: QA={'✅' if qa_ok else '❌'} | HITL={'✅' if hitl_ok else '❌'}")
    print("=" * 70)
    return 0 if (qa_ok and hitl_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
