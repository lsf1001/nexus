"""date_utils MCP server — 确定性日期/星期工具。

设计目标:
- 替代 LLM 的 mod 7 阴历推测,直接给真实今日 + 任意日期星期几
- 时区硬编码 Asia/Shanghai(项目事实源)
- 错误边界:无效日期立刻 ValueError,绝不静默

工具:
- today() -> str (YYYY-MM-DD,Asia/Shanghai)
- weekday_of(date_str: str) -> str (星期一/二/三/四/五/六/日)
- next_n_days(start_date: str, n: int) -> list[dict] (含 date 和 weekday 字段)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")

# Python: Monday=0 ... Sunday=6 → 中文
_WEEKDAY_ZH = (
    "星期一",  # 0
    "星期二",  # 1
    "星期三",  # 2
    "星期四",  # 3
    "星期五",  # 4
    "星期六",  # 5
    "星期日",  # 6
)


def today(tz: str | None = None) -> str:
    """返回 Asia/Shanghai 当前日期 YYYY-MM-DD。

    设计:tz 参数为向后兼容占位;始终以 Asia/Shanghai 为权威时区。
    """
    return datetime.now(SHANGHAI_TZ).date().isoformat()


def weekday_of(date_str: str) -> str:
    """返回中文星期(星期一...星期日)。

    Args:
        date_str: YYYY-MM-DD 格式日期字符串

    Raises:
        ValueError: 无效日期格式
    """
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError as e:
        raise ValueError(f"无效日期格式 {date_str!r},需要 YYYY-MM-DD") from e

    return _WEEKDAY_ZH[d.weekday()]


def next_n_days(
    start_date: str,
    n: int,
) -> list[dict[str, str]]:
    """从 start_date 开始,返回接下来 n 天的 [{date, weekday}, ...]。

    Args:
        start_date: YYYY-MM-DD 起始日(不含)
        n: 天数,必须 >= 1

    Raises:
        ValueError: n < 1 或 start_date 无效
    """
    if n < 1:
        raise ValueError(f"n 必须 >= 1,收到 {n}")
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
    except ValueError as e:
        raise ValueError(f"无效日期格式 {start_date!r},需要 YYYY-MM-DD") from e

    return [
        {
            "date": (start + timedelta(days=i + 1)).isoformat(),
            "weekday": _WEEKDAY_ZH[(start + timedelta(days=i + 1)).weekday()],
        }
        for i in range(n)
    ]
