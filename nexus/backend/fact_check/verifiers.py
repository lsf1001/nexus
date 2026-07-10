"""确定性事实校验器。

每个校验器接收一个 FactClaim，返回 VerificationResult。
校验器都是纯函数 —— 不调用 LLM，不发起网络请求（汇率校验器除外，
它走带缓存的 API）。

验证策略:
- DateWeekdayVerifier: 用 Python datetime 核对日期与星期是否一致
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

from nexus.backend.fact_check.extractors import FactClaim


@dataclass(frozen=True)
class VerificationResult:
    """单条事实声明的校验结果。"""

    claim: FactClaim
    verdict: Literal["ok", "conflict", "error", "skipped"]
    claimed_weekday_zh: str | None = None
    actual_weekday_zh: str | None = None
    expected_value: float | None = None
    actual_value: float | None = None
    error_message: str | None = None


class DateWeekdayVerifier:
    """核对"日期 + 星期"是否一致。

    支持中文格式（"2026年7月11日 星期六"）和 ISO 格式
    （"2026-07-11 Saturday"）。无法解析或日期非法时返回 verdict="error"。
    """

    _RE_ZH_DATE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")
    _RE_ISO_DATE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")

    _WEEKDAY_ZH = (
        "星期一",
        "星期二",
        "星期三",
        "星期四",
        "星期五",
        "星期六",
        "星期日",
    )

    def verify(self, claim: FactClaim) -> VerificationResult:
        """校验一条 date_weekday 声明;非该类型则跳过。"""
        if claim.kind != "date_weekday":
            return VerificationResult(claim=claim, verdict="skipped")

        assert claim.date_str and claim.claimed_weekday_zh
        m_zh = self._RE_ZH_DATE.match(claim.date_str)
        m_iso = self._RE_ISO_DATE.match(claim.date_str)
        if m_zh:
            y, mo, d = int(m_zh[1]), int(m_zh[2]), int(m_zh[3])
        elif m_iso:
            y, mo, d = int(m_iso[1]), int(m_iso[2]), int(m_iso[3])
        else:
            return VerificationResult(
                claim=claim,
                verdict="error",
                error_message=f"Unparseable date: {claim.date_str}",
            )

        try:
            dt = date(y, mo, d)
        except ValueError as e:
            return VerificationResult(
                claim=claim,
                verdict="error",
                error_message=str(e),
            )

        actual_zh = self._WEEKDAY_ZH[dt.weekday()]

        verdict: Literal["ok", "conflict"] = "ok" if actual_zh == claim.claimed_weekday_zh else "conflict"
        return VerificationResult(
            claim=claim,
            verdict=verdict,
            claimed_weekday_zh=claim.claimed_weekday_zh,
            actual_weekday_zh=actual_zh,
        )
