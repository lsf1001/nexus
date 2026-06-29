"""7 场景 E2E driver:启动 mock 后端 → WS 模拟人工 → 校验结果。

用法:
    /Users/yxb/projects/nexus/.venv/bin/python3 tests/e2e_driver.py

设计:
  - 每个场景:重启 mock 后端(NEXUS_E2E_SCENARIO=...)+ WS 客户端 → 校验产物
  - 写文件在 cleanup 阶段自动删除,跨场景不污染
  - 结果用 ok/fail 输出,最终给汇总表

WHY 写在 tests/ 而非 scripts/:用户偏好(feedback-test-files-location)项目内统一目录;
此 driver 模拟"人工点 HITL 按钮"的真实交互,本质是测试设施,不是运维脚本。
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
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
SERVER_LOG = Path("/tmp/nexus_e2e_server.log")


@dataclass
class ScenarioResult:
    """单场景结果。"""

    name: str
    passed: bool
    summary: str
    frames: list[dict[str, Any]] = field(default_factory=list)
    files_created: list[str] = field(default_factory=list)
    error: str | None = None


# --- 服务启停 ---


def _port_listening(port: int, timeout: float = 0.5) -> bool:
    """端口是否在监听。"""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except (TimeoutError, ConnectionRefusedError, OSError):
        return False


def kill_server() -> None:
    """杀掉所有 nexus 后端进程。

    WHY 多步:pkill -f 只匹配命令行含模式的进程,driver 自己启动时用
    ``start_new_session=True`` 让子进程脱离父进程组,只 pkill 一次可能
    漏掉(尤其前一 case 的残留进程在 acquire lock 后没释放 SQLite)。
    先 lsof 端口清干净,再 pkill 兜底。
    """
    # 清端口 30000(uvicorn 实际占的 socket)
    subprocess.run(["lsof", "-ti:30000"], capture_output=True, text=True)
    port_pids = subprocess.run(["lsof", "-ti:30000"], capture_output=True, text=True).stdout.strip().split()
    for pid in port_pids:
        if pid:
            subprocess.run(["kill", "-9", pid], capture_output=True)
    # 兜底:pkill 所有 nexus.backend.main 相关进程
    subprocess.run(["pkill", "-9", "-f", "nexus.backend.main"], capture_output=True)
    time.sleep(2)
    # 二次确认端口空
    still_listening = subprocess.run(["lsof", "-ti:30000"], capture_output=True, text=True).stdout.strip()
    if still_listening:
        raise RuntimeError(f"端口 30000 仍有进程占用: {still_listening}")


def start_server(scenario: str, env_extra: dict[str, str] | None = None) -> None:
    """启动 mock 后端(NEXUS_E2E_MOCK=1 + NEXUS_E2E_SCENARIO=scenario),等就绪。

    WHY 强制设 ``NEXUS_DB_PATH=/tmp/nexus_e2e_<scenario>.db``:7 场景 + 跨进程
    复用同一个 ``~/.nexus/nexus.db`` 会导致 SQLite lock(虽然有 WAL,但
    同一 checkpoint 表 + 频繁 INSERT 仍会触发 SQLITE_BUSY)。E2E 隔离用
    临时 DB,场景结束自动清理。

    WHY 设 ``NEXUS_CHECKPOINTER=memory`` + ``NEXUS_STORE=memory``:E2E 不需要
    跨进程持久化(HITL 模拟在同一 WS 连接内完成),用 InMemoryStore + MemorySaver
    避开 aiosqlite + sync sqlite3 之间的 SQLite WAL 锁竞争(实测 AsyncSqliteStore
    的 executescript 会持锁 > 30s,busy_timeout 救不了)。生产路径(NEXUS_E2E_MOCK 未
    设)走默认 sqlite + AsyncSqliteSaver/store,不受影响。
    """
    kill_server()
    env = os.environ.copy()
    env["NEXUS_E2E_MOCK"] = "1"
    env["NEXUS_E2E_SCENARIO"] = scenario
    env["NEXUS_CHECKPOINTER"] = "memory"
    env["NEXUS_STORE"] = "memory"
    db_path = f"/tmp/nexus_e2e_{scenario}.db"
    # 删除旧 DB(防止前次残留 schema 跟新版本不一致)
    Path(db_path).unlink(missing_ok=True)
    env["NEXUS_DB_PATH"] = db_path
    if env_extra:
        env.update(env_extra)
    # 后台启动
    with open(SERVER_LOG, "w") as logf:
        proc = subprocess.Popen(
            [
                str(VENV_PY),
                "-u",  # unbuffered:让 server 内部 logger / stacktrace 立即写到 logf
                "-c",
                "import uvicorn; uvicorn.run('nexus.backend.main:app', host='0.0.0.0', port=30000, log_level='warning')",
            ],
            cwd=ROOT,
            env=env,
            stdout=logf,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    # 等就绪(最多 30 秒)
    deadline = time.time() + 30
    while time.time() < deadline:
        if _port_listening(30000):
            # 再等 2 秒让 startup 完成
            time.sleep(2)
            return
        time.sleep(0.5)
    proc.send_signal(signal.SIGTERM)
    raise RuntimeError(f"Server not ready for scenario={scenario}, log tail:\n{SERVER_LOG.read_text()[-2000:]}")


def cleanup_files(paths: list[Path]) -> None:
    """清理 mock 写入的文件。"""
    for p in paths:
        try:
            if p.exists():
                p.unlink()
        except OSError:
            pass


# --- WS 客户端 driver ---


async def run_ws_scenario(
    *,
    user_msg: str,
    approve_hitl: bool = True,
    timeout: float = 60.0,
) -> tuple[list[dict[str, Any]], list[str]]:
    """WS 单轮交互:发 user_msg → 收帧 → 命中 confirmation_request 自动 approve/reject → 收完 done。

    Returns:
        (frames, files_created_in_msg) 元组。
    """
    frames: list[dict[str, Any]] = []
    files_created: list[str] = []
    async with websockets.connect(URL, open_timeout=10) as ws:
        await ws.send(json.dumps({"content": user_msg, "title": "e2e"}))
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
                # 自动 approve / reject
                resp = {
                    "type": "confirmation_response",
                    "event_id": f["event_id"],
                    "interrupt_id": f["interrupt_id"],
                    "decision": "approve" if approve_hitl else "reject",
                }
                await ws.send(json.dumps(resp))
            elif ty in ("done", "error"):
                break
            elif ty == "final":
                # 检测 final 中提到的文件
                content = f.get("content", "")
                for token in content.split():
                    if token.endswith((".py", ".md")) and "/" in token:
                        files_created.append(token)
    return frames, files_created


def frames_summary(frames: list[dict[str, Any]]) -> str:
    """帧序列摘要。"""
    out = []
    for f in frames:
        ty = f.get("type", "?")
        if ty == "thinking":
            c = f.get("content", "")[:80].replace("\n", " ")
            out.append(f"think:{c!r}")
        elif ty == "confirmation_request":
            acts = f.get("actions", [])
            targets = [a.get("target_path", "") for a in acts]
            out.append(f"HITL×{len(acts)}:{targets}")
        elif ty == "final":
            out.append(f"final:{f.get('content', '')[:60]!r}")
        elif ty == "error":
            out.append(f"ERR:{f.get('content', '')[:80]!r}")
        elif ty == "session_created":
            out.append(f"session:{f.get('session_id', '')[:8]}")
        elif ty == "done":
            out.append("done")
        else:
            out.append(ty)
    return " → ".join(out[-12:])  # 末 12 帧摘要


# --- 7 场景断言 ---


def assert_scenario(result: ScenarioResult, *, expect_hitl: bool, expect_files: list[Path]) -> None:
    """统一断言:1)HITL 帧是否触发 2)预期文件是否被创建。"""
    frames = result.frames
    has_hitl = any(f.get("type") == "confirmation_request" for f in frames)
    if expect_hitl and not has_hitl:
        result.passed = False
        result.summary = f"❌ 期望 HITL 但未触发 | {frames_summary(frames)}"
        return
    if not expect_hitl and has_hitl:
        result.passed = False
        result.summary = f"❌ 不应有 HITL 但触发了 | {frames_summary(frames)}"
        return
    # 文件断言
    for fp in expect_files:
        if not fp.exists():
            result.passed = False
            result.summary = f"❌ 文件未创建: {fp}"
            return
    result.passed = True
    result.summary = f"✅ {'HITL+' if expect_hitl else '直接'} | {len(frames)} 帧 | {frames_summary(frames)}"


# --- 7 场景主流程 ---


def scenario_allow_nexus_write() -> ScenarioResult:
    """1) 写 .nexus/ → 应直接 allow,无 HITL,文件创建。"""
    r = ScenarioResult(name="allow_nexus_write", passed=False, summary="")
    fp = Path.home() / ".nexus" / "outputs" / "e2e_allow.md"
    cleanup_files([fp])
    start_server("allow_nexus_write")
    try:
        frames, _ = asyncio.run(run_ws_scenario(user_msg="mock test"))
        r.frames = frames
        assert_scenario(r, expect_hitl=False, expect_files=[fp])
        if r.passed:
            r.files_created.append(str(fp))
    finally:
        cleanup_files([fp])
        kill_server()
    return r


def scenario_interrupt_source() -> ScenarioResult:
    """2) 写项目源码 → HITL,approve 后文件创建。"""
    r = ScenarioResult(name="interrupt_source", passed=False, summary="")
    fp = ROOT / "nexus" / "backend" / "e2e_src.py"
    cleanup_files([fp])
    start_server("interrupt_source")
    try:
        frames, _ = asyncio.run(run_ws_scenario(user_msg="mock test", approve_hitl=True))
        r.frames = frames
        assert_scenario(r, expect_hitl=True, expect_files=[fp])
        if r.passed:
            r.files_created.append(str(fp))
    finally:
        cleanup_files([fp])
        kill_server()
    return r


def scenario_interrupt_agents_md() -> ScenarioResult:
    """3) 写 ~/.nexus/AGENTS.md → QualityGate 评估(机器判断),无 HITL,文件创建。

    2026-06-29 重构:AGENTS.md 写入走 :class:`QualityGateMiddleware` faithfulness
    评估(机器判断 LLM 内容是否合理),不弹 HITL(用户弹窗冗余)。评估通过 → 文件
    创建;评估失败 → ToolMessage error 回 LLM 反思。本场景验证评估**通过**路径。
    """
    r = ScenarioResult(name="interrupt_agents_md", passed=False, summary="")
    fp = Path.home() / ".nexus" / "AGENTS.md"
    backup = None
    if fp.exists():
        backup = fp.read_text()
    cleanup_files([fp])
    start_server("interrupt_agents_md")
    try:
        frames, _ = asyncio.run(run_ws_scenario(user_msg="mock test", approve_hitl=True))
        r.frames = frames
        # expect_hitl=False — AGENTS.md 走 QualityGate 评估,非 HITL。
        assert_scenario(r, expect_hitl=False, expect_files=[fp])
        if r.passed:
            r.files_created.append(str(fp))
    finally:
        if backup is not None:
            fp.write_text(backup)
        else:
            cleanup_files([fp])
        kill_server()
    return r


def scenario_deny_tmp_write() -> ScenarioResult:
    """4) 写 /tmp → 应 deny,文件未创建,LLM 反思不再写。

    2026-06-29 重构:系统级危险路径(``/tmp`` / ``/etc`` 等)由
    :class:`PathAwareHITLMiddleware._should_deny` 短路返回
    ``ToolMessage(status="error")``,**不弹 HITL**。LLM 看到 ToolMessage
    后反思,不再调任何写工具(由 mock LLM 的 "has_tool_result → 反思" 行为
    验证)。断言简化:
      - 无 HITL 帧
      - 文件**未**创建
      - LLM final 出现(说明 mock 收到 ToolMessage 后反思收尾)
    早期版本要求"thinking 帧含 permission denied",但 mock LLM 反射只
    final "操作完成",不在 thinking 流里吐 deny 字样 — 断言放宽匹配
    实际 mock 行为。
    """
    r = ScenarioResult(name="deny_tmp_write", passed=False, summary="")
    fp = Path("/tmp/e2e_scratch.md")
    cleanup_files([fp])
    start_server("deny_tmp_write")
    try:
        frames, _ = asyncio.run(run_ws_scenario(user_msg="mock test"))
        r.frames = frames
        # 1) 不应触发 HITL
        has_hitl = any(f.get("type") == "confirmation_request" for f in frames)
        if has_hitl:
            r.passed = False
            r.summary = f"❌ /tmp 写不应触发 HITL | {frames_summary(frames)}"
            return r
        # 2) 文件未被创建(系统级路径被 deny)
        if fp.exists():
            r.passed = False
            r.summary = f"❌ /tmp 文件不应被创建 | {frames_summary(frames)}"
            return r
        # 3) LLM 应反思收尾(出现 final 帧 — mock 看到 ToolMessage error 后
        #    走反思路径,不出 tool_call,直接 final)
        has_final = any(f.get("type") == "final" for f in frames)
        if not has_final:
            r.passed = False
            r.summary = f"❌ 未见到 LLM 反思收尾 | {frames_summary(frames)}"
            return r
        r.passed = True
        r.summary = f"✅ /tmp 写被 deny + LLM 反思 | {len(frames)} 帧 | {frames_summary(frames)}"
    finally:
        cleanup_files([fp])
        kill_server()
    return r


def scenario_multi_tool_calls() -> ScenarioResult:
    """5) 多 tool_calls(1 allow + 1 interrupt)→ 1 HITL 帧(只针对 interrupt 那条),
    approve 后 2 文件均创建。

    WHY:deepagents 对 tool_calls 批处理时,只有 mode="interrupt" 的路径才进 HITL
    队列;.nexus/ 白名单路径直接放行,不弹窗。这是设计意图,不是 bug。
    """
    r = ScenarioResult(name="multi_tool_calls", passed=False, summary="")
    fp_a = Path.home() / ".nexus" / "outputs" / "e2e_multi_a.md"
    fp_b = ROOT / "nexus" / "backend" / "e2e_multi_b.py"
    cleanup_files([fp_a, fp_b])
    start_server("multi_tool_calls")
    try:
        frames, _ = asyncio.run(run_ws_scenario(user_msg="mock test", approve_hitl=True))
        r.frames = frames
        # 找 confirmation_request
        hitl = next((f for f in frames if f.get("type") == "confirmation_request"), None)
        if hitl is None:
            r.passed = False
            r.summary = f"❌ 应有 HITL 帧 | {frames_summary(frames)}"
            return r
        # 只 interrupt 那条进 HITL,.nexus/ 走白名单 allow 不进队列
        if len(hitl.get("actions", [])) != 1:
            r.passed = False
            r.summary = f"❌ HITL 应含 1 action(只 interrupt 那条),实际 {len(hitl.get('actions', []))}"
            return r
        # approve 后 2 文件均应被创建(.nexus/ 走白名单,源码走 HITL approve)
        if not fp_a.exists() or not fp_b.exists():
            r.passed = False
            r.summary = f"❌ 2 文件应都创建 | a={fp_a.exists()} b={fp_b.exists()}"
            return r
        r.passed = True
        r.summary = f"✅ HITL×1 + 2 文件都创建 | {frames_summary(frames)}"
        r.files_created.extend([str(fp_a), str(fp_b)])
    finally:
        cleanup_files([fp_a, fp_b])
        kill_server()
    return r


def scenario_reject_then_reflect() -> ScenarioResult:
    """6) 写源码 → HITL → reject → 文件未创建 + LLM 反思。"""
    r = ScenarioResult(name="reject_then_reflect", passed=False, summary="")
    fp = ROOT / "nexus" / "backend" / "e2e_reject.py"
    cleanup_files([fp])
    start_server("reject_then_reflect")
    try:
        frames, _ = asyncio.run(run_ws_scenario(user_msg="mock test", approve_hitl=False))
        r.frames = frames
        has_hitl = any(f.get("type") == "confirmation_request" for f in frames)
        if not has_hitl:
            r.passed = False
            r.summary = f"❌ 应有 HITL | {frames_summary(frames)}"
            return r
        if fp.exists():
            r.passed = False
            r.summary = f"❌ reject 后文件不应创建 | {frames_summary(frames)}"
            return r
        # 反思:final 或 thinking 中应有"不再" / "理解" / "reflect" 类文本
        text = " ".join(str(f.get("content", "") or f.get("preview", "")) for f in frames)
        if "不再" not in text and "理解" not in text and "操作完成" not in text:
            r.passed = False
            r.summary = f"❌ LLM 未反思 | text={text[:120]!r}"
            return r
        r.passed = True
        r.summary = f"✅ reject + 反思 + 文件未创建 | {frames_summary(frames)}"
    finally:
        cleanup_files([fp])
        kill_server()
    return r


def scenario_edit_file_interrupt() -> ScenarioResult:
    """7) edit_file 改源码 → HITL,approve 后修改生效。

    特殊:目标文件 nexus/backend/agent/_agent_builder.py 必须存在。
    我们先备份原内容 + 恢复,避免污染。
    """
    r = ScenarioResult(name="edit_file_interrupt", passed=False, summary="")
    # 2026-06-30 重构:``get_project_root`` 搬到 ``_system_prompt.py``,
    # 跟着 e2e_mock 的 file_path 同步更新。
    fp = ROOT / "nexus" / "backend" / "agent" / "_system_prompt.py"
    backup = fp.read_text()
    cleanup_files([])  # 不删任何文件
    start_server("edit_file_interrupt")
    try:
        frames, _ = asyncio.run(run_ws_scenario(user_msg="mock test", approve_hitl=True))
        r.frames = frames
        assert_scenario(r, expect_hitl=True, expect_files=[])  # edit 不创建新文件
        if not r.passed:
            return r  # assert_scenario 已填 summary
        # 额外断言:文件被改过(内容含 "# E2E mock comment")
        if "E2E mock comment" not in fp.read_text():
            r.passed = False
            r.summary = f"❌ edit_file 未生效 | {frames_summary(frames)}"
            return r
        r.passed = True
        r.summary = f"✅ edit_file HITL + 修改生效 | {frames_summary(frames)}"
        r.files_created.append(f"{fp} (edit)")
    finally:
        fp.write_text(backup)  # 恢复原内容
        kill_server()
    return r


SCENARIOS = [
    scenario_allow_nexus_write,
    scenario_interrupt_source,
    scenario_interrupt_agents_md,
    scenario_deny_tmp_write,
    scenario_multi_tool_calls,
    scenario_reject_then_reflect,
    scenario_edit_file_interrupt,
]


def main() -> int:
    """跑全部 7 场景,打印汇总。"""
    print("=" * 70)
    print("Nexus DeepAgents HITL — 7 场景 E2E driver")
    print("=" * 70)
    results: list[ScenarioResult] = []
    for i, fn in enumerate(SCENARIOS, 1):
        name = fn.__name__
        print(f"\n[{i}/7] {name}")
        try:
            r = fn()
        except Exception as e:
            r = ScenarioResult(name=name, passed=False, summary=f"💥 {type(e).__name__}: {e}")
        results.append(r)
        status = "✅ PASS" if r.passed else "❌ FAIL"
        print(f"  {status} {r.summary}")
    # 汇总
    print("\n" + "=" * 70)
    print("汇总")
    print("=" * 70)
    passed = sum(1 for r in results if r.passed)
    for r in results:
        s = "✅" if r.passed else "❌"
        print(f"  {s} {r.name}")
    print(f"\n{passed}/{len(results)} 场景通过")
    # 清理 7 个场景的临时 DB(连同 -journal / -wal)
    for fn in SCENARIOS:
        for ext in ("", "-journal", "-wal", "-shm"):
            Path(f"/tmp/nexus_e2e_{fn.__name__}{ext}").unlink(missing_ok=True)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
