"""单位换算表，用于事实校验里的确定性数值核对。

这里保留常见单位的手写换算表，新增单位只需要在对应分类里补一行。
不引入外部依赖，避免为了小范围换算拉入额外运行时包。
"""

from __future__ import annotations

from typing import Final

# 每个分组内的单位都可通过一个基准单位互相换算；温度因偏移量需要单独处理。
_UNIT_GROUPS: Final[dict[str, dict[str, float]]] = {
    "temperature": {"C": 0.0, "F": 0.0, "K": 0.0},
    "length": {
        "m": 1.0,
        "km": 1000.0,
        "cm": 0.01,
        "mm": 0.001,
        "mile": 1609.344,
        "ft": 0.3048,
        "inch": 0.0254,
        "yd": 0.9144,
    },
    "mass": {
        "kg": 1.0,
        "g": 0.001,
        "mg": 0.000001,
        "lb": 0.45359237,
        "oz": 0.028349523125,
    },
    "volume": {
        "L": 1.0,
        "mL": 0.001,
        "gal": 3.785411784,
    },
}


class _SupportedUnits(dict[str, list[str]]):
    """按分类存储支持单位，并允许用单位名做成员检查。"""

    def __contains__(self, key: object) -> bool:
        """兼容 ``"C" in supported_units()`` 这类单位名成员检查。"""
        if super().__contains__(key):
            return True
        if not isinstance(key, str):
            return False
        return any(key in group_units for group_units in self.values())


def _find_group(unit: str) -> str | None:
    """查找单位所属分类，未知单位返回 ``None``。"""
    for group, units in _UNIT_GROUPS.items():
        if unit in units:
            return group
    return None


def convert(value: float, from_unit: str, to_unit: str) -> float:
    """将数值从一个单位换算到另一个单位。

    Args:
        value: 待换算数值。
        from_unit: 来源单位。
        to_unit: 目标单位。

    Returns:
        换算后的浮点数。

    Raises:
        ValueError: 单位未知或两个单位不属于同一可换算分类。
    """
    if from_unit == to_unit:
        return float(value)

    src_group = _find_group(from_unit)
    dst_group = _find_group(to_unit)
    if src_group is None:
        raise ValueError(f"Unknown unit: {from_unit!r}")
    if dst_group is None:
        raise ValueError(f"Unknown unit: {to_unit!r}")
    if src_group != dst_group:
        raise ValueError(f"Incompatible units: {from_unit!r} ({src_group}) → {to_unit!r} ({dst_group})")

    if src_group == "temperature":
        return _convert_temperature(value, from_unit, to_unit)

    src_factor = _UNIT_GROUPS[src_group][from_unit]
    dst_factor = _UNIT_GROUPS[src_group][to_unit]
    return value * src_factor / dst_factor


def _convert_temperature(value: float, from_unit: str, to_unit: str) -> float:
    """换算带偏移量的温度单位。"""
    if from_unit == "C":
        kelvin = value + 273.15
    elif from_unit == "F":
        kelvin = (value - 32) * 5 / 9 + 273.15
    elif from_unit == "K":
        kelvin = value
    else:
        raise ValueError(f"Unknown temperature unit: {from_unit!r}")

    if to_unit == "C":
        return kelvin - 273.15
    if to_unit == "F":
        return (kelvin - 273.15) * 9 / 5 + 32
    if to_unit == "K":
        return kelvin
    raise ValueError(f"Unknown temperature unit: {to_unit!r}")


def supported_units() -> dict[str, list[str]]:
    """返回按分类分组的全部支持单位。"""
    return _SupportedUnits({group: list(units) for group, units in _UNIT_GROUPS.items()})
