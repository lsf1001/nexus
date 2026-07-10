"""Test the date_utils MCP server tools.

WHY: The original bug was an LLM hallucinating that Saturday was Friday.
With this server, the LLM has a tool that returns the real weekday — no
arithmetic, no hallucination possible.

设计原则:
- 纯函数:无 I/O、无日志、无全局状态
- 硬编码 Asia/Shanghai:不读 TZ 环境变量,这就是项目事实源
- 无效输入立刻 ValueError,绝不静默
- Server construction 单独测试,这里只验工具逻辑
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from nexus.backend.mcp.date_utils import next_n_days, today, weekday_of


class TestToday:
    def test_today_returns_shanghai_date(self):
        result = today()
        # Should be a YYYY-MM-DD string matching Asia/Shanghai today
        shanghai_now = datetime.now(ZoneInfo("Asia/Shanghai"))
        assert result == shanghai_now.date().isoformat()

    def test_today_is_deterministic(self):
        # Two calls within the same day return same string
        assert today() == today()

    def test_today_tz_argument_is_ignored_or_validated(self):
        # Per design, the server is hardcoded to Asia/Shanghai.
        # Optionally: accept tz argument but always normalize to Shanghai.
        try:
            result = today(tz="America/New_York")
            # If accepted, must still be Shanghai date
            shanghai_now = datetime.now(ZoneInfo("Asia/Shanghai"))
            assert result == shanghai_now.date().isoformat()
        except (TypeError, ValueError):
            pass  # OK if argument is rejected


class TestWeekdayOf:
    def test_known_friday(self):
        # 2026-07-10 was a Friday
        assert weekday_of("2026-07-10") == "星期五"

    def test_known_saturday(self):
        # 2026-07-11 was a Saturday
        assert weekday_of("2026-07-11") == "星期六"

    def test_leap_year_handling(self):
        # 2024-02-29 was a Thursday
        assert weekday_of("2024-02-29") == "星期四"

    def test_invalid_date_raises(self):
        with pytest.raises(ValueError):
            weekday_of("2026-13-99")
        with pytest.raises(ValueError):
            weekday_of("not a date")

    def test_returns_chinese_full_name(self):
        # All 7 days must map correctly to Chinese
        # 2026-07-06 = Monday; 2026-07-12 = Sunday
        assert weekday_of("2026-07-06") == "星期一"
        assert weekday_of("2026-07-07") == "星期二"
        assert weekday_of("2026-07-08") == "星期三"
        assert weekday_of("2026-07-09") == "星期四"
        assert weekday_of("2026-07-10") == "星期五"
        assert weekday_of("2026-07-11") == "星期六"
        assert weekday_of("2026-07-12") == "星期日"


class TestNextNDays:
    def test_next_one_day(self):
        result = next_n_days(start_date="2026-07-10", n=1)
        assert len(result) == 1
        assert result[0]["date"] == "2026-07-11"
        assert result[0]["weekday"] == "星期六"

    def test_next_seven_days(self):
        result = next_n_days(start_date="2026-07-10", n=7)
        assert len(result) == 7
        assert result[0]["date"] == "2026-07-11"
        assert result[6]["date"] == "2026-07-17"

    def test_n_zero_or_negative_raises(self):
        with pytest.raises(ValueError):
            next_n_days(start_date="2026-07-10", n=0)
        with pytest.raises(ValueError):
            next_n_days(start_date="2026-07-10", n=-1)

    def test_crosses_year_boundary(self):
        result = next_n_days(start_date="2026-12-31", n=2)
        assert result[0]["date"] == "2027-01-01"
        assert result[1]["date"] == "2027-01-02"

    def test_crosses_leap_day(self):
        result = next_n_days(start_date="2024-02-28", n=3)
        assert result[0]["date"] == "2024-02-29"  # leap year
        assert result[1]["date"] == "2024-03-01"
        assert result[2]["date"] == "2024-03-02"
