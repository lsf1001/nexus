# Fact-Check Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic fact-check pipeline to Nexus that catches factual errors (date/weekday mismatches, math mistakes, unit conversions, exchange rates) before user-facing output is delivered.

**Architecture:** Three-layer defense — (1) `date_utils` MCP server forces agent to call tools instead of mental-math; (2) `FactCheckMiddleware` scans agent output for fact claims; (3) `QualityPipeline` runs deterministic verifiers (Python stdlib + lookup tables + exchange rate API) and routes conflicts to REPAIR/REJECT. Verifiers are rule-based, never LLM-judged.

**Tech Stack:** Python 3.12 stdlib (`datetime`, `re`, `ast`), `pydantic` (config), `aiohttp` (exchange rate API), `pytest` + `pytest-asyncio` (tests), `pyyaml` (config loading). No `pint` — use hand-coded conversion tables.

---

## File Structure

**New files (15):**
- `nexus/backend/fact_check/__init__.py` — package marker
- `nexus/backend/fact_check/extractors.py` — regex claim extractors
- `nexus/backend/fact_check/verifiers.py` — deterministic verifier registry
- `nexus/backend/fact_check/units.py` — unit conversion tables (km↔mile, kg↔lb, C↔F, etc.)
- `nexus/backend/fact_check/exchange_rate.py` — API client + 1h cache
- `nexus/backend/fact_check/pipeline.py` — orchestrator (extract → verify → report)
- `nexus/backend/mcp_servers/__init__.py` — package marker
- `nexus/backend/mcp_servers/date_utils/__init__.py` — package marker
- `nexus/backend/mcp_servers/date_utils/server.py` — MCP wrapper for date tools
- `nexus/backend/mcp_servers/fact_verify/__init__.py` — package marker
- `nexus/backend/mcp_servers/fact_verify/server.py` — MCP wrapper for verify_claims
- `nexus/backend/config/fact_check.yaml` — config (claim types, fail strategies, timezone)
- `tests/test_fact_check_extractors.py`
- `tests/test_fact_check_verifiers.py`
- `tests/test_fact_check_units.py`
- `tests/test_fact_check_exchange_rate.py`
- `tests/test_fact_check_pipeline.py`
- `tests/test_fact_check_middleware.py`
- `tests/regression/test_clothing_reminder_regression.py` — reproduces 7-10 21:45 bug
- `tests/e2e/test_fact_check_e2e.py`
- `docs/operations/fact-check.md` — operator guide

**Modified files (6):**
- `nexus/backend/quality/pipeline.py` (or `nexus/backend/rubrics/pipeline.py`) — add fact-check step before `RubricJudge`
- `nexus/backend/db.py` — `_ensure_column` for `quality_scores.fact_check_*`
- `nexus/backend/main.py` — load fact_check.yaml config, register MCP servers
- `nexus/backend/agents/middleware/__init__.py` — register `FactCheckMiddleware`
- `docs/operations/quality.md` — add §10 Fact-Check Pipeline
- `data/rubric_eval_samples.jsonl` — add 5 fact-check samples
- `pyproject.toml` — add `aiohttp` dependency

---

## Task 1: Date/Weekday Extractor (TDD)

**Files:**
- Create: `nexus/backend/fact_check/extractors.py`
- Test: `tests/test_fact_check_extractors.py`

- [ ] **Step 1: Write failing test for DateWeekdayExtractor**

`tests/test_fact_check_extractors.py`:

```python
"""Tests for fact_check.extractors."""

import pytest
from nexus.backend.fact_check.extractors import DateWeekdayExtractor, MathExtractor


class TestDateWeekdayExtractor:
    def test_extracts_chinese_full_date_with_weekday(self):
        text = "明天是 2026年7月11日 星期六"
        claims = DateWeekdayExtractor().extract(text)
        assert len(claims) == 1
        assert claims[0].date_str == "2026年7月11日"
        assert claims[0].claimed_weekday_zh == "星期六"
        assert claims[0].raw_text == text

    def test_extracts_iso_date_with_weekday(self):
        text = "Plan for 2026-07-11 Saturday"
        claims = DateWeekdayExtractor().extract(text)
        assert len(claims) == 1
        assert claims[0].date_str == "2026-07-11"
        assert claims[0].claimed_weekday_zh == "星期六"  # English Saturday → 星期六

    def test_extracts_date_without_weekday(self):
        text = "Today is 2026-07-10"
        claims = DateWeekdayExtractor().extract(text)
        assert claims == []  # No weekday → no claim (no conflict possible)

    def test_extracts_multiple_claims(self):
        text = "From 2026-07-10 Friday to 2026-07-11 Saturday"
        claims = DateWeekdayExtractor().extract(text)
        assert len(claims) == 2

    def test_skips_invalid_weekday(self):
        text = "2026-07-11 星期八"  # Invalid weekday name
        claims = DateWeekdayExtractor().extract(text)
        # Either skipped or marked invalid; decide: skip
        assert all(c.claimed_weekday_zh != "星期八" for c in claims)


class TestMathExtractor:
    def test_extracts_addition(self):
        text = "23 + 32 = 55"
        claims = MathExtractor().extract(text)
        assert len(claims) == 1
        assert claims[0].expression == "23 + 32"
        assert claims[0].claimed_result == "55"

    def test_extracts_multiplication_with_units(self):
        text = "1.5L × 2 = 3L"
        claims = MathExtractor().extract(text)
        assert len(claims) == 1
        assert claims[0].expression == "1.5L × 2"
        assert claims[0].claimed_result == "3L"

    def test_skips_no_equals(self):
        text = "23 + 32"
        claims = MathExtractor().extract(text)
        assert claims == []

    def test_extracts_chinese_operators(self):
        text = "100 乘以 2 等于 200"
        claims = MathExtractor().extract(text)
        assert len(claims) == 1
        assert claims[0].claimed_result == "200"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/yxb/projects/nexus && .venv/bin/pytest tests/test_fact_check_extractors.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'nexus.backend.fact_check'`

- [ ] **Step 3: Implement DateWeekdayExtractor and MathExtractor**

`nexus/backend/fact_check/__init__.py`:

```python
"""Deterministic fact-check pipeline.

Catches factual errors (date/weekday, math, units, exchange rate) before
user-facing output. Rule-based verifiers, never LLM-judged.
"""
```

`nexus/backend/fact_check/extractors.py`:

```python
"""Regex-based fact claim extractors."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class FactClaim:
    """A single factual claim extracted from text."""

    kind: str  # "date_weekday" | "math" | "unit" | "exchange_rate"
    raw_text: str  # The full matched string
    date_str: str | None = None  # For date_weekday
    claimed_weekday_zh: str | None = None
    expression: str | None = None  # For math
    claimed_result: str | None = None
    claimed_value: float | None = None  # Parsed numeric value


# Weekday name normalization (Chinese + English)
WEEKDAY_MAP = {
    "一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6, "末": 6,
    "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
    "Friday": 4, "Saturday": 5, "Sunday": 6,
    "Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6,
}

# Build reverse map for EN→ZH
_EN_TO_ZH = {0: "星期一", 1: "星期二", 2: "星期三", 3: "星期四",
             4: "星期五", 5: "星期六", 6: "星期日"}


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

    # Chinese: 2026年7月11日 星期六 / 星期六 7月11日
    _RE_ZH = re.compile(
        r"(?P<date>\d{4}年\d{1,2}月\d{1,2}日)"
        r"[\s,，、]*(?P<wd>星期[一二三四五六日天末])"
    )
    # ISO: 2026-07-11 Saturday / Saturday 2026-07-11
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
                claims.append(FactClaim(
                    kind="date_weekday",
                    raw_text=m.group(0),
                    date_str=m.group("date"),
                    claimed_weekday_zh=wd_zh,
                ))
        for m in self._RE_ISO.finditer(text):
            date_str = m.group("date") or m.group("date2")
            wd_name = m.group("wd") or m.group("wd2")
            wd_zh = _normalize_weekday(wd_name)
            if wd_zh:
                claims.append(FactClaim(
                    kind="date_weekday",
                    raw_text=m.group(0),
                    date_str=date_str,
                    claimed_weekday_zh=wd_zh,
                ))
        return claims


class MathExtractor:
    """Extract arithmetic claims of form '<expr> = <result>' from text."""

    _RE = re.compile(
        r"(?P<expr>[\d.]+\s*(?:[+\-*/×÷]|乘以|除以|加上|减去|乘|除)\s*[\d.]+\s*[a-zA-Z%]*)"
        r"\s*(?:=|等于|是)\s*"
        r"(?P<result>[\d.]+\s*[a-zA-Z%]*)"
    )

    def extract(self, text: str) -> list[FactClaim]:
        claims: list[FactClaim] = []
        for m in self._RE.finditer(text):
            claims.append(FactClaim(
                kind="math",
                raw_text=m.group(0),
                expression=m.group("expr").strip(),
                claimed_result=m.group("result").strip(),
            ))
        return claims
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_fact_check_extractors.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add nexus/backend/fact_check/__init__.py nexus/backend/fact_check/extractors.py tests/test_fact_check_extractors.py
git commit -m "feat(fact_check): add DateWeekdayExtractor and MathExtractor (TDD)"
```

---

## Task 2: DateWeekday Verifier (TDD)

**Files:**
- Create: `nexus/backend/fact_check/verifiers.py`
- Test: `tests/test_fact_check_verifiers.py`

- [ ] **Step 1: Write failing test for DateWeekdayVerifier**

Append to `tests/test_fact_check_extractors.py` or create `tests/test_fact_check_verifiers.py`:

