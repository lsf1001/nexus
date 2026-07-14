"""Shell 工具的命令审计日志(JSONL + 0600 权限 + 大小 rotate)。

WHY
--
``shell_run`` 是 Nexus 第一条"任意执行命令"的产品能力。即便有 HITL 拦截 +
沙箱黑名单,审计日志仍然必要:出事后用户能查"AI 跑了什么 / 我批准了什么 /
结果是什么"。这是 MEMORY.md ``feedback-no-wrapping-stdlib`` 反例的合法情况
—— 单文件工具,职责清晰,无外部依赖,不写脚本/包一层。

格式:JSONL(每行一条 JSON 对象),理由:
  - 追加写 + 进程间无需锁
  - 任何文本工具都能打开看
  - 后续切 logstash / fluentd 无格式迁移成本

文件:``~/.nexus/logs/shell_executions.log``,权限 0600(只 owner 可读写)。
大小 rotate 阈值 10MB —— 超过就 rename 成 ``shell_executions.log.1``,
新文件从头写。简单 rotate,够用户自查即可,不接 ELK。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

# === 配置常量 ===
_USER_HOME = Path.home()
AUDIT_LOG_DIR: Path = _USER_HOME / ".nexus" / "logs"
AUDIT_LOG_FILE: Path = AUDIT_LOG_DIR / "shell_executions.log"
AUDIT_LOG_MAX_BYTES: int = 10 * 1024 * 1024  # 10MB
_STDOUT_PREVIEW_CHARS: int = 500
_STDERR_PREVIEW_CHARS: int = 500

UserDecision = Literal["approve", "reject", "auto_deny"]


def _ensure_audit_file() -> Path:
    """确保审计日志文件存在 + 权限 0600。"""
    AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    if not AUDIT_LOG_FILE.exists():
        AUDIT_LOG_FILE.touch()
        os.chmod(AUDIT_LOG_FILE, 0o600)
    return AUDIT_LOG_FILE


def _rotate_if_needed() -> None:
    """文件超过 ``AUDIT_LOG_MAX_BYTES`` 时 rotate 成 .1(覆盖旧 .1)。

    WHY 简单 rotate:用户自查场景只需"最近 N 次 rotate";无限增长会撑爆
    磁盘(``~/.nexus/`` 可能在小 SSD 上)。保留最近 1 个备份足够。
    """
    if not AUDIT_LOG_FILE.exists():
        return
    try:
        size = AUDIT_LOG_FILE.stat().st_size
    except OSError as exc:  # 文件被其他进程删除等竞态
        logger.warning("audit log stat 失败,跳过 rotate: %s", exc)
        return
    if size < AUDIT_LOG_MAX_BYTES:
        return

    backup = AUDIT_LOG_FILE.with_suffix(AUDIT_LOG_FILE.suffix + ".1")
    try:
        if backup.exists():
            backup.unlink()
        AUDIT_LOG_FILE.rename(backup)
        AUDIT_LOG_FILE.touch()
        os.chmod(AUDIT_LOG_FILE, 0o600)
        logger.info("audit log rotated: %s -> %s", AUDIT_LOG_FILE, backup)
    except OSError as exc:
        logger.warning("audit log rotate 失败: %s", exc)


def append_log(
    *,
    command: str,
    cwd: str,
    exit_code: int | None,
    stdout_snippet: str = "",
    stderr_snippet: str = "",
    user_decision: UserDecision,
    duration_ms: int | None = None,
    risk_label: str | None = None,
) -> None:
    """追加一条 shell 执行审计记录。

    Args:
        command: 完整 shell 命令字符串。
        cwd: resolve 后的 cwd 绝对路径。
        exit_code: 进程退出码;被 deny / reject 时传 ``None``。
        stdout_snippet: stdout 前 ``_STDOUT_PREVIEW_CHARS`` 字符;太长截断。
        stderr_snippet: stderr 前 ``_STDERR_PREVIEW_CHARS`` 字符。
        user_decision: ``"approve"``(用户批准后跑) / ``"reject"``(用户拒绝,未跑)
            / ``"auto_deny"``(沙箱自动拒绝,未弹 HITL)。
        duration_ms: 实际执行毫秒数;未跑传 ``None``。
        risk_label: ``validate_command`` 命中的危险模式 label(如果有);
            否则 ``None``。
    """
    record = {
        "ts": datetime.now(tz=UTC).isoformat(),
        "command": command,
        "cwd": cwd,
        "exit_code": exit_code,
        "stdout_preview": stdout_snippet[:_STDOUT_PREVIEW_CHARS],
        "stderr_preview": stderr_snippet[:_STDERR_PREVIEW_CHARS],
        "decision": user_decision,
        "duration_ms": duration_ms,
        "risk_label": risk_label,
    }

    try:
        _rotate_if_needed()
        path = _ensure_audit_file()
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        # 审计写失败**不**应阻断 shell_run 主流程 —— 记录到 logger,用户
        # 至少能从 ``~/.nexus/logs/nexus.log`` 看到"审计失败"。
        logger.error("shell audit log 写入失败: %s", exc, exc_info=True)


__all__ = ["AUDIT_LOG_FILE", "append_log"]
