"""Nexus Plugin SDK - 插件系统

参考 OpenClaw SDK 设计:
- plugin-sdk: 核心接口
- channel-core: 通道核心
- channel-config-schema: 配置 Schema
- channel-outbound: 消息发送
- channel-inbound: 消息接收
- channel-turn: 会话路由

文档: https://github.com/openclaw/openclaw/blob/main/docs/plugins/
"""

from .channel import (
    BaseChannel,
    ChannelConfig,
    ChannelPlugin,
    ChannelStatus,
)
from .manifest import (
    ChannelManifest,
    HookManifest,
    PluginManifest,
    ToolManifest,
)
from .message import (
    AckPolicy,
    ChannelMessageAdapter,
    InboundMessage,
    MediaAdapter,
    MessageContent,
    MessageReceipt,
    MessageReceiptStatus,
    MessageType,
    OutboundMessage,
    TextOnlyAdapter,
    TypingIndicator,
)
from .registry import (
    PluginRegistry,
    define_channel_plugin_entry,
    define_plugin_entry,
)
from .schema import (
    ArrayField,
    BooleanField,
    ConfigSchema,
    EnumField,
    NumberField,
    ObjectField,
    StringField,
    build_config_schema,
    required_fields,
)
from .security import (
    ChannelSecurity,
    DMPolicy,
    DefaultChannelSecurity,
    SecurityResult,
    Sender,
)
from .session import (
    ConversationType,
    DefaultSessionGrammar,
    Session,
    SessionGrammar,
    SessionManager,
)
from .wechat_plugin import WechatChannelPlugin, create_wechat_channel

__all__ = [
    # 核心
    "BaseChannel",
    "ChannelPlugin",
    "ChannelConfig",
    "ChannelStatus",

    # 清单
    "PluginManifest",
    "ChannelManifest",
    "ToolManifest",
    "HookManifest",

    # 消息
    "MessageType",
    "MessageReceiptStatus",
    "AckPolicy",
    "MessageContent",
    "InboundMessage",
    "OutboundMessage",
    "MessageReceipt",
    "TypingIndicator",
    "ChannelMessageAdapter",
    "TextOnlyAdapter",
    "MediaAdapter",

    # 注册表
    "PluginRegistry",
    "define_plugin_entry",
    "define_channel_plugin_entry",

    # Schema
    "ConfigSchema",
    "StringField",
    "NumberField",
    "BooleanField",
    "EnumField",
    "ArrayField",
    "ObjectField",
    "build_config_schema",
    "required_fields",

    # 安全
    "DMPolicy",
    "Sender",
    "SecurityResult",
    "ChannelSecurity",
    "DefaultChannelSecurity",

    # 会话
    "ConversationType",
    "Session",
    "SessionGrammar",
    "SessionManager",
    "DefaultSessionGrammar",

    # 插件实现
    "WechatChannelPlugin",
    "create_wechat_plugin",
]

# 版本
__version__ = "1.0.0"
