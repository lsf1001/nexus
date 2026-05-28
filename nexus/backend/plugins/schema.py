"""Plugin Config Schema - 插件配置 Schema

参考 OpenClaw: openclaw/plugin-sdk/channel-config-schema
https://github.com/openclaw/openclaw/blob/main/docs/plugins/sdk-channel-plugins.md
"""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ConfigSchema:
    """配置 Schema 基类"""
    type: str = "object"
    properties: dict[str, Any] = field(default_factory=dict)
    required: list[str] = field(default_factory=list)


@dataclass
class StringField:
    """字符串字段"""
    type: str = "string"
    default: str = ""
    description: str = ""
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    pattern: Optional[str] = None  # 正则表达式


@dataclass
class NumberField:
    """数字字段"""
    type: str = "number"
    default: float = 0
    description: str = ""
    minimum: Optional[float] = None
    maximum: Optional[float] = None


@dataclass
class BooleanField:
    """布尔字段"""
    type: str = "boolean"
    default: bool = False
    description: str = ""


@dataclass
class EnumField:
    """枚举字段"""
    type: str = "string"
    enum: list[str] = field(default_factory=list)
    default: str = ""
    description: str = ""


@dataclass
class ArrayField:
    """数组字段"""
    type: str = "array"
    items: dict[str, Any] = field(default_factory=dict)
    default: list = field(default_factory=list)
    description: str = ""


@dataclass
class ObjectField:
    """对象字段"""
    type: str = "object"
    properties: dict[str, Any] = field(default_factory=dict)
    default: dict = field(default_factory=dict)
    description: str = ""


def build_config_schema(
    fields: dict[str, Any],
    required: Optional[list[str]] = None,
) -> dict[str, Any]:
    """构建配置 Schema

    辅助函数，从字段定义构建 JSON Schema
    """
    properties = {}
    for name, field_def in fields.items():
        if isinstance(field_def, dict):
            properties[name] = field_def
        else:
            properties[name] = field_def.__dict__ if hasattr(field_def, "__dict__") else {}

    schema = {
        "type": "object",
        "properties": properties,
    }

    if required:
        schema["required"] = required

    return schema


def required_fields(*field_names: str) -> list[str]:
    """标记必填字段"""
    return list(field_names)
