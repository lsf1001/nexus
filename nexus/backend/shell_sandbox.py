"""Shell 工具的沙箱守卫:危险命令黑名单 + cwd 白名单 + 超时硬上限。

WHY 独立模块(2026-07-14)
------------------------
之前 Nexus LLM 工具集是 100% 只读(get_current_date / search / introspect),
用户/产品都没意识到这层约束;加 ``shell_run`` 后 LLM 第一次拿到
``subprocess.run`` 入口,等价于给 LLM 一把"运行任意命令"的钥匙,风险骤升。
本模块把"什么命令不许跑 / 什么 cwd 不许去 / 超时多久强制杀"集中成**纯函数**,
便于:

  1. ``shell_run`` 工具调 ``validate_command`` 提前 deny,无需走 HITL(避免
     "rm -rf /" 这种命令也弹卡,体验差且浪费用户注意力)。
  2. ``tests/test_shell_sandbox.py`` 单测覆盖全部黑名单模式 + 边界。
  3. 未来如果放宽策略(比如用户主动加白名单),只改这里,不动工具/WS/前端。

不依赖 langchain / deepagents / langgraph —— 是**最底层的规则**,必须
可以在不引入 agent 的纯单元测试里完整覆盖。
"""

from __future__ import annotations

import re
from pathlib import Path

# === 路径白名单:shell_run 的 cwd 只能落在 ~/.nexus/ 下 ===
# WHY:产品定位是 OpenClaw 个人助理(MEMORY.md `nexus-product-positioning-openclaw`),
# 用户数据唯一归宿就是 ``~/.nexus/``(models.json / nexus.db / logs / outputs 等)。
# 任意 cwd 偏离这条线 → 拒,无需 HITL。
ALLOWED_CWD_ROOTS: tuple[str, ...] = (str((Path.home() / ".nexus").resolve()) + "/",)

# === 超时硬上限 ===
# WHY:用户不指定 timeout → 默认 30s(覆盖典型 grep / pip install / curl 等);
# 最长 300s(5 分钟)避免 ``while true`` / 大型 npm install 永久挂起。
# LLM 不能通过传更长 timeout 绕过 —— clamp 是最后一道闸。
DEFAULT_TIMEOUT_SECONDS: int = 30
MAX_TIMEOUT_SECONDS: int = 300

# === 危险命令黑名单 ===
# 原则:宁可误杀一个真合法的命令(用户改一下重跑),不可漏掉一个真危险命令。
# 每个 pattern 必须 + re.IGNORECASE(rm -RF / 也要拒)。
#
# 覆盖模式(每个一行注释写清楚命中什么):
_DANGEROUS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # rm -rf <any> / rm -fr <any> / rm -r <any> / rm --recursive <any>:
    # 路径可以是 / (rm -rf /) / 文件夹 / 通配,统一拦。
    # 注意:rm <file>(不带 -r) 是合法操作(删一个文件),**不**拦。
    (
        "recursive_force_delete",
        re.compile(
            r"\brm\s+(?:-[a-zA-Z]*[fr][a-zA-Z]*|--recursive\b)[^|;&\n]*",
            re.IGNORECASE,
        ),
    ),
    # sudo / su / doas —— 提权运行一律拒
    ("privilege_escalation_sudo", re.compile(r"\bsudo\b", re.IGNORECASE)),
    ("privilege_escalation_su", re.compile(r"\bsu\s+-[a-zA-Z]*", re.IGNORECASE)),
    ("privilege_escalation_doas", re.compile(r"\bdoas\b", re.IGNORECASE)),
    # shutdown / reboot / halt / poweroff —— 系统关机类
    ("system_power", re.compile(r"\b(shutdown|reboot|halt|poweroff)\b", re.IGNORECASE)),
    # | sh / | bash / | zsh —— 任何管道进 shell 的下载即执行(覆盖 curl|wget|nc)
    ("pipe_to_shell", re.compile(r"\|\s*(ba|z)?sh\b", re.IGNORECASE)),
    # > /dev/sda / > /dev/nvme / > /dev/disk0 —— 覆盖磁盘
    ("disk_overwrite", re.compile(r">\s*/dev/(sd[a-z]+|hd[a-z]+|nvme[0-9]+|disk[0-9]+)", re.IGNORECASE)),
    # mkfs / mkfs.ext4 —— 格式化
    ("filesystem_format", re.compile(r"\bmkfs(\.[a-z0-9]+)?\b", re.IGNORECASE)),
    # dd if= —— 经典磁盘克隆 / 覆盖
    ("dd_image", re.compile(r"\bdd\s+[^|;&]*\bif=", re.IGNORECASE)),
    # fork bomb: :(){ :|:& };:
    ("fork_bomb", re.compile(r":\s*\(\s*\)\s*\{[^}]*\|[^}]*&\s*\}\s*;:")),
    # chmod 777 / chown -R —— 大范围改权限
    ("permissive_chmod", re.compile(r"\bchmod\s+[0-7]?7[0-7][0-7]\b", re.IGNORECASE)),
    ("recursive_chown", re.compile(r"\bchown\s+-[a-zA-Z]*R\b", re.IGNORECASE)),
)