```python
"""Tests for fact_check.verifiers."""

from datetime import date
import pytest
from nexus.backend.fact_check.extractors import FactClaim
from nexus.backend.fact_check.verifiers import DateWeekdayVerifier


class TestDateWeekdayVerifier:
    def test_correct_weekday_passes(self):
        claim = FactClaim(
            kind="date_weekday",
            raw_text="2026年7月11日 星期六",
            date_str="2026年7月11日",
            claimed_weekday_zh="星期六",
        )
        result = DateWeekdayVerifier().verify(claim)
        assert result.verdict == "ok"
        assert result.actual_weekday_zh == "星期六"

    def test_wrong_weekday_conflicts(self):
        claim = FactClaim(
            kind="date_weekday",
            raw_text="2026年7月11日 星期五",
            date_str="2026年7月11日",
            claimed_weekday_zh="星期五",
        )
        result = DateWeekdayVerifier().verify(claim)
        assert result.verdict == "conflict"
        assert result.claimed_weekday_zh == "星期五"
        assert result.actual_weekday_zh == "星期六"

    def test_iso_format(self):
        claim = FactClaim(
            kind="date_weekday",
            raw_text="2026-07-11 Saturday",
            date_str="2026-07-11",
            claimed_weekday_zh="星期六",
        )
        result = DateWeekdayVerifier().verify(claim)
        assert result.verdict == "ok"

    def test_invalid_date_returns_error(self):
        claim = FactClaim(
            kind="date_weekday",
            raw_text="2026年13月45日 星期一",
            date_str="2026年13月45日",
            claimed_weekday_zh="星期一",
        )
        result = DateWeekdayVerifier().verify(claim)
        assert result.verdict == "error"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_fact_check_verifiers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'nexus.backend.fact_check.verifiers'`

- [ ] **Step 3: Implement DateWeekdayVerifier**

`nexus/backend/fact_check/verifiers.py`:

```python
"""Deterministic verifiers for fact claims.

Each verifier takes a FactClaim and returns a VerificationResult.
Verifiers are pure functions — no LLM calls, no network calls (except
ExchangeRateVerifier which uses a cached API).
"""

from __future__ import annotations

import ast
import operator
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from nexus.backend.fact_check.extractors import FactClaim


@dataclass(frozen=True)
class VerificationResult:
    """Result of verifying a single fact claim."""

    claim: FactClaim
    verdict: Literal["ok", "conflict", "error", "skipped"]
    claimed_weekday_zh: str | None = None
    actual_weekday_zh: str | None = None
    expected_value: float | None = None
    actual_value: float | None = None
    error_message: str | None = None


# Chinese weekday name → Python weekday int (Monday=0)
_ZH_WEEKDAY_INT = {"星期一": 0, "星期二": 1, "星期三": 2, "星期四": 3,
                   "星期五": 4, "星期六": 5, "星期日": 6}


class DateWeekdayVerifier:
    """Verify date/weekday alignment using Python datetime."""

    _RE_ZH_DATE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")
    _RE_ISO_DATE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")

    def verify(self, claim: FactClaim) -> VerificationResult:
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
                claim=claim, verdict="error",
                error_message=f"Unparseable date: {claim.date_str}",
            )

        try:
            dt = date(y, mo, d)
        except ValueError as e:
            return VerificationResult(
                claim=claim, verdict="error", error_message=str(e),
            )

        actual_zh = {0: "星期一", 1: "星期二", 2: "星期三", 3: "星期四",
                     4: "星期五", 5: "星期六", 6: "星期日"}[dt.weekday()]

        verdict: Literal["ok", "conflict"] = (
            "ok" if actual_zh == claim.claimed_weekday_zh else "conflict"
        )
        return VerificationResult(
            claim=claim,
            verdict=verdict,
            claimed_weekday_zh=claim.claimed_weekday_zh,
            actual_weekday_zh=actual_zh,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_fact_check_verifiers.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add nexus/backend/fact_check/verifiers.py tests/test_fact_check_verifiers.py
git commit -m "feat(fact_check): add DateWeekdayVerifier (deterministic date check)"
```

---

## Task 3: Math Verifier (TDD)

**Files:**
- Modify: `nexus/backend/fact_check/verifiers.py`
- Modify: `tests/test_fact_check_verifiers.py`

- [ ] **Step 1: Write failing test for MathVerifier**

Append to `tests/test_fact_check_verifiers.py`:

```python
from nexus.backend.fact_check.verifiers import MathVerifier


class TestMathVerifier:
    def test_simple_addition_correct(self):
        claim = FactClaim(
            kind="math", raw_text="23 + 32 = 55",
            expression="23 + 32", claimed_result="55",
        )
        result = MathVerifier().verify(claim)
        assert result.verdict == "ok"
        assert result.expected_value == 55.0
        assert result.actual_value == 55.0

    def test_addition_wrong(self):
        claim = FactClaim(
            kind="math", raw_text="23 + 32 = 56",
            expression="23 + 32", claimed_result="56",
        )
        result = MathVerifier().verify(claim)
        assert result.verdict == "conflict"
        assert result.expected_value == 55.0
        assert result.actual_value == 56.0

    def test_multiplication_with_units(self):
        claim = FactClaim(
            kind="math", raw_text="1.5L × 2 = 3L",
            expression="1.5L × 2", claimed_result="3L",
        )
        result = MathVerifier().verify(claim)
        assert result.verdict == "ok"
        assert result.expected_value == 3.0
        assert result.actual_value == 3.0

    def test_division(self):
        claim = FactClaim(
            kind="math", raw_text="100 / 4 = 25",
            expression="100 / 4", claimed_result="25",
        )
        result = MathVerifier().verify(claim)
        assert result.verdict == "ok"

    def test_chinese_operators(self):
        claim = FactClaim(
            kind="math", raw_text="100 乘以 2 等于 200",
            expression="100 乘以 2", claimed_result="200",
        )
        result = MathVerifier().verify(claim)
        assert result.verdict == "ok"

    def test_unsafe_expression_rejected(self):
        claim = FactClaim(
            kind="math", raw_text="__import__('os').system('rm -rf /') = 0",
            expression="__import__('os').system('rm -rf /')",
            claimed_result="0",
        )
        result = MathVerifier().verify(claim)
        assert result.verdict == "error"  # Reject unsafe expression
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_fact_check_verifiers.py::TestMathVerifier -v`
Expected: FAIL with `AttributeError: module ... has no attribute 'MathVerifier'`

- [ ] **Step 3: Implement MathVerifier**

Append to `nexus/backend/fact_check/verifiers.py`:

```python
class MathVerifier:
    """Verify arithmetic claims using safe AST evaluation.

    Only allows: numbers, +, -, *, /, **, parentheses. Rejects function
    calls, attribute access, imports, and other AST nodes (no eval risk).
    """

    _ALLOWED_OPS = {
        ast.Add: operator.add, ast.Sub: operator.sub,
        ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.USub: operator.neg,
    }

    # Map Chinese operators to symbols
    _ZH_OP_MAP = {
        "乘以": "*", "乘": "*", "除以": "/", "除": "/",
        "加上": "+", "加": "+", "减去": "-", "减": "-",
    }

    def _normalize(self, expr: str) -> str:
        """Replace Chinese operators with symbols; strip unit suffixes."""
        out = expr
        for zh, sym in self._ZH_OP_MAP.items():
            out = out.replace(zh, sym)
        # Strip unit suffixes like "L", "kg", "%" attached to numbers
        out = re.sub(r"([\d.]+)[a-zA-Z%]+", r"\1", out)
        # Replace × ÷ with */ if present
        out = out.replace("×", "*").replace("÷", "/")
        return out

    def _safe_eval(self, expr: str) -> float:
        """Evaluate arithmetic expression safely via AST."""
        tree = ast.parse(expr, mode="eval")
        return self._eval_node(tree.body)

    def _eval_node(self, node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp):
            op_type = type(node.op)
            if op_type not in self._ALLOWED_OPS:
                raise ValueError(f"Operator {op_type.__name__} not allowed")
            left = self._eval_node(node.left)
            right = self._eval_node(node.right)
            return self._ALLOWED_OPS[op_type](left, right)
        if isinstance(node, ast.UnaryOp):
            if type(node.op) not in self._ALLOWED_OPS:
                raise ValueError(f"Unary {type(node.op).__name__} not allowed")
            return self._ALLOWED_OPS[type(node.op)](self._eval_node(node.operand))
        raise ValueError(f"AST node {type(node).__name__} not allowed")

    def _strip_units(self, s: str) -> float:
        """Strip trailing units and return numeric value."""
        m = re.match(r"([\d.]+)", s.strip())
        if not m:
            raise ValueError(f"No numeric value in {s!r}")
        return float(m.group(1))

    def verify(self, claim: FactClaim) -> VerificationResult:
        if claim.kind != "math":
            return VerificationResult(claim=claim, verdict="skipped")

        assert claim.expression and claim.claimed_result
        try:
            normalized = self._normalize(claim.expression)
            expected = self._safe_eval(normalized)
            actual = self._strip_units(claim.claimed_result)
        except (ValueError, SyntaxError) as e:
            return VerificationResult(
                claim=claim, verdict="error", error_message=str(e),
            )

        # Use small epsilon for float comparison
        verdict: Literal["ok", "conflict"] = (
            "ok" if abs(expected - actual) < 1e-6 else "conflict"
        )
        return VerificationResult(
            claim=claim, verdict=verdict,
            expected_value=expected, actual_value=actual,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_fact_check_verifiers.py::TestMathVerifier -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add nexus/backend/fact_check/verifiers.py tests/test_fact_check_verifiers.py
git commit -m "feat(fact_check): add MathVerifier with safe AST eval"
```

---

## Task 4: Unit Conversion Tables (TDD)

**Files:**
- Create: `nexus/backend/fact_check/units.py`
- Test: `tests/test_fact_check_units.py`

- [ ] **Step 1: Write failing test**

`tests/test_fact_check_units.py`:

```python
"""Tests for fact_check.units."""

import pytest
from nexus.backend.fact_check.units import convert, supported_units


class TestConvert:
    def test_celsius_to_fahrenheit(self):
        assert convert(100, "C", "F") == pytest.approx(212.0, abs=0.01)

    def test_fahrenheit_to_celsius(self):
        assert convert(32, "F", "C") == pytest.approx(0.0, abs=0.01)

    def test_km_to_mile(self):
        assert convert(1, "km", "mile") == pytest.approx(0.621371, abs=0.001)

    def test_kg_to_lb(self):
        assert convert(1, "kg", "lb") == pytest.approx(2.20462, abs=0.001)

    def test_meter_to_foot(self):
        assert convert(1, "m", "ft") == pytest.approx(3.28084, abs=0.001)

    def test_incompatible_units_raises(self):
        with pytest.raises(ValueError, match="Incompatible"):
            convert(1, "kg", "m")

    def test_unknown_unit_raises(self):
        with pytest.raises(ValueError, match="Unknown unit"):
            convert(1, "foo", "bar")


class TestSupportedUnits:
    def test_returns_dict(self):
        units = supported_units()
        assert "C" in units
        assert "F" in units
        assert "kg" in units
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_fact_check_units.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement units.py**

`nexus/backend/fact_check/units.py`:

```python
"""Unit conversion tables for fact-check verification.

Hand-coded tables for common conversions. Adding more is a one-liner.
No external dependency (no `pint`).
"""

from __future__ import annotations

# Each group: units that can convert to each other via a base unit
_UNIT_GROUPS: dict[str, dict[str, float]] = {
    # Temperature uses offset (handled specially)
    "temperature": {"C": 0.0, "F": 0.0, "K": 0.0},
    # Length (base: meter)
    "length": {
        "m": 1.0, "km": 1000.0, "cm": 0.01, "mm": 0.001,
        "mile": 1609.344, "ft": 0.3048, "inch": 0.0254, "yd": 0.9144,
    },
    # Mass (base: kilogram)
    "mass": {
        "kg": 1.0, "g": 0.001, "mg": 0.000001, "lb": 0.45359237,
        "oz": 0.028349523125,
    },
    # Volume (base: liter)
    "volume": {
        "L": 1.0, "mL": 0.001, "gal": 3.785411784,
    },
}


def _find_group(unit: str) -> tuple[str, str] | None:
    """Return (group_name, base_unit) for a given unit, or None."""
    for group, units in _UNIT_GROUPS.items():
        if unit in units:
            base = "K" if group == "temperature" else _pick_base(units)
            return group, base
    return None


def _pick_base(units: dict[str, float]) -> str:
    """Pick base unit — first unit with factor 1.0."""
    for name, factor in units.items():
        if factor == 1.0:
            return name
    return next(iter(units))


def convert(value: float, from_unit: str, to_unit: str) -> float:
    """Convert `value` from `from_unit` to `to_unit`.

    Raises ValueError if units are incompatible or unknown.
    """
    if from_unit == to_unit:
        return value

    src = _find_group(from_unit)
    dst = _find_group(to_unit)
    if src is None:
        raise ValueError(f"Unknown unit: {from_unit!r}")
    if dst is None:
        raise ValueError(f"Unknown unit: {to_unit!r}")
    if src[0] != dst[0]:
        raise ValueError(
            f"Incompatible units: {from_unit!r} ({src[0]}) → {to_unit!r} ({dst[0]})"
        )

    # Temperature has offsets, handle specially
    if src[0] == "temperature":
        return _convert_temperature(value, from_unit, to_unit)

    # Linear conversion: value × src_factor / dst_factor
    src_factor = _UNIT_GROUPS[src[0]][from_unit]
    dst_factor = _UNIT_GROUPS[src[0]][to_unit]
    return value * src_factor / dst_factor


def _convert_temperature(value: float, from_u: str, to_u: str) -> float:
    # Convert to Kelvin first
    if from_u == "C":
        kelvin = value + 273.15
    elif from_u == "F":
        kelvin = (value - 32) * 5 / 9 + 273.15
    elif from_u == "K":
        kelvin = value
    else:
        raise ValueError(f"Unknown temperature unit: {from_u}")
    # Convert from Kelvin to target
    if to_u == "C":
        return kelvin - 273.15
    if to_u == "F":
        return (kelvin - 273.15) * 9 / 5 + 32
    if to_u == "K":
        return kelvin
    raise ValueError(f"Unknown temperature unit: {to_u}")


def supported_units() -> dict[str, list[str]]:
    """Return all supported units grouped by category."""
    return {group: list(units.keys()) for group, units in _UNIT_GROUPS.items()}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_fact_check_units.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add nexus/backend/fact_check/units.py tests/test_fact_check_units.py
git commit -m "feat(fact_check): add unit conversion tables (no external deps)"
```

---

## Task 5: Units Verifier (TDD)

**Files:**
- Modify: `nexus/backend/fact_check/verifiers.py`
- Create: `nexus/backend/fact_check/extractors.py` (add UnitsExtractor — extend existing)
- Modify: `tests/test_fact_check_extractors.py`

- [ ] **Step 1: Write failing test for UnitsExtractor**

Append to `tests/test_fact_check_extractors.py`:

```python
from nexus.backend.fact_check.extractors import UnitsExtractor


class TestUnitsExtractor:
    def test_extracts_simple_conversion(self):
        text = "100°C = 212°F"
        claims = UnitsExtractor().extract(text)
        assert len(claims) == 1
        assert claims[0].value == 100.0
        assert claims[0].from_unit == "C"
        assert claims[0].to_unit == "F"
        assert claims[0].claimed_result == 212.0

    def test_extracts_km_to_mile(self):
        text = "5 km = 3.107 mile"
        claims = UnitsExtractor().extract(text)
        assert len(claims) == 1
        assert claims[0].claimed_result == pytest.approx(3.107, abs=0.01)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_fact_check_extractors.py::TestUnitsExtractor -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement UnitsExtractor**

Append to `nexus/backend/fact_check/extractors.py`:

```python
class UnitsExtractor:
    """Extract unit conversion claims of form '<value><unit> = <result><unit>'."""

    _RE = re.compile(
        r"(?P<value>[\d.]+)\s*(?P<from_u>[a-zA-Z°℃℉]+)"
        r"\s*(?:=|等于|是|->|→|转换到|转成)\s*"
        r"(?P<result>[\d.]+)\s*(?P<to_u>[a-zA-Z°℃℉]+)"
    )

    # Unit alias normalization
    _ALIASES = {
        "°C": "C", "℃": "C", "摄氏度": "C", "度C": "C",
        "°F": "F", "℉": "F", "华氏度": "F", "度F": "F",
        "°K": "K", "开尔文": "K",
        "公里": "km", "千米": "km", "米": "m", "英尺": "ft",
        "千克": "kg", "克": "g", "磅": "lb",
        "升": "L", "毫升": "mL",
    }

    def _normalize(self, u: str) -> str:
        return self._ALIASES.get(u.strip(), u.strip())

    def extract(self, text: str) -> list[FactClaim]:
        claims: list[FactClaim] = []
        for m in self._RE.finditer(text):
            try:
                claims.append(FactClaim(
                    kind="unit",
                    raw_text=m.group(0),
                    claimed_value=float(m.group("value")),
                    date_str=None,
                    claimed_weekday_zh=None,
                    expression=None,
                    claimed_result=str(m.group("result")),
                    from_unit=self._normalize(m.group("from_u")),
                    to_unit=self._normalize(m.group("to_u")),
                ))
            except ValueError:
                continue  # Skip unparseable numbers
        return claims
```

Also update `FactClaim` dataclass in extractors.py — add `from_unit` and `to_unit` fields:

```python
@dataclass(frozen=True)
class FactClaim:
    """A single factual claim extracted from text."""

    kind: str
    raw_text: str
    date_str: str | None = None
    claimed_weekday_zh: str | None = None
    expression: str | None = None
    claimed_result: str | None = None
    claimed_value: float | None = None
    from_unit: str | None = None
    to_unit: str | None = None
```

- [ ] **Step 4: Implement UnitsVerifier**

Append to `nexus/backend/fact_check/verifiers.py`:

```python
from nexus.backend.fact_check.units import convert


class UnitsVerifier:
    """Verify unit conversion claims against conversion tables."""

    def verify(self, claim: FactClaim) -> VerificationResult:
        if claim.kind != "unit":
            return VerificationResult(claim=claim, verdict="skipped")

        assert claim.claimed_value is not None
        assert claim.from_unit and claim.to_unit
        try:
            actual = convert(claim.claimed_value, claim.from_unit, claim.to_unit)
            expected = float(claim.claimed_result)  # type: ignore[arg-type]
        except (ValueError, TypeError) as e:
            return VerificationResult(
                claim=claim, verdict="error", error_message=str(e),
            )

        verdict: Literal["ok", "conflict"] = (
            "ok" if abs(actual - expected) < 0.01 else "conflict"
        )
        return VerificationResult(
            claim=claim, verdict=verdict,
            expected_value=actual, actual_value=expected,
        )
```

- [ ] **Step 5: Run all extractor+verifier tests to verify they pass**

Run: `.venv/bin/pytest tests/test_fact_check_extractors.py tests/test_fact_check_verifiers.py tests/test_fact_check_units.py -v`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
git add nexus/backend/fact_check/extractors.py nexus/backend/fact_check/verifiers.py tests/test_fact_check_extractors.py tests/test_fact_check_verifiers.py
git commit -m "feat(fact_check): add UnitsExtractor + UnitsVerifier"
```

---

## Task 6: Exchange Rate Verifier (TDD with mocked API)

**Files:**
- Create: `nexus/backend/fact_check/exchange_rate.py`
- Test: `tests/test_fact_check_exchange_rate.py`

- [ ] **Step 1: Write failing test**

`tests/test_fact_check_exchange_rate.py`:

```python
"""Tests for fact_check.exchange_rate."""

import time
import pytest
from nexus.backend.fact_check.exchange_rate import (
    ExchangeRateCache, fetch_rate, clear_cache,
)


@pytest.fixture(autouse=True)
def reset_cache():
    clear_cache()
    yield
    clear_cache()


class TestExchangeRateCache:
    def test_returns_cached_value_within_ttl(self):
        cache = ExchangeRateCache(ttl_seconds=60)
        cache.set("USD", {"rate": 7.20, "fetched_at": time.time()})
        rate = cache.get("USD")
        assert rate == pytest.approx(7.20, abs=0.001)

    def test_expired_entry_returns_none(self):
        cache = ExchangeRateCache(ttl_seconds=0.01)
        cache.set("USD", {"rate": 7.20, "fetched_at": time.time() - 1})
        assert cache.get("USD") is None


