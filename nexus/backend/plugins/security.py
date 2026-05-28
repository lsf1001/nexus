"""Channel Security - 通道安全策略

参考 OpenClaw: openclaw/plugin-sdk/channel-ingress
https://github.com/openclaw/openclaw/blob/main/docs/plugins/sdk-channel-ingress.md
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class DMPolicy(Enum):
    """私信策略"""
    ALLOW = "allow"           # 允许所有
    DENY = "deny"            # 拒绝所有
    APPROVE = "approve"       # 需要审批
    WHITELIST = "whitelist"  # 白名单


@dataclass
class Sender:
    """发送者信息"""
    sender_id: str
    sender_name: str = ""
    is_verified: bool = False
    is_trusted: bool = False
    metadata: dict = field(default_factory=dict)


@dataclass
class SecurityResult:
    """安全检查结果"""
    allowed: bool
    reason: str = ""
    action: str = "block"  # block, allow, approve

    @classmethod
    def allow(cls, reason: str = "") -> "SecurityResult":
        return cls(allowed=True, reason=reason, action="allow")

    @classmethod
    def deny(cls, reason: str) -> "SecurityResult":
        return cls(allowed=False, reason=reason, action="block")

    @classmethod
    def approve(cls, reason: str = "") -> "SecurityResult":
        return cls(allowed=True, reason=reason, action="approve")


class ChannelSecurity(ABC):
    """通道安全策略基类

    参考 OpenClaw: Security (DM policy, allowlists)
    """

    def __init__(self):
        self._dm_policy = DMPolicy.ALLOW
        self._whitelist: set[str] = set()
        self._blacklist: set[str] = set()

    def set_dm_policy(self, policy: DMPolicy) -> None:
        """设置私信策略"""
        self._dm_policy = policy

    def add_to_whitelist(self, sender_id: str) -> None:
        """添加到白名单"""
        self._whitelist.add(sender_id)

    def remove_from_whitelist(self, sender_id: str) -> None:
        """从白名单移除"""
        self._whitelist.discard(sender_id)

    def add_to_blacklist(self, sender_id: str) -> None:
        """添加到黑名单"""
        self._blacklist.add(sender_id)

    def remove_from_blacklist(self, sender_id: str) -> None:
        """从黑名单移除"""
        self._blacklist.discard(sender_id)

    async def check_sender(self, sender: Sender) -> SecurityResult:
        """检查发送者

        统一的安全检查入口
        """
        # 黑名单检查
        if sender.sender_id in self._blacklist:
            return SecurityResult.deny("Sender is blacklisted")

        # 白名单检查
        if self._dm_policy == DMPolicy.WHITELIST:
            if sender.sender_id in self._whitelist:
                return SecurityResult.allow()
            return SecurityResult.deny("Sender not in whitelist")

        # 审批模式
        if self._dm_policy == DMPolicy.APPROVE:
            if sender.sender_id in self._whitelist:
                return SecurityResult.allow()
            return SecurityResult.approve("Sender requires approval")

        # 允许所有
        if self._dm_policy == DMPolicy.ALLOW:
            return SecurityResult.allow()

        # 拒绝所有
        return SecurityResult.deny("DM policy is deny")

    @abstractmethod
    async def validate_message(self, sender: Sender, content: str) -> SecurityResult:
        """验证消息内容"""
        pass

    @abstractmethod
    async def authorize_action(
        self,
        sender: Sender,
        action: str,
        target: Optional[str] = None,
    ) -> SecurityResult:
        """授权动作"""
        pass


class DefaultChannelSecurity(ChannelSecurity):
    """默认安全策略"""

    async def validate_message(self, sender: Sender, content: str) -> SecurityResult:
        """验证消息"""
        if not content or len(content.strip()) == 0:
            return SecurityResult.deny("Empty message")

        # 内容长度检查
        if len(content) > 10000:
            return SecurityResult.deny("Message too long")

        return SecurityResult.allow()

    async def authorize_action(
        self,
        sender: Sender,
        action: str,
        target: Optional[str] = None,
    ) -> SecurityResult:
        """授权动作"""
        # 默认允许
        allowed_actions = ["send_message", "send_media"]
        if action in allowed_actions:
            return SecurityResult.allow()

        return SecurityResult.deny(f"Action {action} not allowed")
