"""Regex-based fact claim extractors."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class FactClaim:
    """A single factual claim extracted from text."""

    kind: str  # "date_weekday" | "math" | "unit" | "exchange_rate"
    raw_text: str  # The full matched string
    date_str: str | None = None
    claimed_weekday_zh: str | None = None
    expression: str | None = None
    claimed_result: str | None = None
    claimed_value: float | None = None
    from_unit: str | None = None
    to_unit: str | None = None
    from_ccy: str | None = None
    to_ccy: str | None = None


WEEKDAY_MAP = {
    "一": 0,
    "二": 1,
    "三": 2,
    "四": 3,
    "五": 4,
    "六": 5,
    "日": 6,
    "天": 6,
    "末": 6,
    "Monday": 0,
    "Tuesday": 1,
    "Wednesday": 2,
    "Thursday": 3,
    "Friday": 4,
    "Saturday": 5,
    "Sunday": 6,
    "Mon": 0,
    "Tue": 1,
    "Wed": 2,
    "Thu": 3,
    "Fri": 4,
    "Sat": 5,
    "Sun": 6,
}

_EN_TO_ZH = {0: "星期一", 1: "星期二", 2: "星期三", 3: "星期四", 4: "星期五", 5: "星期六", 6: "星期日"}


def _normalize_weekday(name: str) -> str | None:
    """Return 星期X if input is a valid weekday name, else None."""
    name = name.strip()
    if name.startswith("星期") or name.startswith("周"):
        rest = name[2:] if name.startswith("星期") else name[1:]
        if rest in WEEKDAY_MAP:
            return f"星期{rest}"
        return None
    if name in WEEKDAY_MAP:
        return _EN_TO_ZH[WEEKDAY_MAP[name]]
    return None


class DateWeekdayExtractor:
    """Extract claims of form '<date> <weekday>' from text."""

    _RE_ZH = re.compile(
        r".*?(?P<date>\d{4}年\d{1,2}月\d{1,2}日)"
        r"[\s,，、]*(?P<wd>星期[一二三四五六日天末])"
    )
    _RE_ISO = re.compile(
        r"(?P<date>\d{4}-\d{1,2}-\d{1,2})"
        r"[\s,，、]*(?P<wd>(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)(?:day)?)"
        r"|(?P<wd2>(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)(?:day)?)"
        r"[\s,，、]+(?P<date2>\d{4}-\d{1,2}-\d{1,2})"
    )

    def extract(self, text: str) -> list[FactClaim]:
        claims: list[FactClaim] = []
        for m in self._RE_ZH.finditer(text):
            wd_zh = _normalize_weekday(m.group("wd"))
            if wd_zh:
                claims.append(
                    FactClaim(
                        kind="date_weekday",
                        raw_text=m.group(0),
                        date_str=m.group("date"),
                        claimed_weekday_zh=wd_zh,
                    )
                )
        for m in self._RE_ISO.finditer(text):
            date_str = m.group("date") or m.group("date2")
            wd_name = m.group("wd") or m.group("wd2")
            wd_zh = _normalize_weekday(wd_name)
            if wd_zh:
                claims.append(
                    FactClaim(
                        kind="date_weekday",
                        raw_text=m.group(0),
                        date_str=date_str,
                        claimed_weekday_zh=wd_zh,
                    )
                )
        return claims


class MathExtractor:
    """Extract arithmetic claims of form '<expr> = <result>' from text."""

    _RE = re.compile(
        r"(?P<expr>[\d.]+\s*[a-zA-Z%]*\s*(?:[+\-*/×÷]|乘以|除以|加上|减去|乘|除)\s*[\d.]+\s*[a-zA-Z%]*)"
        r"\s*(?:=|等于|是)\s*"
        r"(?P<result>[\d.]+\s*[a-zA-Z%]*)"
    )

    def extract(self, text: str) -> list[FactClaim]:
        claims: list[FactClaim] = []
        for m in self._RE.finditer(text):
            claims.append(
                FactClaim(
                    kind="math",
                    raw_text=m.group(0),
                    expression=m.group("expr").strip(),
                    claimed_result=m.group("result").strip(),
                )
            )
        return claims


class UnitsExtractor:
    """从文本中抽取单位换算声明,形式为 '<数值><单位> = <结果><单位>'。

    支持中英文运算符（=、等于、是、->、→、转换到、转成）和常见
    单位别名（摄氏度/°C/℃ → C、华氏度/°F/℉ → F 等）。
    """

    _RE = re.compile(
        r"(?P<value>[\d.]+)\s*(?P<from_u>[a-zA-Z°℃℉]+)"
        r"\s*(?:=|等于|是|->|→|转换到|转成)\s*"
        r"(?P<result>[\d.]+)\s*(?P<to_u>[a-zA-Z°℃℉]+)"
    )

    _ALIASES: dict[str, str] = {
        "°C": "C",
        "℃": "C",
        "摄氏度": "C",
        "度C": "C",
        "°F": "F",
        "℉": "F",
        "华氏度": "F",
        "度F": "F",
        "°K": "K",
        "开尔文": "K",
        "公里": "km",
        "千米": "km",
        "米": "m",
        "英尺": "ft",
        "千克": "kg",
        "克": "g",
        "磅": "lb",
        "升": "L",
        "毫升": "mL",
    }

    @staticmethod
    def _normalize(u: str) -> str:
        """用别名表把单位写法归一到 ``units.py`` 支持的规范名。"""
        return UnitsExtractor._ALIASES.get(u.strip(), u.strip())

    def extract(self, text: str) -> list[FactClaim]:
        """返回文本中匹配到的所有单位换算声明。"""
        claims: list[FactClaim] = []
        for m in self._RE.finditer(text):
            try:
                claims.append(
                    FactClaim(
                        kind="unit",
                        raw_text=m.group(0),
                        claimed_value=float(m.group("value")),
                        claimed_result=str(m.group("result")),
                        from_unit=self._normalize(m.group("from_u")),
                        to_unit=self._normalize(m.group("to_u")),
                    )
                )
            except ValueError:
                continue
        return claims


class ExchangeRateExtractor:
    """从文本中抽取汇率换算声明,形式为 '<数值><币种> = <结果><币种>'。

    支持英文三字母币种代码 (USD/CNY 等) 和常见中文币种名
    (美元/欧元/英镑/日元/港币/人民币)。运算符兼容 =、≈、约、约等于、大概是。
    """

    _RE_EN = re.compile(
        r"(?P<value>[\d.]+)\s*(?P<from>[A-Z]{3})"
        r"\s*(?:=|≈|约等于|约|大概是)\s*"
        r"(?P<result>[\d.]+)\s*(?P<to>[A-Z]{3})"
    )
    _RE_ZH = re.compile(
        r"(?P<value>[\d.]+)\s*(?P<from>美元|欧元|英镑|日元|港币|人民币)"
        r"\s*(?:=|≈|约|大概是|大约)\s*"
        r"(?P<result>[\d.]+)\s*(?P<to>美元|欧元|英镑|日元|港币|人民币)"
    )
    _ZH_CCY: dict[str, str] = {
        "美元": "USD",
        "欧元": "EUR",
        "英镑": "GBP",
        "日元": "JPY",
        "港币": "HKD",
        "人民币": "CNY",
    }

    def extract(self, text: str) -> list[FactClaim]:
        """返回文本中匹配到的所有汇率换算声明。"""
        claims: list[FactClaim] = []
        for m in self._RE_EN.finditer(text):
            try:
                claims.append(
                    FactClaim(
                        kind="exchange_rate",
                        raw_text=m.group(0),
                        claimed_value=float(m.group("value")),
                        claimed_result=str(m.group("result")),
                        from_ccy=m.group("from"),
                        to_ccy=m.group("to"),
                    )
                )
            except ValueError:
                continue
        for m in self._RE_ZH.finditer(text):
            try:
                claims.append(
                    FactClaim(
                        kind="exchange_rate",
                        raw_text=m.group(0),
                        claimed_value=float(m.group("value")),
                        claimed_result=str(m.group("result")),
                        from_ccy=self._ZH_CCY[m.group("from")],
                        to_ccy=self._ZH_CCY[m.group("to")],
                    )
                )
            except (ValueError, KeyError):
                continue
        return claims