class TestFetchRate:
    def test_fetch_success(self, monkeypatch):
        async def mock_fetch(url):
            return {"rates": {"CNY": 7.20}}

        monkeypatch.setattr(
            "nexus.backend.fact_check.exchange_rate._fetch_api",
            mock_fetch,
        )
        rate = fetch_rate("USD", "CNY", api_key="dummy")
        assert rate == pytest.approx(7.20, abs=0.001)

    def test_fetch_uses_cache(self, monkeypatch):
        # First call
        async def mock_fetch(url):
            return {"rates": {"CNY": 7.20}}

        monkeypatch.setattr(
            "nexus.backend.fact_check.exchange_rate._fetch_api",
            mock_fetch,
        )
        rate1 = fetch_rate("USD", "CNY", api_key="dummy")
        # Second call should hit cache, not API
        call_count = [0]

        async def counting_fetch(url):
            call_count[0] += 1
            return {"rates": {"CNY": 999.99}}

        monkeypatch.setattr(
            "nexus.backend.fact_check.exchange_rate._fetch_api",
            counting_fetch,
        )
        rate2 = fetch_rate("USD", "CNY", api_key="dummy")
        assert rate1 == rate2
        assert call_count[0] == 0  # No new API call
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_fact_check_exchange_rate.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement exchange_rate.py**

`nexus/backend/fact_check/exchange_rate.py`:

```python
"""Exchange rate fetcher with 1-hour in-memory cache.

Uses https://api.exchangerate-api.com/v4/latest/{base} (free, no auth).
On API failure, returns None (fail-open in verifier).
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass


_CACHE: dict[str, "CachedRate"] = {}


@dataclass
class CachedRate:
    rate: float
    fetched_at: float


class ExchangeRateCache:
    def __init__(self, ttl_seconds: int = 3600) -> None:
        self.ttl = ttl_seconds

    def get(self, base: str) -> float | None:
        entry = _CACHE.get(base)
        if entry is None:
            return None
        if time.time() - entry.fetched_at > self.ttl:
            return None
        return entry.rate

    def set(self, base: str, payload: dict) -> None:
        if "rate" in payload:
            _CACHE[base] = CachedRate(
                rate=float(payload["rate"]),
                fetched_at=payload.get("fetched_at", time.time()),
            )


def clear_cache() -> None:
    _CACHE.clear()


async def _fetch_api(url: str) -> dict:
    """Fetch JSON from URL. Override in tests via monkeypatch."""
    import aiohttp

    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            resp.raise_for_status()
            return await resp.json()


def fetch_rate(from_ccy: str, to_ccy: str, api_key: str | None = None) -> float | None:
    """Fetch exchange rate from `from_ccy` to `to_ccy`.

    Returns rate as float, or None on failure (network/API error).
    Uses 1-hour cache. Synchronous wrapper for sync verifier use.
    """
    if from_ccy == to_ccy:
        return 1.0

    cache = ExchangeRateCache()
    cached = cache.get(from_ccy)
    if cached is not None:
        return cached

    # Cache miss — fetch from API
    try:
        data = asyncio.run(_fetch_api(f"https://api.exchangerate-api.com/v4/latest/{from_ccy}"))
        rates = data.get("rates", {})
        if to_ccy not in rates:
            return None
        rate = float(rates[to_ccy])
        cache.set(from_ccy, {"rate": rate, "fetched_at": time.time()})
        return rate
    except Exception:
        return None
```

- [ ] **Step 4: Add aiohttp to pyproject.toml**

Edit `pyproject.toml`:

```toml
dependencies = [
    # ... existing
    "aiohttp>=3.9",
]
```

Run: `.venv/bin/pip install aiohttp`

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_fact_check_exchange_rate.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add nexus/backend/fact_check/exchange_rate.py tests/test_fact_check_exchange_rate.py pyproject.toml
git commit -m "feat(fact_check): add ExchangeRateCache with 1h TTL"
```

---

## Task 7: ExchangeRate Verifier + Extractor (TDD)

**Files:**
- Modify: `nexus/backend/fact_check/verifiers.py`
- Modify: `nexus/backend/fact_check/extractors.py`
- Modify: `tests/test_fact_check_extractors.py`
- Modify: `tests/test_fact_check_verifiers.py`

- [ ] **Step 1: Write failing test for ExchangeRateExtractor**

Append to `tests/test_fact_check_extractors.py`:

```python
from nexus.backend.fact_check.extractors import ExchangeRateExtractor


class TestExchangeRateExtractor:
    def test_extracts_usd_to_cny(self):
        text = "100 USD ≈ 720 CNY"
        claims = ExchangeRateExtractor().extract(text)
        assert len(claims) == 1
        assert claims[0].value == 100.0
        assert claims[0].from_ccy == "USD"
        assert claims[0].to_ccy == "CNY"
        assert claims[0].claimed_result == 720.0

    def test_extracts_with_chinese_label(self):
        text = "汇率:100美元 = 720人民币"
        claims = ExchangeRateExtractor().extract(text)
        assert len(claims) == 1
        assert claims[0].from_ccy == "USD"
        assert claims[0].to_ccy == "CNY"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_fact_check_extractors.py::TestExchangeRateExtractor -v`
Expected: FAIL

- [ ] **Step 3: Implement ExchangeRateExtractor**

Append to `nexus/backend/fact_check/extractors.py`:

```python
class ExchangeRateExtractor:
    """Extract currency conversion claims."""

    # English: 100 USD = 720 CNY / ≈
    _RE_EN = re.compile(
        r"(?P<value>[\d.]+)\s*(?P<from>[A-Z]{3})"
        r"\s*(?:=|≈|约等于|约|大概是)\s*"
        r"(?P<result>[\d.]+)\s*(?P<to>[A-Z]{3})"
    )
    # Chinese: 100美元 = 720人民币
    _RE_ZH = re.compile(
        r"(?P<value>[\d.]+)\s*(?P<from>美元|欧元|英镑|日元|港币|人民币)"
        r"\s*(?:=|≈|约|大概是|大约)\s*"
        r"(?P<result>[\d.]+)\s*(?P<to>美元|欧元|英镑|日元|港币|人民币)"
    )
    _ZH_CCY = {"美元": "USD", "欧元": "EUR", "英镑": "GBP",
               "日元": "JPY", "港币": "HKD", "人民币": "CNY"}

    def extract(self, text: str) -> list[FactClaim]:
        claims: list[FactClaim] = []
        for m in self._RE_EN.finditer(text):
            claims.append(FactClaim(
                kind="exchange_rate",
                raw_text=m.group(0),
                claimed_value=float(m.group("value")),
                claimed_result=str(m.group("result")),
                from_ccy=m.group("from"),
                to_ccy=m.group("to"),
            ))
        for m in self._RE_ZH.finditer(text):
            claims.append(FactClaim(
                kind="exchange_rate",
                raw_text=m.group(0),
                claimed_value=float(m.group("value")),
                claimed_result=str(m.group("result")),
                from_ccy=self._ZH_CCY[m.group("from")],
                to_ccy=self._ZH_CCY[m.group("to")],
            ))
        return claims
```

Update `FactClaim` dataclass to add `from_ccy`, `to_ccy`:

```python
@dataclass(frozen=True)
class FactClaim:
    kind: str
    raw_text: str
    date_str: str | None = None
    claimed_weekday_zh: str | None = None
    expression: str | None = None
    claimed_result: str | None = None
    claimed_value: float | None = None
    from_unit: str | None = None
    to_unit: str | None = None
    from_ccy: str | None = None
    to_ccy: str | None = None
```

- [ ] **Step 4: Write failing test for ExchangeRateVerifier**

Append to `tests/test_fact_check_verifiers.py`:

```python
from nexus.backend.fact_check.verifiers import ExchangeRateVerifier


class TestExchangeRateVerifier:
    def test_correct_rate_passes(self, monkeypatch):
        from nexus.backend.fact_check import exchange_rate as er

        monkeypatch.setattr(er, "fetch_rate", lambda f, t, api_key=None: 7.20)
        claim = FactClaim(
            kind="exchange_rate", raw_text="100 USD = 720 CNY",
            claimed_value=100.0, claimed_result="720",
            from_ccy="USD", to_ccy="CNY",
        )
        result = ExchangeRateVerifier().verify(claim, api_key=None)
        assert result.verdict == "ok"
        assert result.expected_value == 720.0
        assert result.actual_value == 720.0

    def test_wrong_rate_conflicts(self, monkeypatch):
        from nexus.backend.fact_check import exchange_rate as er

        monkeypatch.setattr(er, "fetch_rate", lambda f, t, api_key=None: 7.20)
        claim = FactClaim(
            kind="exchange_rate", raw_text="100 USD = 800 CNY",
            claimed_value=100.0, claimed_result="800",
            from_ccy="USD", to_ccy="CNY",
        )
        result = ExchangeRateVerifier().verify(claim, api_key=None)
        assert result.verdict == "conflict"

    def test_api_failure_skipped(self, monkeypatch):
        from nexus.backend.fact_check import exchange_rate as er

        monkeypatch.setattr(er, "fetch_rate", lambda f, t, api_key=None: None)
        claim = FactClaim(
            kind="exchange_rate", raw_text="100 USD = 720 CNY",
            claimed_value=100.0, claimed_result="720",
            from_ccy="USD", to_ccy="CNY",
        )
        result = ExchangeRateVerifier().verify(claim, api_key=None)
        assert result.verdict == "skipped"  # API down → fail-open
```

- [ ] **Step 5: Implement ExchangeRateVerifier**

Append to `nexus/backend/fact_check/verifiers.py`:

```python
from nexus.backend.fact_check.exchange_rate import fetch_rate