def validate_command(command: str) -> tuple[bool, str]:
    """检查命令字符串是否触发危险模式黑名单。

    Args:
        command: 完整 shell 命令字符串(由 LLM 传入)。

    Returns:
        ``(True, "")`` 命令合法;``(False, reason)`` 命令触发黑名单,``reason``
        是面向 LLM + 用户的可读解释(包含触发的模式名 + 命中片段)。
    """
    if not command or not command.strip():
        return False, "命令为空"

    for label, pattern in _DANGEROUS_PATTERNS:
        match = pattern.search(command)
        if match is not None:
            return False, f"触发危险模式 ``{label}``: ``{match.group(0)}``"

    return True, ""


def validate_cwd(cwd: str | None) -> tuple[bool, str]:
    """检查 cwd 是否在 ``~/.nexus/`` 白名单下。

    Args:
        cwd: LLM 指定的 cwd;``None`` 表示"使用进程默认 cwd",**拒绝**
            (进程默认 cwd 不可控,可能落到 ``/`` 或项目根)。

    Returns:
        ``(True, str(resolved))`` 合法;``(False, reason)`` 不合法。
    """
    if cwd is None or not str(cwd).strip():
        return False, "未指定 cwd(必须显式指定,默认 cwd 不可控)"

    try:
        resolved = str(Path(cwd).expanduser().resolve())
    except (OSError, RuntimeError) as exc:
        return False, f"cwd 解析失败: ``{exc}``"

    if not any(resolved.startswith(prefix) for prefix in ALLOWED_CWD_ROOTS):
        # 给一个"该去哪里"的提示,LLM 可据此改写
        return False, (f"cwd ``{resolved}`` 不在白名单 ``~/.nexus/`` 下。请改用 ``~/.nexus/outputs/`` 之类的目录。")

    return True, resolved


def validate_timeout(timeout: int | None) -> int:
    """把 LLM 传入的 timeout clamp 到合法区间。

    Args:
        timeout: LLM 指定的超时秒数;``None`` 走 ``DEFAULT_TIMEOUT_SECONDS``。

    Returns:
        clamp 后的整数秒数,落在 ``[1, MAX_TIMEOUT_SECONDS]``。
    """
    if timeout is None:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        value = int(timeout)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS
    if value < 1:
        return 1
    if value > MAX_TIMEOUT_SECONDS:
        return MAX_TIMEOUT_SECONDS
    return value


def classify_dangerous_command(command: str) -> str | None:
    """``validate_command`` 的辅助:只返回命中的模式 label,无副作用。

    WHY 辅助:测试断言用得上"具体哪个模式命中";生产路径走 ``validate_command``
    拿到完整 reason 即可。
    """
    if not command:
        return None
    for label, pattern in _DANGEROUS_PATTERNS:
        if pattern.search(command) is not None:
            return label
    return None


__all__ = [
    "ALLOWED_CWD_ROOTS",
    "DEFAULT_TIMEOUT_SECONDS",
    "MAX_TIMEOUT_SECONDS",
    "classify_dangerous_command",
    "validate_command",
    "validate_cwd",
    "validate_timeout",
]
