"""确定性事实校验器。

每个校验器接收一个 FactClaim，返回 VerificationResult。
校验器都是纯函数 —— 不调用 LLM，不发起网络请求（汇率校验器除外，
它走带缓存的 API）。

验证策略:
- DateWeekdayVerifier: 用 Python datetime 核对日期与星期是否一致
- MathVerifier: 通过 AST 安全求值核对算术表达式
- UnitsVerifier: 用 units.convert 核对单位换算
"""

from __future__ import annotations

import ast
import operator
import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

from nexus.backend.fact_check.extractors import FactClaim
from nexus.backend.fact_check.units import convert


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


class MathVerifier:
    """通过 AST 安全求值核对算术表达式。

    仅允许数字常量与 +、-、*、/、**、一元负号;函数调用、属性访问、
    Name 节点等都会被拒绝,杜绝 eval 注入。
    """

    _ALLOWED_OPS: dict[type, object] = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
    }

    _ZH_OP_MAP: dict[str, str] = {
        "乘以": "*",
        "乘": "*",
        "除以": "/",
        "除": "/",
        "加上": "+",
        "加": "+",
        "减去": "-",
        "减": "-",
    }

    @staticmethod
    def _normalize(expr: str) -> str:
        """替换中文运算符为符号,并剥离表达式里的单位后缀。"""
        out = expr
        for zh, sym in MathVerifier._ZH_OP_MAP.items():
            out = out.replace(zh, sym)
        # 去掉数字尾巴上的字母/百分号单位（如 "1.5L" → "1.5"）
        out = re.sub(r"([\d.]+)[a-zA-Z%]+", r"\1", out)
        out = out.replace("×", "*").replace("÷", "/")
        return out

    def _safe_eval(self, expr: str) -> float:
        """用 AST 求值算术表达式;非允许节点抛 ValueError。"""
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
            return self._ALLOWED_OPS[op_type](left, right)  # type: ignore[operator]
        if isinstance(node, ast.UnaryOp):
            if type(node.op) not in self._ALLOWED_OPS:
                raise ValueError(f"Unary {type(node.op).__name__} not allowed")
            return self._ALLOWED_OPS[type(node.op)](  # type: ignore[operator]
                self._eval_node(node.operand),
            )
        raise ValueError(f"AST node {type(node).__name__} not allowed")

    @staticmethod
    def _strip_units(s: str) -> float:
        """从 claimed_result 里剥离单位后缀,只保留数值。"""
        m = re.match(r"([\d.]+)", s.strip())
        if not m:
            raise ValueError(f"No numeric value in {s!r}")
        return float(m.group(1))

    def verify(self, claim: FactClaim) -> VerificationResult:
        """校验一条 math 声明;非该类型则跳过。"""
        if claim.kind != "math":
            return VerificationResult(claim=claim, verdict="skipped")

        assert claim.expression and claim.claimed_result
        try:
            normalized = self._normalize(claim.expression)
            expected = self._safe_eval(normalized)
            actual = self._strip_units(claim.claimed_result)
        except (ValueError, SyntaxError) as e:
            return VerificationResult(
                claim=claim,
                verdict="error",
                error_message=str(e),
            )

        verdict: Literal["ok", "conflict"] = "ok" if abs(expected - actual) < 1e-6 else "conflict"
        return VerificationResult(
            claim=claim,
            verdict=verdict,
            expected_value=expected,
            actual_value=actual,
        )


class UnitsVerifier:
    """用 ``units.convert`` 核对单位换算声明的真伪。

    误差容限固定为 0.01,足以吸收常见四舍五入(如 km↔mile 的 3.107)而不
    放过明显错误(如 100°C = 200°F)。当来源/目标单位不属于同一可换算分类
    时返回 verdict="error"。
    """

    _TOLERANCE: float = 0.01

    def verify(self, claim: FactClaim) -> VerificationResult:
        """校验一条 unit 声明;非该类型则跳过。"""
        if claim.kind != "unit":
            return VerificationResult(claim=claim, verdict="skipped")

        assert claim.claimed_value is not None
        assert claim.from_unit and claim.to_unit
        try:
            actual = convert(claim.claimed_value, claim.from_unit, claim.to_unit)
            expected = float(str(claim.claimed_result))
        except (ValueError, TypeError) as e:
            return VerificationResult(
                claim=claim,
                verdict="error",
                error_message=str(e),
            )

        verdict: Literal["ok", "conflict"] = "ok" if abs(actual - expected) < self._TOLERANCE else "conflict"
        return VerificationResult(
            claim=claim,
            verdict=verdict,
            expected_value=actual,
            actual_value=expected,
        )