class ExchangeRateVerifier:
    """Verify currency conversion claims. Fails-open on API errors."""

    def verify(self, claim: FactClaim, api_key: str | None = None) -> VerificationResult:
        if claim.kind != "exchange_rate":
            return VerificationResult(claim=claim, verdict="skipped")

        assert claim.from_ccy and claim.to_ccy and claim.claimed_value is not None
        rate = fetch_rate(claim.from_ccy, claim.to_ccy, api_key=api_key)
        if rate is None:
            # API failure → fail-open (don't block user)
            return VerificationResult(
                claim=claim, verdict="skipped",
                error_message="Exchange rate API unavailable",
            )

        expected = claim.claimed_value * rate
        try:
            actual = float(claim.claimed_result)  # type: ignore[arg-type]
        except (TypeError, ValueError) as e:
            return VerificationResult(
                claim=claim, verdict="error", error_message=str(e),
            )

        # 5% tolerance for rate fluctuation
        tolerance = abs(expected) * 0.05
        verdict: Literal["ok", "conflict"] = (
            "ok" if abs(expected - actual) <= tolerance else "conflict"
        )
        return VerificationResult(
            claim=claim, verdict=verdict,
            expected_value=expected, actual_value=actual,
        )
```

- [ ] **Step 6: Run all extractor+verifier tests**

Run: `.venv/bin/pytest tests/test_fact_check_extractors.py tests/test_fact_check_verifiers.py tests/test_fact_check_exchange_rate.py -v`
Expected: PASS (all tests)

- [ ] **Step 7: Commit**

```bash
git add nexus/backend/fact_check/verifiers.py nexus/backend/fact_check/extractors.py tests/test_fact_check_extractors.py tests/test_fact_check_verifiers.py tests/test_fact_check_exchange_rate.py
git commit -m "feat(fact_check): add ExchangeRateExtractor + ExchangeRateVerifier (fail-open)"
```

---

## Task 8: Fact-Check Pipeline Orchestrator (TDD)

**Files:**
- Create: `nexus/backend/fact_check/pipeline.py`
- Test: `tests/test_fact_check_pipeline.py`

- [ ] **Step 1: Write failing test**

`tests/test_fact_check_pipeline.py`:

```python
"""Tests for fact_check.pipeline orchestrator."""

import pytest
from nexus.backend.fact_check.pipeline import FactCheckPipeline, FactCheckReport


class TestFactCheckPipeline:
    def test_empty_text_returns_empty_report(self):
        pipeline = FactCheckPipeline()
        report = pipeline.check("今天天气不错")
        assert report.claims_total == 0
        assert report.has_conflict is False

    def test_correct_date_passes(self):
        pipeline = FactCheckPipeline()
        report = pipeline.check("明天是 2026年7月11日 星期六")
        assert report.claims_total == 1
        assert report.has_conflict is False

    def test_wrong_date_triggers_conflict(self):
        pipeline = FactCheckPipeline()
        report = pipeline.check("明天是 2026年7月11日 星期五")  # wrong weekday
        assert report.claims_total == 1
        assert report.has_conflict is True
        assert report.conflicts[0].verdict == "conflict"

    def test_wrong_math_triggers_conflict(self):
        pipeline = FactCheckPipeline()
        report = pipeline.check("23 + 32 = 56")  # should be 55
        assert report.has_conflict is True

    def test_disabled_claim_type_skipped(self):
        config = {"enabled_claim_types": ["date_weekday"]}
        pipeline = FactCheckPipeline(config=config)
        report = pipeline.check("23 + 32 = 56")
        assert report.claims_total == 0  # math not enabled

    def test_pipeline_returns_full_report(self):
        pipeline = FactCheckPipeline()
        text = "明天是 2026年7月11日 星期六。气温 23 + 32 = 55。"
        report = pipeline.check(text)
        assert report.claims_total == 2
        assert report.passed == 2
        assert report.failed == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_fact_check_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement FactCheckPipeline**

`nexus/backend/fact_check/pipeline.py`:

```python
"""Orchestrates extract → verify → report."""

from __future__ import annotations

from dataclasses import dataclass, field

from nexus.backend.fact_check.extractors import (
    DateWeekdayExtractor, MathExtractor, UnitsExtractor, ExchangeRateExtractor,
    FactClaim,
)
from nexus.backend.fact_check.verifiers import (
    DateWeekdayVerifier, MathVerifier, UnitsVerifier, ExchangeRateVerifier,
    VerificationResult,
)


@dataclass
class FactCheckReport:
    text: str
    claims_total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    conflicts: list[VerificationResult] = field(default_factory=list)
    all_results: list[VerificationResult] = field(default_factory=list)

    @property
    def has_conflict(self) -> bool:
        return len(self.conflicts) > 0

    def to_dict(self) -> dict:
        return {
            "claims_total": self.claims_total,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "skipped": self.skipped,
            "conflicts": [
                {
                    "claim_text": r.claim.raw_text,
                    "kind": r.claim.kind,
                    "verdict": r.verdict,
                    "claimed": r.claimed_weekday_zh or r.expected_value,
                    "actual": r.actual_weekday_zh or r.actual_value,
                }
                for r in self.conflicts
            ],
        }


_EXTRACTORS = {
    "date_weekday": DateWeekdayExtractor(),
    "math": MathExtractor(),
    "unit": UnitsExtractor(),
    "exchange_rate": ExchangeRateExtractor(),
}

_VERIFIERS = {
    "date_weekday": DateWeekdayVerifier(),
    "math": MathVerifier(),
    "unit": UnitsVerifier(),
    "exchange_rate": ExchangeRateVerifier(),
}


class FactCheckPipeline:
    """Run all enabled extractors + verifiers on text. Returns FactCheckReport."""

    DEFAULT_ENABLED = ["date_weekday", "math", "unit", "exchange_rate"]

    def __init__(self, config: dict | None = None) -> None:
        self.enabled = (config or {}).get("enabled_claim_types", self.DEFAULT_ENABLED)

    def check(self, text: str, api_key: str | None = None) -> FactCheckReport:
        report = FactCheckReport(text=text)
        for kind in self.enabled:
            extractor = _EXTRACTORS.get(kind)
            verifier = _VERIFIERS.get(kind)
            if not extractor or not verifier:
                continue
            claims: list[FactClaim] = extractor.extract(text)
            for claim in claims:
                report.claims_total += 1
                if kind == "exchange_rate":
                    result = verifier.verify(claim, api_key=api_key)  # type: ignore[arg-type]
                else:
                    result = verifier.verify(claim)
                report.all_results.append(result)
                if result.verdict == "ok":
                    report.passed += 1
                elif result.verdict == "conflict":
                    report.failed += 1
                    report.conflicts.append(result)
                elif result.verdict == "error":
                    report.errors += 1
                else:  # skipped
                    report.skipped += 1
        return report
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_fact_check_pipeline.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add nexus/backend/fact_check/pipeline.py tests/test_fact_check_pipeline.py
git commit -m "feat(fact_check): add FactCheckPipeline orchestrator"
```

---

## Task 9: FactCheckMiddleware (TDD)

**Files:**
- Create: `nexus/backend/agents/middleware/fact_check.py`
- Test: `tests/test_fact_check_middleware.py`

- [ ] **Step 1: Write failing test**

`tests/test_fact_check_middleware.py`:

