"""Plugin Manifest - 插件清单定义

参考 OpenClaw: openclaw/plugin-sdk/plugin-entry
https://github.com/openclaw/openclaw/blob/main/docs/plugins/manifest.md
"""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class PluginManifest:
    """插件清单

    描述插件的基本信息和能力
    """
    id: str                          # 插件唯一标识
    name: str                        # 插件名称
    version: str                     # 插件版本
    description: str = ""             # 插件描述

    # 插件类型
    channel: bool = False            # 是否为通道插件
    provider: bool = False           # 是否为提供商插件
    tool: bool = False              # 是否为工具插件
    hook: bool = False              # 是否为钩子插件

    # 能力声明
    capabilities: list[str] = field(default_factory=list)  # 支持的能力列表

    # 依赖
    dependencies: dict[str, str] = field(default_factory=dict)  # 插件依赖

    # 配置
    config_schema: Optional[dict[str, Any]] = None  # JSON Schema

    # 入口点
    entrypoint: str = ""              # 入口模块

    # 元数据
    author: str = ""
    license: str = ""
    homepage: str = ""

    def is_channel_plugin(self) -> bool:
        return self.channel

    def supports_capability(self, capability: str) -> bool:
        return capability in self.capabilities


@dataclass
class ChannelManifest(PluginManifest):
    """通道插件清单

    扩展 PluginManifest，添加通道特有配置
    """
    channel: bool = True

    # 通道特定能力
    supports_dm: bool = False         # 支持私信
    supports_group: bool = False     # 支持群聊
    supports_media: bool = False     # 支持媒体消息
    supports_typing: bool = False   # 支持打字状态
    supports_receipt: bool = False   # 支持消息回执

    # 会话映射
    session_grammar: Optional[dict[str, Any]] = None

    def __post_init__(self):
        self.channel = True
        if self.supports_media:
            self.capabilities.append("media")
        if self.supports_typing:
            self.capabilities.append("typing")
        if self.supports_receipt:
            self.capabilities.append("receipt")


@dataclass
class ToolManifest(PluginManifest):
    """工具插件清单"""
    tool: bool = True

    # 工具定义
    tools: list[dict[str, Any]] = field(default_factory=list)  # 提供的工具列表

    def __post_init__(self):
        self.tool = True


@dataclass
class HookManifest(PluginManifest):
    """钩子插件清单"""
    hook: bool = True

    # 钩子点
    hook_points: list[str] = field(default_factory=list)  # 监听的钩子点

    def __post_init__(self):
        self.hook = True
