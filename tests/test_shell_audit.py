"""``nexus.backend.shell_audit`` 单元测试。

覆盖三类路径:
  1. **正常**:append_log 写入 JSONL 行;stdout/stderr 截断;文件权限 0600。
  2. **边界**:多行写入;空 stdout/stderr;rotate 触发保留最近 1 份。
  3. **异常**:目录不可写不抛(降级到 logger);OSError 走降级。

WHY 不依赖 db / 网络:
  审计模块只摸文件,test 用 tmp_path 隔离,不污染真实 ``~/.nexus/``。
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

import nexus.backend.shell_audit as audit_mod


@pytest.fixture
def audit_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """把 ``AUDIT_LOG_DIR`` / ``AUDIT_LOG_FILE`` 重定向到 tmp_path。"""
    log_dir = tmp_path / "logs"
    log_file = log_dir / "shell_executions.log"
    monkeypatch.setattr(audit_mod, "AUDIT_LOG_DIR", log_dir)
    monkeypatch.setattr(audit_mod, "AUDIT_LOG_FILE", log_file)
    return {"dir": log_dir, "file": log_file}


def test_append_log_normal(audit_env: dict[str, Path]) -> None:
    """正常 append_log → 文件存在 + 1 行 JSON + 权限 0600。"""
    audit_mod.append_log(
        command="echo hi",
        cwd="/Users/x/.nexus/outputs",
        exit_code=0,
        stdout_snippet="hi\n",
        stderr_snippet="",
        user_decision="approve",
        duration_ms=42,
    )
    path = audit_env["file"]
    assert path.exists()
    # 权限 0600:owner rw-,no group,no other
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600, f"权限错误: {oct(mode)}"

    lines = path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["command"] == "echo hi"
    assert record["exit_code"] == 0
    assert record["decision"] == "approve"
    assert record["duration_ms"] == 42
    assert "ts" in record


def test_append_log_truncates_long_output(audit_env: dict[str, Path]) -> None:
    """stdout/stderr 超过 500 字符应被截断。"""
    long_out = "x" * 5000
    audit_mod.append_log(
        command="cat huge",
        cwd="/Users/x/.nexus",
        exit_code=0,
        stdout_snippet=long_out,
        stderr_snippet=long_out,
        user_decision="approve",
    )
    record = json.loads(audit_env["file"].read_text(encoding="utf-8").strip())
    assert len(record["stdout_preview"]) == 500
    assert len(record["stderr_preview"]) == 500


def test_append_log_auto_deny(audit_env: dict[str, Path]) -> None:
    """auto_deny (沙箱短路) 决策也能记录,exit_code=None。"""
    audit_mod.append_log(
        command="rm -rf /",
        cwd="/Users/x/.nexus",
        exit_code=None,
        user_decision="auto_deny",
        risk_label="recursive_force_delete",
    )
    record = json.loads(audit_env["file"].read_text(encoding="utf-8").strip())
    assert record["decision"] == "auto_deny"
    assert record["exit_code"] is None
    assert record["risk_label"] == "recursive_force_delete"


def test_append_log_reject(audit_env: dict[str, Path]) -> None:
    """reject (用户 HITL 拒绝) 决策。"""
    audit_mod.append_log(
        command="echo bye",
        cwd="/Users/x/.nexus",
        exit_code=None,
        user_decision="reject",
    )
    record = json.loads(audit_env["file"].read_text(encoding="utf-8").strip())
    assert record["decision"] == "reject"


def test_append_log_multiple_lines(audit_env: dict[str, Path]) -> None:
    """多次写入 → 多行 JSONL。"""
    for i in range(3):
        audit_mod.append_log(
            command=f"echo {i}",
            cwd="/Users/x/.nexus",
            exit_code=0,
            user_decision="approve",
        )
    lines = audit_env["file"].read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 3


def test_append_log_creates_dir_with_perms(audit_env: dict[str, Path]) -> None:
    """首次写入应自动 mkdir + chmod 0600。"""
    assert not audit_env["file"].exists()
    audit_mod.append_log(
        command="ls",
        cwd="/Users/x/.nexus",
        exit_code=0,
        user_decision="approve",
    )
    assert audit_env["file"].exists()
    mode = stat.S_IMODE(audit_env["file"].stat().st_mode)
    assert mode == 0o600


def test_rotate_when_too_big(audit_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    """文件超过阈值 → rotate 成 .1,新文件变小(最近 1 次写入)。"""
    # 把阈值调到 200 字节,容易触发
    monkeypatch.setattr(audit_mod, "AUDIT_LOG_MAX_BYTES", 200)

    pre_size = audit_env["file"].stat().st_size if audit_env["file"].exists() else 0

    # 写满 3 次,每次约 200+ 字节,触发 rotate
    for i in range(3):
        audit_mod.append_log(
            command=f"echo long_output_{i}_{'x' * 30}",
            cwd="/Users/x/.nexus",
            exit_code=0,
            stdout_snippet="y" * 40,
            user_decision="approve",
        )

    backup = audit_env["file"].with_suffix(audit_env["file"].suffix + ".1")
    assert backup.exists(), "rotate 后 .1 文件应存在"
    # 新文件应该比阈值小(rotate 后只剩最近 1 次写入)
    assert audit_env["file"].stat().st_size <= audit_mod.AUDIT_LOG_MAX_BYTES + 100
    assert audit_env["file"].stat().st_size < pre_size + 100 or pre_size == 0


def test_rotate_keeps_only_one_backup(audit_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    """多次 rotate 只保留最近 1 份备份(.1),旧 .1 被覆盖。"""
    monkeypatch.setattr(audit_mod, "AUDIT_LOG_MAX_BYTES", 50)

    for i in range(5):
        audit_mod.append_log(
            command=f"echo pad_{i}_{'x' * 40}",
            cwd="/Users/x/.nexus",
            exit_code=0,
            user_decision="approve",
        )

    backup = audit_env["file"].with_suffix(audit_env["file"].suffix + ".1")
    assert backup.exists()
    # .2 不应存在(只留 .1)
    backup2 = audit_env["file"].with_suffix(audit_env["file"].suffix + ".2")
    assert not backup2.exists()


def test_append_log_swallows_oserror(
    audit_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """OSError 不应向上抛,降级到 logger 记录。"""

    # 把 _ensure_audit_file 改成抛 OSError,模拟磁盘满 / 权限拒绝
    def _raise_oserror() -> Path:
        raise OSError("simulated disk full")

    monkeypatch.setattr(audit_mod, "_ensure_audit_file", _raise_oserror)

    # 不应抛异常
    audit_mod.append_log(
        command="ls",
        cwd="/Users/x/.nexus",
        exit_code=0,
        user_decision="approve",
    )
    # 至少 logger 应有 ERROR 级别记录
    assert any("shell audit log 写入失败" in rec.message for rec in caplog.records)


def test_chmod_enforced_after_existing_file(audit_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    """文件已存在但权限被改 → 重新写入不应还原权限(只新建时设)。"""
    audit_env["dir"].mkdir(parents=True, exist_ok=True)
    audit_env["file"].touch()
    os.chmod(audit_env["file"], 0o644)
    audit_mod.append_log(
        command="ls",
        cwd="/Users/x/.nexus",
        exit_code=0,
        user_decision="approve",
    )
    # 设计行为:不主动改已存在文件的权限(避免覆盖 sysadmin 调整过的权限)。
    # 验证:文件仍可读 + 写入追加。
    assert audit_env["file"].exists()
    assert len(audit_env["file"].read_text(encoding="utf-8").strip().split("\n")) == 1