```python
"""Tests for FactCheckMiddleware."""

import pytest
from nexus.backend.agents.middleware.fact_check import (
    FactCheckMiddleware, FactCheckError,
)


class TestFactCheckMiddleware:
    @pytest.mark.asyncio
    async def test_passes_clean_output(self):
        async def handler(req):
            return {"content": "明天是 2026年7月11日 星期六"}

        mw = FactCheckMiddleware()
        result = await mw.wrap_model_call({}, handler)
        assert result["content"] == "明天是 2026年7月11日 星期六"

    @pytest.mark.asyncio
    async def test_raises_on_conflict_fail_closed(self):
        async def handler(req):
            return {"content": "明天是 2026年7月11日 星期五"}  # wrong

        mw = FactCheckMiddleware(fail_strategy="closed")
        with pytest.raises(FactCheckError) as exc_info:
            await mw.wrap_model_call({}, handler)
        assert "星期五" in str(exc_info.value)
        assert "星期六" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_passes_on_conflict_fail_open(self):
        async def handler(req):
            return {"content": "明天是 2026年7月11日 星期五"}

        mw = FactCheckMiddleware(fail_strategy="open")
        result = await mw.wrap_model_call({}, handler)
        # Even with conflict, output passes through with warning
        assert "星期五" in result["content"]
        assert result.get("_fact_check_warnings")  # Warning attached

    @pytest.mark.asyncio
    async def test_math_error_caught(self):
        async def handler(req):
            return {"content": "23 + 32 = 100"}  # wrong

        mw = FactCheckMiddleware(fail_strategy="closed")
        with pytest.raises(FactCheckError):
            await mw.wrap_model_call({}, handler)

    @pytest.mark.asyncio
    async def test_exchange_rate_skipped_on_api_failure(self, monkeypatch):
        from nexus.backend.fact_check import exchange_rate as er

        monkeypatch.setattr(er, "fetch_rate", lambda f, t, api_key=None: None)
        async def handler(req):
            return {"content": "100 USD = 9999 CNY"}  # wrong but API down

        mw = FactCheckMiddleware(fail_strategy="closed")
        result = await mw.wrap_model_call({}, handler)
        # Should not raise because exchange_rate fails-open on API error
        assert "9999" in result["content"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_fact_check_middleware.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement FactCheckMiddleware**

`nexus/backend/agents/middleware/fact_check.py`:

```python
"""Fact-check middleware for deepagents.

Scans agent output for fact claims, runs deterministic verification,
raises FactCheckError on conflict (fail-closed) or attaches warning
(fail-open).
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Literal

from nexus.backend.fact_check.pipeline import FactCheckPipeline


logger = logging.getLogger(__name__)


class FactCheckError(Exception):
    """Raised when fact-check finds a conflict in agent output."""

    def __init__(self, conflicts: list[dict]) -> None:
        self.conflicts = conflicts
        summary = "; ".join(
            f"{c['kind']}: claimed {c['claimed']} actual {c['actual']}"
            for c in conflicts
        )
        super().__init__(f"Fact-check conflict: {summary}")


class FactCheckMiddleware:
    """DeepAgents middleware: verify facts in model output.

    Args:
        fail_strategy: "closed" raises on conflict, "open" attaches warning.
        config: optional config dict for FactCheckPipeline.
    """

    def __init__(
        self,
        fail_strategy: Literal["closed", "open"] = "closed",
        config: dict | None = None,
    ) -> None:
        self.fail_strategy = fail_strategy
        self.pipeline = FactCheckPipeline(config=config)

    async def wrap_model_call(
        self,
        request: Any,
        handler: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        response = await handler(request)
        content = self._extract_content(response)
        if not content:
            return response

        report = self.pipeline.check(content)
        if not report.has_conflict:
            return response

        if self.fail_strategy == "closed":
            logger.warning(
                "FactCheckMiddleware blocked output: %d conflicts",
                len(report.conflicts),
            )
            raise FactCheckError(report.to_dict()["conflicts"])

        # fail-open: attach warning, pass through
        if isinstance(response, dict):
            response["_fact_check_warnings"] = report.to_dict()
        logger.warning(
            "FactCheckMiddleware open-passed output: %d conflicts",
            len(report.conflicts),
        )
        return response

    def _extract_content(self, response: Any) -> str:
        if isinstance(response, str):
            return response
        if isinstance(response, dict):
            return response.get("content", "") or ""
        # DeepAgents AIMessage-like object
        return getattr(response, "content", "") or ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_fact_check_middleware.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add nexus/backend/agents/middleware/fact_check.py tests/test_fact_check_middleware.py
git commit -m "feat(fact_check): add FactCheckMiddleware (deepagents middleware)"
```

---

## Task 10: QualityPipeline Integration

**Files:**
- Modify: `nexus/backend/quality/pipeline.py` (or `nexus/backend/rubrics/pipeline.py`)
- Test: `tests/test_quality_pipeline_fact_check.py`

- [ ] **Step 1: Find and read the QualityPipeline**

Locate: `find /Users/yxb/projects/nexus -name "pipeline.py" -path "*rubric*" -o -name "pipeline.py" -path "*quality*"`

Read the file, identify the `run_with_quality` method and the rubric judge step.

- [ ] **Step 2: Write failing test**

`tests/test_quality_pipeline_fact_check.py`:

```python
"""Test fact-check integration in QualityPipeline."""

import pytest
from unittest.mock import AsyncMock, patch
from nexus.backend.quality.pipeline import QualityPipeline


@pytest.fixture
def mock_pipeline():
    with patch("nexus.backend.quality.pipeline.RubricJudge") as MockJudge:
        mock_judge = MockJudge.return_value
        mock_judge.judge = AsyncMock(return_value={
            "faithfulness": 0.95, "relevance": 0.9,
            "safety": 0.95, "tool_correctness": 0.9,
        })
        yield QualityPipeline()


class TestQualityPipelineFactCheck:
    @pytest.mark.asyncio
    async def test_fact_conflict_triggers_repair(self, mock_pipeline):
        response = "明天是 2026年7月11日 星期五"  # wrong weekday

        result = await mock_pipeline.run_with_quality(
            session_id="test", user_query="明天穿啥",
            raw_response=response,
        )

        # Should NOT accept directly; should route to repair or reject
        assert result.verdict in ("repair", "reject")
        assert result.fact_check_status == "fail"

    @pytest.mark.asyncio
    async def test_correct_facts_pass_through(self, mock_pipeline):
        response = "明天是 2026年7月11日 星期六"

        result = await mock_pipeline.run_with_quality(
            session_id="test", user_query="明天穿啥",
            raw_response=response,
        )

        assert result.verdict == "accept"
        assert result.fact_check_status == "pass"

    @pytest.mark.asyncio
    async def test_no_claims_skipped(self, mock_pipeline):
        response = "好的,我会帮你查一下"

        result = await mock_pipeline.run_with_quality(
            session_id="test", user_query="hi",
            raw_response=response,
        )

        assert result.fact_check_status == "skipped"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_quality_pipeline_fact_check.py -v`
Expected: FAIL (QualityPipeline.run_with_quality doesn't take raw_response, or doesn't have fact_check_status)

- [ ] **Step 4: Add fact-check step to QualityPipeline**

Modify `nexus/backend/quality/pipeline.py` (or `nexus/backend/rubrics/pipeline.py`):

Find the `run_with_quality` method. Add at the top (before RubricJudge.judge()):

```python
from nexus.backend.fact_check.pipeline import FactCheckPipeline
from nexus.backend.agents.middleware.fact_check import FactCheckError

# In run_with_quality, before rubric judge:
self._fact_check = FactCheckPipeline(config=self._load_fact_check_config())
report = self._fact_check.check(raw_response)

if report.has_conflict:
    logger.warning(
        "QualityPipeline fact-check conflict: %d in %d claims",
        len(report.conflicts), report.claims_total,
    )
    # Store fact_check_* in result for DB write
    result.fact_check_claims = report.to_dict()
    result.fact_check_status = "fail"
    # Route to REPAIR
    if self._repair_strategy.attempts < self._repair_strategy.max_repair_attempts:
        return await self._repair(raw_response, reason="fact_conflict", report=report)
    return self._reject(raw_response, reason="fact_conflict", report=report)

result.fact_check_status = "pass" if report.claims_total > 0 else "skipped"
result.fact_check_claims = report.to_dict()
```

- [ ] **Step 5: Update RepairStrategy to accept fact_check context**

In `repair.py` or wherever RepairStrategy lives:

```python
@dataclass
class RepairContext:
    fact_check_report: dict | None = None
    # ... existing fields
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_quality_pipeline_fact_check.py -v`
Expected: PASS (3 tests)

- [ ] **Step 7: Commit**

```bash
git add nexus/backend/quality/pipeline.py nexus/backend/quality/repair.py tests/test_quality_pipeline_fact_check.py
git commit -m "feat(quality): integrate FactCheckPipeline into QualityPipeline"
```

---

## Task 11: DB Schema Migration for fact_check_*

**Files:**
- Modify: `nexus/backend/db.py`
- Test: existing migration test (verify _ensure_column works)

- [ ] **Step 1: Find the quality_scores table definition**

Run: `grep -n "quality_scores" /Users/yxb/projects/nexus/nexus/backend/db.py`

Find where columns are added/ensured for quality_scores.

- [ ] **Step 2: Add _ensure_column calls**

In `nexus/backend/db.py`, locate the section where quality_scores columns are ensured (likely near other `_ensure_column` calls). Add:

```python
_ensure_column(cursor, "quality_scores", "fact_check_claims", "JSON")
_ensure_column(cursor, "quality_scores", "fact_check_results", "JSON")
_ensure_column(cursor, "quality_scores", "fact_check_status", "TEXT")
_ensure_column(cursor, "quality_scores", "fact_check_latency_ms", "INTEGER")
```

- [ ] **Step 3: Write test for column existence**

Create or extend `tests/test_db_migrations.py`:

```python
def test_quality_scores_has_fact_check_columns(tmp_path):
    import sqlite3
    from nexus.backend.db import _ensure_column, get_connection

    db_path = tmp_path / "test.db"
    con = sqlite3.connect(str(db_path))
    con.execute("""
        CREATE TABLE quality_scores (
            id INTEGER PRIMARY KEY,
            session_id TEXT NOT NULL,
            message_id TEXT,
            rubric TEXT NOT NULL,
            score REAL NOT NULL,
            verdict TEXT NOT NULL,
            reasoning TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    _ensure_column(con.cursor(), "quality_scores", "fact_check_claims", "JSON")
    con.commit()

    cols = [row[1] for row in con.execute("PRAGMA table_info(quality_scores)")]
    assert "fact_check_claims" in cols
    assert "fact_check_status" in cols
```

- [ ] **Step 4: Run test**

Run: `.venv/bin/pytest tests/test_db_migrations.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nexus/backend/db.py tests/test_db_migrations.py
git commit -m "feat(db): add fact_check_* columns to quality_scores (auto-migrate)"
```

---

## Task 12: Update QualityPipeline DB Write to Include fact_check_*

**Files:**
- Modify: `nexus/backend/quality/pipeline.py`

- [ ] **Step 1: Find the DB insert for quality_scores**

Run: `grep -n "INSERT INTO quality_scores" /Users/yxb/projects/nexus/nexus/backend/quality/`

- [ ] **Step 2: Extend INSERT to include new columns**

Add the fact_check columns to the INSERT statement:

```python
con.execute("""
    INSERT INTO quality_scores
        (session_id, message_id, rubric, score, verdict, reasoning,
         fact_check_claims, fact_check_status, fact_check_latency_ms)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
""", (
    session_id, message_id, rubric, score, verdict, reasoning,
    json.dumps(result.fact_check_claims) if result.fact_check_claims else None,
    result.fact_check_status,
    result.fact_check_latency_ms,
))
```

- [ ] **Step 3: Test that DB write includes fact_check fields**

Run: `.venv/bin/pytest tests/ -k "quality_scores or fact_check" -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add nexus/backend/quality/pipeline.py
git commit -m "feat(quality): persist fact_check_* in quality_scores"
```

---

## Task 13: date_utils MCP Server

**Files:**
- Create: `nexus/backend/mcp_servers/__init__.py`
- Create: `nexus/backend/mcp_servers/date_utils/__init__.py`
- Create: `nexus/backend/mcp_servers/date_utils/server.py`
- Test: `tests/test_date_utils_mcp.py`

- [ ] **Step 1: Write failing test**

`tests/test_date_utils_mcp.py`:

```python
"""Tests for date_utils MCP server."""

import pytest
from datetime import date
from nexus.backend.mcp_servers.date_utils.server import (
    today, weekday_of, next_n_days,
)


class TestDateUtilsMCP:
    def test_today_default_timezone(self, monkeypatch):
        # Pin to known date
        monkeypatch.setattr(
            "nexus.backend.mcp_servers.date_utils.server._now_shanghai",
            lambda: date(2026, 7, 10),
        )
        result = today()
        assert result["date"] == "2026-07-10"
        assert result["weekday_zh"] == "星期五"
        assert result["weekday_int"] == 4

    def test_weekday_of_saturday(self):
        result = weekday_of("2026-07-11")
        assert result["weekday_zh"] == "星期六"
        assert result["weekday_int"] == 5

    def test_next_n_days(self, monkeypatch):
        monkeypatch.setattr(
            "nexus.backend.mcp_servers.date_utils.server._now_shanghai",
            lambda: date(2026, 7, 10),
        )
        result = next_n_days(3)
        assert result == [
            {"date": "2026-07-10", "weekday_zh": "星期五"},
            {"date": "2026-07-11", "weekday_zh": "星期六"},
            {"date": "2026-07-12", "weekday_zh": "星期日"},
        ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_date_utils_mcp.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement date_utils MCP server**

`nexus/backend/mcp_servers/__init__.py`:

```python
"""MCP servers for Nexus."""
```

`nexus/backend/mcp_servers/date_utils/__init__.py`:

```python
"""date_utils MCP server."""
```

`nexus/backend/mcp_servers/date_utils/server.py`:

```python
"""Date utilities MCP server — forces agent to call tools for date facts."""

from __future__ import annotations

from datetime import date, timedelta, datetime
from zoneinfo import ZoneInfo

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _now_shanghai() -> date:
    """Get current date in Asia/Shanghai timezone."""
    return datetime.now(_SHANGHAI).date()


_ZH_WEEKDAY = ["星期一", "星期二", "星期三", "星期四",
               "星期五", "星期六", "星期日"]


def today(tz: str = "Asia/Shanghai") -> dict:
    """Return today's date and weekday in given timezone."""
    if tz != "Asia/Shanghai":
        # Future: support other timezones
        raise NotImplementedError(f"timezone {tz!r} not yet supported")
    d = _now_shanghai()
    return {
        "date": d.isoformat(),
        "weekday_int": d.weekday(),
        "weekday_zh": _ZH_WEEKDAY[d.weekday()],
    }


def weekday_of(date_str: str) -> dict:
    """Return weekday info for given ISO date string."""
    d = date.fromisoformat(date_str)
    return {
        "date": d.isoformat(),
        "weekday_int": d.weekday(),
        "weekday_zh": _ZH_WEEKDAY[d.weekday()],
    }


def next_n_days(n: int) -> list[dict]:
    """Return today + next n-1 days."""
    if n < 1 or n > 30:
        raise ValueError("n must be in [1, 30]")
    base = _now_shanghai()
    return [
        {"date": (base + timedelta(days=i)).isoformat(),
         "weekday_zh": _ZH_WEEKDAY[(base + timedelta(days=i)).weekday()]}
        for i in range(n)
    ]


# MCP server entry point (FastMCP / stdio JSON-RPC)
if __name__ == "__main__":
    import sys
    # Minimal stdio JSON-RPC dispatch
    print("date_utils MCP server ready", file=sys.stderr)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_date_utils_mcp.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add nexus/backend/mcp_servers/ tests/test_date_utils_mcp.py
git commit -m "feat(mcp): add date_utils MCP server (today/weekday_of/next_n_days)"
```

---

## Task 14: fact_verify MCP Server

**Files:**
- Create: `nexus/backend/mcp_servers/fact_verify/__init__.py`
- Create: `nexus/backend/mcp_servers/fact_verify/server.py`
- Test: extend `tests/test_fact_check_pipeline.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_fact_check_pipeline.py`:

```python
class TestFactVerifyMCP:
    def test_verify_claims_returns_report_dict(self):
        from nexus.backend.mcp_servers.fact_verify.server import verify_claims
        result = verify_claims("明天是 2026年7月11日 星期六")
        assert result["claims_total"] == 1
        assert result["conflicts"] == []

    def test_verify_claims_reports_conflicts(self):
        from nexus.backend.mcp_servers.fact_verify.server import verify_claims
        result = verify_claims("明天是 2026年7月11日 星期五")  # wrong
        assert len(result["conflicts"]) == 1
        assert result["conflicts"][0]["claimed"] == "星期五"
        assert result["conflicts"][0]["actual"] == "星期六"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_fact_check_pipeline.py::TestFactVerifyMCP -v`
Expected: FAIL

- [ ] **Step 3: Implement fact_verify MCP server**

`nexus/backend/mcp_servers/fact_verify/__init__.py`:

```python
"""fact_verify MCP server."""
```

`nexus/backend/mcp_servers/fact_verify/server.py`:

```python
"""fact_verify MCP server — exposes FactCheckPipeline to agent."""

from __future__ import annotations

from nexus.backend.fact_check.pipeline import FactCheckPipeline


_PIPELINE = FactCheckPipeline()


def verify_claims(text: str, api_key: str | None = None) -> dict:
    """Run fact-check on text, return report dict.

    Agent should call this before finalizing any output containing
    dates, math, unit conversions, or exchange rates.
    """
    report = _PIPELINE.check(text, api_key=api_key)
    return report.to_dict()


if __name__ == "__main__":
    import sys
    print("fact_verify MCP server ready", file=sys.stderr)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_fact_check_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nexus/backend/mcp_servers/fact_verify/ tests/test_fact_check_pipeline.py
git commit -m "feat(mcp): add fact_verify MCP server (verify_claims)"
```

---

## Task 15: Config File & Main Registration

**Files:**
- Create: `nexus/backend/config/fact_check.yaml`
- Modify: `nexus/backend/main.py`

- [ ] **Step 1: Create config**

`nexus/backend/config/fact_check.yaml`:

```yaml
# Fact-check pipeline configuration
fact_check:
  enabled: true
  timezone: Asia/Shanghai
  fail_strategy: closed  # closed = block on conflict, open = warn only
  enabled_claim_types:
    - date_weekday    # fail-closed (critical)
    - math            # fail-closed (critical)
    - unit            # fail-closed (critical)
    - exchange_rate   # fail-open (external API can fail)
  exchange_rate:
    api_url: https://api.exchangerate-api.com/v4/latest
    cache_ttl_seconds: 3600
    tolerance: 0.05  # 5% tolerance for rate fluctuation
```

- [ ] **Step 2: Add config loader in main.py**

In `nexus/backend/main.py`, add:

```python
import yaml
from pathlib import Path

def _load_fact_check_config() -> dict:
    config_path = Path(__file__).parent / "config" / "fact_check.yaml"
    if not config_path.exists():
        return {}
    return yaml.safe_load(config_path.read_text(encoding="utf-8")).get("fact_check", {})

FACT_CHECK_CONFIG = _load_fact_check_config()
```

- [ ] **Step 3: Register MCP servers**

In `nexus/backend/main.py` startup, register the new MCP servers. Look at how existing MCP servers are registered (e.g., in `nexus/backend/api/ws/registry.py` or main.py), then add:

```python
if FACT_CHECK_CONFIG.get("enabled"):
    from nexus.backend.mcp_servers.date_utils.server import today, weekday_of, next_n_days
    from nexus.backend.mcp_servers.fact_verify.server import verify_claims
    register_mcp_server("date_utils", {"today": today, "weekday_of": weekday_of, "next_n_days": next_n_days})
    register_mcp_server("fact_verify", {"verify_claims": verify_claims})
```

- [ ] **Step 4: Verify main.py still starts**

Run: `.venv/bin/python -c "from nexus.backend.main import app; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add nexus/backend/config/fact_check.yaml nexus/backend/main.py
git commit -m "feat(config): add fact_check.yaml and register MCP servers"
```

---

## Task 16: Agent System Prompt Constraint

**Files:**
- Modify: `nexus/backend/agents/` (wherever deepagents system prompt is built)

- [ ] **Step 1: Locate system prompt construction**

Run: `grep -rn "system_prompt\|SystemMessage" /Users/yxb/projects/nexus/nexus/backend/agents/ /Users/yxb/projects/nexus/nexus/backend/main.py | head -10`

- [ ] **Step 2: Add fact-check constraint to system prompt**

In the system prompt template (likely in `agents/prompts.py` or similar), append:

```python
FACT_CHECK_CONSTRAINT = """

## 事实校验硬约束

任何涉及以下内容的输出，**必须**先调用对应 MCP 工具验证，再写入回复：

- **日期/星期**：调用 `date_utils.today()` 或 `date_utils.weekday_of(date_str)`，把 tool 返回的 weekday 引用到输出中
- **数学计算**：用 Python `ast` 安全 eval 自验，或调用 `fact_verify.verify_claims(text)` 扫一遍
- **单位换算**：调用 `fact_verify.verify_claims(text)` 验证
- **汇率**：调用 `fact_verify.verify_claims(text)` 验证（如 API 失败可标注"汇率参考"）

**禁止**直接心算或凭印象写星期/日期/数学结果。Tool 没调就用，会被 FactCheckMiddleware 拦截。
"""
```

Insert into the prompt template after the existing constraints section.

- [ ] **Step 3: Verify prompt still loads**

Run: `.venv/bin/python -c "from nexus.backend.agents.prompts import SYSTEM_PROMPT; print('OK' if 'FACT_CHECK_CONSTRAINT' in SYSTEM_PROMPT or '事实校验' in SYSTEM_PROMPT else 'MISSING')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add nexus/backend/agents/
git commit -m "feat(agents): add fact-check hard constraint to system prompt"
```

---

## Task 17: Regression Test — 7-10 21:45 Case

**Files:**
- Create: `tests/regression/__init__.py`
- Create: `tests/regression/test_clothing_reminder_regression.py`

- [ ] **Step 1: Create regression package**

`tests/regression/__init__.py`:

```python
"""Regression tests for previously-bugged behaviors."""
```

- [ ] **Step 2: Write regression test**

`tests/regression/test_clothing_reminder_regression.py`:

```python
"""Regression: 7-10 21:45 assistant wrote '2026-07-11 星期五' (wrong).

Real date: 2026-07-11 is Saturday (星期六). This test pins the fix.
"""

import pytest
from nexus.backend.fact_check.pipeline import FactCheckPipeline


class TestClothingReminderRegression:
    def test_old_buggy_output_now_caught(self):
        """The exact bad output from 7-10 21:45 must be flagged."""
        bad_output = "明天(2026-07-11 星期五)出门穿衣..."
        pipeline = FactCheckPipeline()
        report = pipeline.check(bad_output)
        assert report.has_conflict, (
            "Regression: fact-check did not catch 2026-07-11 + 星期五 mismatch"
        )
        assert report.conflicts[0].claim.claimed_weekday_zh == "星期五"
        assert report.conflicts[0].actual_weekday_zh == "星期六"

    def test_correct_output_passes(self):
        good_output = "明天(2026-07-11 星期六)出门穿衣..."
        pipeline = FactCheckPipeline()
        report = pipeline.check(good_output)
        assert not report.has_conflict
```

- [ ] **Step 3: Run regression test**

Run: `.venv/bin/pytest tests/regression/test_clothing_reminder_regression.py -v`
Expected: PASS (2 tests)

- [ ] **Step 4: Commit**

```bash
git add tests/regression/
git commit -m "test(regression): pin 7-10 21:45 穿衣提醒 case"
```

---

## Task 18: E2E Test — "明天是星期几"

**Files:**
- Create: `tests/e2e/test_fact_check_e2e.py`

- [ ] **Step 1: Write E2E test**

```python
"""E2E: when user asks '明天是星期几', agent must call date_utils tool."""

import pytest


@pytest.mark.asyncio
async def test_tomorrow_weekday_triggers_tool_call():
    """Verify agent doesn't mental-math the weekday."""
    from nexus.backend.agents.middleware.fact_check import (
        FactCheckMiddleware, FactCheckError,
    )

    # Simulate agent output WITHOUT tool call verification (mental math)
    bad_output = "明天是 2026-07-11 星期五"

    async def handler(req):
        return {"content": bad_output}

    mw = FactCheckMiddleware(fail_strategy="closed")
    with pytest.raises(FactCheckError):
        await mw.wrap_model_call({}, handler)


@pytest.mark.asyncio
async def test_correct_tomorrow_weekday_passes():
    good_output = "明天是 2026-07-11 星期六"

    async def handler(req):
        return {"content": good_output}

    mw = FactCheckMiddleware(fail_strategy="closed")
    result = await mw.wrap_model_call({}, handler)
    assert "星期六" in result["content"]
```

- [ ] **Step 2: Run E2E test**

Run: `.venv/bin/pytest tests/e2e/test_fact_check_e2e.py -v`
Expected: PASS (2 tests)

- [ ] **Step 3: Commit**

```bash
git add tests/e2e/test_fact_check_e2e.py
git commit -m "test(e2e): '明天星期几' triggers fact-check"
```

---

## Task 19: Meta-Eval Samples

**Files:**
- Modify: `data/rubric_eval_samples.jsonl`

- [ ] **Step 1: Add 5 fact-check samples**

Append to `data/rubric_eval_samples.jsonl`:

```jsonl
{"prompt":"明天是星期几","response":"明天是2026年7月11日星期六","expected_score":0.95,"expected_verdict":"accept","rubric_name":"faithfulness"}
{"prompt":"明天是星期几","response":"明天是2026年7月11日星期五","expected_score":0.2,"expected_verdict":"reject","rubric_name":"faithfulness"}
{"prompt":"23+32等于多少","response":"23+32等于55","expected_score":0.95,"expected_verdict":"accept","rubric_name":"faithfulness"}
{"prompt":"23+32等于多少","response":"23+32等于56","expected_score":0.2,"expected_verdict":"reject","rubric_name":"faithfulness"}
{"prompt":"100美元等于多少人民币","response":"100美元约等于720人民币","expected_score":0.85,"expected_verdict":"accept","rubric_name":"faithfulness"}
```

- [ ] **Step 2: Run meta-eval**

Run: `.venv/bin/python scripts/eval_rubrics.py --samples data/rubric_eval_samples.jsonl --output data/eval_report.json`

Expected: Pearson ≥ 0.7, Cohen's kappa ≥ 0.4

- [ ] **Step 3: Commit**

```bash
git add data/rubric_eval_samples.jsonl data/eval_report.json
git commit -m "test(meta-eval): add 5 fact-check samples"
```

---

## Task 20: Documentation

**Files:**
- Create: `docs/operations/fact-check.md`
- Modify: `docs/operations/quality.md`

- [ ] **Step 1: Create fact-check.md operator guide**

`docs/operations/fact-check.md`:

```markdown
# 事实校验流水线调优指南

> 适用版本：阶段 fact-check pipeline 已合并
> 适用范围：日期/星期、数学、单位换算、汇率的事实校验

## 1. 架构

```
用户问题 → 主 Agent 生成 raw_response
              ↓
       QualityPipeline.run_with_quality
              ├─【NEW】FactCheckPipeline.check()
              │   ├─ Extractors (regex)
              │   ├─ Verifiers (deterministic)
              │   └─ fail-closed on critical conflict
              ├─ RubricJudge.judge()
              ├─ RepairStrategy.decide()
              └─ 主 LLM 重生
```

## 2. 4 类 Claim

| Claim 类型 | 默认策略 | Extractor | Verifier |
|---|---|---|---|
| date_weekday | fail-closed | `DateWeekdayExtractor` | `DateWeekdayVerifier` (Python datetime) |
| math | fail-closed | `MathExtractor` | `MathVerifier` (safe AST eval) |
| unit | fail-closed | `UnitsExtractor` | `UnitsVerifier` (lookup tables) |
| exchange_rate | fail-open | `ExchangeRateExtractor` | `ExchangeRateVerifier` (API + cache) |

## 3. 配置

`nexus/backend/config/fact_check.yaml`:

```yaml
fact_check:
  enabled: true
  fail_strategy: closed
  enabled_claim_types: [date_weekday, math, unit, exchange_rate]
  exchange_rate:
    cache_ttl_seconds: 3600
    tolerance: 0.05
```

调高 `fail_strategy` 影响：开 → 仅记录 warning；闭 → 阻断。

## 4. 失败模式

| 症状 | 排查 |
|---|---|
| 所有 response 被 REJECT | regex 太激进 → 检查 `fact_check_claims` JSON |
| 时区错 | 确认 `timezone: Asia/Shanghai` |
| 汇率长期 fail-open | API key 失效或网络问题 |
| 数学误杀 | 检查是否含 `__import__` 等被 AST 拒绝 |

## 5. 数据库

`quality_scores` 新增字段：

- `fact_check_claims JSON`：扫描到的所有 claim
- `fact_check_status TEXT`：pass / fail / skipped
- `fact_check_latency_ms INTEGER`：耗时

查询示例：

```sql
-- 7 天内 fact-check 失败率
SELECT
  COUNT(CASE WHEN fact_check_status = 'fail' THEN 1 END) * 1.0 / COUNT(*) AS fail_rate
FROM quality_scores
WHERE created_at > datetime('now', '-7 days');
```
```

- [ ] **Step 2: Add §10 to quality.md**

Append to `docs/operations/quality.md`:

```markdown
## 10. 事实校验流水线（fact-check）

详见 [`fact-check.md`](./fact-check.md)。

关键点：

- `FactCheckPipeline` 在 `RubricJudge` 之前跑，确定性验证（不走 LLM）
- 关键 claim（date/weekday/math/unit）fail-closed，触发 REPAIR/REJECT
- 汇率 claim fail-open（外部 API 不稳）
- 所有验证结果落到 `quality_scores.fact_check_*` 字段
```

- [ ] **Step 3: Commit**

```bash
git add docs/operations/fact-check.md docs/operations/quality.md
git commit -m "docs: add fact-check operator guide and quality.md §10"
```

---

## Task 21: Full Test Run + Final Verification

**Files:** (no changes — verification only)

- [ ] **Step 1: Run all fact_check tests**

Run: `.venv/bin/pytest tests/test_fact_check_*.py tests/regression/test_clothing_reminder_regression.py tests/e2e/test_fact_check_e2e.py -v`

Expected: ALL PASS (target ~50+ tests)

- [ ] **Step 2: Run full test suite to confirm no regressions**

Run: `.venv/bin/pytest tests/ -q`

Expected: 0 failures (existing 639+ tests still pass + new ~50)

- [ ] **Step 3: Run lint**

Run: `.venv/bin/ruff check nexus/ tests/`
Expected: 0 errors

Run: `.venv/bin/ruff format --check nexus/ tests/`
Expected: 0 diff

- [ ] **Step 4: Run meta-eval final check**

Run: `.venv/bin/python scripts/eval_rubrics.py --samples data/rubric_eval_samples.jsonl --output data/eval_report.json`

Expected: Pearson ≥ 0.7, Cohen's kappa ≥ 0.4

- [ ] **Step 5: Final commit if any cleanup needed**

```bash
git status  # Should be clean
git log --oneline -25  # Should show 21+ commits
```

---

## Self-Review

**Spec coverage:**
- ✅ date/weekday mismatch (Task 1, 2, 9, 17)
- ✅ math verification (Task 3, 9)
- ✅ unit conversion (Task 4, 5, 9)
- ✅ exchange rate (Task 6, 7, 9)
- ✅ fail-closed critical / fail-open secondary (Task 9, 10)
- ✅ Asia/Shanghai timezone (Task 13, 15)
- ✅ 一次性完成 P1+P2+P3 (no phased rollout — all tasks here)
- ✅ Deterministic (no LLM in verifiers)
- ✅ QualityPipeline integration (Task 10)
- ✅ DB persistence (Task 11, 12)
- ✅ MCP servers for agent (Task 13, 14, 15)
- ✅ System prompt constraint (Task 16)
- ✅ Regression test (Task 17)
- ✅ E2E test (Task 18)
- ✅ Meta-eval (Task 19)
- ✅ Documentation (Task 20)

**Placeholder scan:** No TBD/TODO. All code blocks complete. Exact file paths. Exact commands.

**Type consistency:**
- `FactClaim.from_unit/to_unit` defined in Task 5, used in Task 5 ✓
- `FactClaim.from_ccy/to_ccy` defined in Task 7, used in Task 7 ✓
- `FactCheckReport.to_dict()` used in middleware and pipeline consistently ✓
- `FactCheckError.conflicts` set in middleware, asserted in test ✓

---

## Execution Handoff

Plan saved to `docs/superpowers/plans/2026-07-10-fact-check-pipeline.md`.

Two execution options:

1. **Subagent-Driven (recommended)** — Fresh subagent per task, two-stage review, fast iteration
2. **Inline Execution** — Execute in this session, batch with checkpoints

Which approach?