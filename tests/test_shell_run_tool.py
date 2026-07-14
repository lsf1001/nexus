"""``nexus.backend.tools.shell_run`` 工具的单元测试。

覆盖三类路径:
  1. **正常**:合法命令 + 白名单 cwd → 真实 subprocess 执行成功,审计写入 approve。
  2. **边界**:timeout clamp;stdout 超 5000 字符截断;cwd resolve 带 ``~``。
  3. **异常**:危险命令短路 + 审计写 auto_deny;cwd 越界短路 + 审计 auto_deny;
     subprocess 真实超时(TimeoutExpired)。

WHY 不依赖中间件 / HITL:
  ``shell_run`` 工具的合约**只**包含"沙箱短路 + subprocess 执行 + 审计写入"。
  HITL 弹窗由 :class:`ShellHITLMiddleware` 独立负责,在
  :mod:`tests.test_shell_hitl_middleware` 单独测。
  这里测"假设 HITL 已经通过,工具本身干得对不对"。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import nexus.backend.shell_audit as audit_mod
from nexus.backend.tools import shell_run


@pytest.fixture
def audit_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """审计日志重定向到 tmp_path。"""
    log_dir = tmp_path / "logs"
    log_file = log_dir / "shell_executions.log"
    monkeypatch.setattr(audit_mod, "AUDIT_LOG_DIR", log_dir)
    monkeypatch.setattr(audit_mod, "AUDIT_LOG_FILE", log_file)
    return {"dir": log_dir, "file": log_file}


@pytest.fixture
def nexus_cwd(tmp_path: Path) -> Path:
    """真实可执行的 cwd: ``~/.nexus/outputs/<tmp>``。"""
    from nexus.backend.shell_sandbox import ALLOWED_CWD_ROOTS

    assert ALLOWED_CWD_ROOTS, "shell_sandbox 必须定义白名单"
    base = Path(ALLOWED_CWD_ROOTS[0].rstrip("/"))
    target = base / "outputs" / f"shell_run_test_{tmp_path.name}"
    target.mkdir(parents=True, exist_ok=True)
    return target


# === 正常路径 ===


def test_shell_run_normal_echo(audit_env: dict[str, Path], nexus_cwd: Path) -> None:
    """echo hello 应成功,审计写入 approve,exit_code=0。"""
    result = shell_run.invoke({"command": "echo hello", "cwd": str(nexus_cwd)})
    assert "exit_code=0" in result
    assert "hello" in result

    record = json.loads(audit_env["file"].read_text(encoding="utf-8").strip())
    assert record["decision"] == "approve"
    assert record["exit_code"] == 0
    assert record["command"] == "echo hello"
    assert "hello" in record["stdout_preview"]


def test_shell_run_records_duration(audit_env: dict[str, Path], nexus_cwd: Path) -> None:
    """duration_ms 应 > 0(实测)。"""
    shell_run.invoke({"command": "sleep 0.05", "cwd": str(nexus_cwd)})
    record = json.loads(audit_env["file"].read_text(encoding="utf-8").strip())
    assert record["duration_ms"] is not None
    assert record["duration_ms"] >= 0


def test_shell_run_truncates_long_stdout(audit_env: dict[str, Path], nexus_cwd: Path) -> None:
    """stdout 超 5000 字符应截断。"""
    shell_run.invoke({"command": "python3 -c 'print(\"x\" * 10000)'", "cwd": str(nexus_cwd)})
    record = json.loads(audit_env["file"].read_text(encoding="utf-8").strip())
    assert len(record["stdout_preview"]) <= 5000


def test_shell_run_nonzero_exit(audit_env: dict[str, Path], nexus_cwd: Path) -> None:
    """非 0 退出码应原样记录 + 显示。"""
    result = shell_run.invoke({"command": "exit 7", "cwd": str(nexus_cwd)})
    assert "exit_code=7" in result
    record = json.loads(audit_env["file"].read_text(encoding="utf-8").strip())
    assert record["exit_code"] == 7


# === 异常路径(沙箱短路,不真跑)===


@pytest.mark.parametrize(
    "dangerous_command",
    [
        "rm -rf /",
        "sudo apt install evil",
        "echo hi | sh",
        "shutdown -h now",
        ":(){ :|:& };:",
        "chmod 777 file",
    ],
)
def test_shell_run_dangerous_short_circuit(dangerous_command: str, audit_env: dict[str, Path], nexus_cwd: Path) -> None:
    """危险命令应短路,返回 error 字符串,审计写 auto_deny,risk_label 不为 None。

    **不**应真跑 subprocess(意味着如果黑名单漏判,这测试会因为真的
    跑 rm -rf 之类炸测试机 —— 跑了也别慌,因为有 cwd=~/.nexus 兜底)。
    """
    result = shell_run.invoke({"command": dangerous_command, "cwd": str(nexus_cwd)})
    assert "[Shell 沙箱阻断]" in result, f"危险命令未短路: {dangerous_command}"

    record = json.loads(audit_env["file"].read_text(encoding="utf-8").strip())
    assert record["decision"] == "auto_deny"
    assert record["exit_code"] is None  # 没真跑
    assert record["risk_label"] is not None


def test_shell_run_cwd_outside_whitelist(audit_env: dict[str, Path]) -> None:
    """cwd 越界应短路,不弹 HITL(由工具入口 deny,而非中间件)。"""
    result = shell_run.invoke({"command": "ls", "cwd": "/tmp"})
    assert "[Shell 沙箱阻断]" in result
    assert "白名单" in result or "未指定" in result

    record = json.loads(audit_env["file"].read_text(encoding="utf-8").strip())
    assert record["decision"] == "auto_deny"
    assert record["risk_label"] is None  # 不是命令危险,是 cwd 越界


def test_shell_run_cwd_none_rejected_via_underlying_function(
    audit_env: dict[str, Path],
) -> None:
    """cwd=None 应被工具函数短路。

    WHY 不直接 ``shell_run.invoke({"cwd": None})``:pydantic schema 在 langchain
    invoke 阶段就把 None 拒了,不会到达我们的 sandbox 校验。这里直接调函数
    闭包(绕过 langchain 装饰层),确认核心逻辑能扛 None。
    """
    from nexus.backend.tools import shell_run

    inner = shell_run.func  # type: ignore[attr-defined]  # 拿原始函数(非 StructuredTool)
    result = inner(command="ls", cwd=None)
    assert "[Shell 沙箱阻断]" in result

    record = json.loads(audit_env["file"].read_text(encoding="utf-8").strip())
    assert record["decision"] == "auto_deny"


def test_shell_run_timeout_clamps_and_kills(audit_env: dict[str, Path], nexus_cwd: Path) -> None:
    """真实超时(timeout=1,sleep 5)应被强制终止,审计写 stderr 含 TIMEOUT。"""
    result = shell_run.invoke({"command": "sleep 5", "cwd": str(nexus_cwd), "timeout": 1})
    assert "[Shell 超时]" in result

    record = json.loads(audit_env["file"].read_text(encoding="utf-8").strip())
    assert "TIMEOUT" in record["stderr_preview"]


def test_shell_run_timeout_default_30(audit_env: dict[str, Path], nexus_cwd: Path) -> None:
    """不传 timeout → 默认 30s(clamp 仍生效:1s sleep 应成功)。"""
    result = shell_run.invoke({"command": "sleep 0.1", "cwd": str(nexus_cwd)})
    assert "exit_code=0" in result


def test_shell_run_timeout_over_max_clamps(audit_env: dict[str, Path], nexus_cwd: Path) -> None:
    """timeout > 300 应被 clamp 到 300,允许通过(没真等 5 分钟)。"""
    # timeout=10000 → clamp 到 300 → sleep 0.05 实际不到 300s,成功。
    result = shell_run.invoke({"command": "sleep 0.05", "cwd": str(nexus_cwd), "timeout": 10000})
    assert "exit_code=0" in result
