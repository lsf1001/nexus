"""记忆系统服务。

融合设计：
- MemoryService: 记忆服务（对 Agent 暴露的统一接口）
- EvolutionService: 进化服务（自动学习和优化）
- 使用 UnifiedStore 统一存储层
"""

import json
import re
import uuid
from typing import Optional, Any

from .db import (
    save_memory as db_save_memory,
    get_memory as db_get_memory,
    search_memory as db_search_memory,
    delete_memory as db_delete_memory,
    list_user_memory as db_list_user_memory,
    get_session_memory as db_get_session_memory,
    update_tool_stats as db_update_tool_stats,
    get_tool_stats as db_get_tool_stats,
    get_all_tool_stats as db_get_all_tool_stats,
    update_session_stats as db_update_session_stats,
    get_session_stats as db_get_session_stats,
    end_session as db_end_session,
    cleanup_expired_memory,
    cleanup_low_confidence_memory,
    cleanup_low_access_memory,
)
from .config import CONFIG


# ============================================================================
# 常量定义
# ============================================================================

MEMORY_TYPE_EXPLICIT = "explicit"    # 用户显式保存
MEMORY_TYPE_EVOLVED = "evolved"       # 自动进化生成
MEMORY_TYPE_SESSION = "session"       # 会话级记忆

CATEGORY_PREFERENCE = "preference"   # 用户偏好
CATEGORY_KNOWLEDGE = "knowledge"      # 用户告诉的事实
CATEGORY_CONTEXT = "context"         # 当前会话上下文
CATEGORY_SUMMARY = "summary"         # 会话摘要

# 自动捕获触发词
AUTO_CAPTURE_TRIGGERS = [
    "告诉过我", "我之前", "你应该知道",
    "记住", "别忘了", "重要的是",
    "我的", "我喜欢", "我习惯",
    "我是", "我在做", "我做的是",
    "别忘了", "要记住", "记住这点",
]

# 自动捕获的类别映射
TRIGGER_TO_CATEGORY = {
    "我喜欢": CATEGORY_PREFERENCE,
    "我习惯": CATEGORY_PREFERENCE,
    "我之前": CATEGORY_CONTEXT,
    "告诉过我": CATEGORY_KNOWLEDGE,
    "你应该知道": CATEGORY_KNOWLEDGE,
}


# ============================================================================
# MemoryService - 记忆服务
# ============================================================================

class MemoryService:
    """记忆服务 - 对 Agent 暴露的统一接口"""

    def __init__(self):
        """初始化记忆服务。"""
        self.user_id = "default"

    def save_memory(
        self,
        category: str,
        key: str,
        value: str,
        memory_type: str = MEMORY_TYPE_EXPLICIT,
        session_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        expires_at: Optional[str] = None
    ) -> dict:
        """保存记忆。

        Args:
            category: 分类 (preference, knowledge, context, summary)
            key: 记忆键
            value: 记忆值
            memory_type: 记忆类型 (explicit, evolved, session)
            session_id: 会话 ID（session 类型必需）
            metadata: 元数据
            expires_at: 过期时间
        """
        memory_id = str(uuid.uuid4())

        # session 类型需要 session_id
        full_key = f"{session_id}:{key}" if memory_type == MEMORY_TYPE_SESSION else key

        return db_save_memory(
            memory_id=memory_id,
            memory_type=memory_type,
            category=category,
            key=full_key,
            value=value,
            metadata=metadata,
            expires_at=expires_at
        )

    def get_memory(
        self,
        session_id: Optional[str] = None,
        category: Optional[str] = None,
        memory_type: Optional[str] = None
    ) -> list[dict]:
        """获取记忆列表。

        Args:
            session_id: 会话 ID
            category: 分类过滤
            memory_type: 记忆类型过滤
        """
        return db_get_memory(
            session_id=session_id,
            memory_type=memory_type,
            category=category
        )

    def search_memory(self, keyword: str, memory_type: Optional[str] = None, limit: int = 10) -> list[dict]:
        """搜索记忆（关键词匹配）。

        Args:
            keyword: 搜索关键词
            memory_type: 记忆类型过滤
            limit: 返回数量限制
        """
        return db_search_memory(keyword, memory_type, limit)

    def build_context(self, session_id: str) -> str:
        """构建记忆上下文（用于注入 prompt）。

        Args:
            session_id: 当前会话 ID
        """
        parts = []

        # 1. 用户偏好（最高优先级）
        preferences = db_get_memory(memory_type=MEMORY_TYPE_EXPLICIT, category=CATEGORY_PREFERENCE)
        if preferences:
            parts.append("【用户偏好】")
            for p in preferences:
                if p["is_active"]:
                    parts.append(f"- {p['key']}: {p['value']}")

        # 2. 会话上下文
        contexts = db_get_session_memory(session_id, category=CATEGORY_CONTEXT)
        if contexts:
            parts.append("【当前会话上下文】")
            for c in contexts:
                parts.append(f"- {c['key']}: {c['value']}")

        # 3. 已学习的知识（高置信度）
        knowledge = db_get_memory(memory_type=MEMORY_TYPE_EVOLVED, category=CATEGORY_KNOWLEDGE)
        if knowledge:
            parts.append("【已学习知识】")
            for k in knowledge[:5]:  # 最多5条
                metadata = json.loads(k.get("metadata", "{}")) if k.get("metadata") else {}
                confidence = metadata.get("confidence", 0.5)
                if confidence > 0.5 and k["is_active"]:
                    parts.append(f"- {k['value']}")

        return "\n".join(parts) if parts else ""

    def build_system_memory(self) -> str:
        """构建系统级记忆（跨会话）。"""
        parts = []

        # 用户偏好
        prefs = db_list_user_memory(category=CATEGORY_PREFERENCE)
        if prefs:
            parts.append("【用户偏好】")
            for p in prefs:
                if p["is_active"]:
                    parts.append(f"- {p['key']}: {p['value']}")

        return "\n".join(parts) if parts else ""

    def delete_memory(self, memory_id: str, hard: bool = False) -> bool:
        """删除记忆。

        Args:
            memory_id: 记忆 ID
            hard: 是否硬删除
        """
        return db_delete_memory(memory_id, hard)

    def list_memory(self, category: Optional[str] = None) -> list[dict]:
        """列出所有记忆。

        Args:
            category: 分类过滤
        """
        return db_list_user_memory(category=category)


# ============================================================================
# EvolutionService - 进化服务
# ============================================================================

class EvolutionService:
    """进化服务 - 自动学习和优化"""

    def __init__(self, memory_service: MemoryService):
        """初始化进化服务。

        Args:
            memory_service: 记忆服务实例
        """
        self.memory = memory_service

    def auto_capture(self, user_content: str, session_id: str) -> Optional[dict]:
        """自动捕获用户偏好。

        Args:
            user_content: 用户输入内容
            session_id: 当前会话 ID

        Returns:
            捕获的记忆，如果未触发则返回 None
        """
        for trigger in AUTO_CAPTURE_TRIGGERS:
            if trigger in user_content:
                # 简单提取：找到触发词后的内容作为值
                # 例如："记住我喜欢简洁回答" -> key: "喜欢简洁回答"
                category = CATEGORY_PREFERENCE

                for trigger_pattern, cat in TRIGGER_TO_CATEGORY.items():
                    if trigger_pattern in trigger:
                        category = cat
                        break

                # 提取 key-value
                value = user_content
                for t in AUTO_CAPTURE_TRIGGERS:
                    value = value.replace(t, "").strip()

                if value and len(value) > 1:
                    key = value[:50]  # 截取前50字符作为 key

                    return self.memory.save_memory(
                        category=category,
                        key=key,
                        value=value,
                        memory_type=MEMORY_TYPE_EVOLVED,
                        session_id=session_id,
                        metadata={"source": "auto_capture", "confidence": 0.6}
                    )

        return None

    def record_outcome(self, tool_name: str, success: bool, latency: float) -> None:
        """记录工具调用结果。

        Args:
            tool_name: 工具名称
            success: 是否成功
            latency: 延迟（秒）
        """
        db_update_tool_stats(tool_name, success, latency)

    def check_tool(self, tool_name: str) -> dict:
        """检查工具是否应自动使用。

        Args:
            tool_name: 工具名称

        Returns:
            包含 reliability 和建议的字典
        """
        stats = db_get_tool_stats(tool_name)

        if not stats:
            return {
                "tool_name": tool_name,
                "reliability": 0.5,
                "suggestion": "unknown",
                "can_auto_use": True
            }

        total = stats["success_count"] + stats["failure_count"]
        reliability = stats["success_count"] / total if total > 0 else 0.5

        # 计算平均延迟
        avg_latency = stats["total_latency"] / total if total > 0 else 0

        suggestion = "auto_use"
        can_auto_use = True

        if reliability < 0.5:
            suggestion = "require_confirm"
            can_auto_use = False
        elif reliability < 0.8:
            suggestion = "use_with_caution"
            can_auto_use = True
        elif avg_latency > 5:
            suggestion = "slow_tool"
            can_auto_use = True

        return {
            "tool_name": tool_name,
            "reliability": reliability,
            "avg_latency": avg_latency,
            "suggestion": suggestion,
            "can_auto_use": can_auto_use,
            "success_count": stats["success_count"],
            "failure_count": stats["failure_count"]
        }

    def distill(self, session_id: str, messages: list[dict]) -> list[dict]:
        """从会话中提炼知识。

        Args:
            session_id: 会话 ID
            messages: 消息列表

        Returns:
            提炼出的知识列表
        """
        distilled = []

        if len(messages) < 6:  # 至少6轮对话才提炼
            return distilled

        # 简单策略：统计工具使用成功率
        tool_results = {}
        for msg in messages:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg.get("tool_calls", []):
                    tool_name = tc.get("function", {}).get("name", "unknown")
                    if tool_name not in tool_results:
                        tool_results[tool_name] = {"success": 0, "failure": 0}
                    # 简化：假设成功
                    tool_results[tool_name]["success"] += 1

        # 保存提炼结果
        for tool_name, stats in tool_results.items():
            if stats["success"] >= 2:  # 至少成功2次
                self.memory.save_memory(
                    category=CATEGORY_KNOWLEDGE,
                    key=f"tool_success_{tool_name}",
                    value=f"工具 {tool_name} 在该会话中成功使用 {stats['success']} 次",
                    memory_type=MEMORY_TYPE_EVOLVED,
                    session_id=session_id,
                    metadata={
                        "source": "distill",
                        "confidence": 0.6,
                        "tool_name": tool_name
                    }
                )
                distilled.append(tool_name)

        # 保存会话摘要
        user_msgs = [m for m in messages if m.get("role") == "user"]
        assistant_msgs = [m for m in messages if m.get("role") == "assistant"]

        if user_msgs:
            summary = f"用户问了 {len(user_msgs)} 个问题，助手回复了 {len(assistant_msgs)} 条消息"
            self.memory.save_memory(
                category=CATEGORY_SUMMARY,
                key="session_summary",
                value=summary,
                memory_type=MEMORY_TYPE_SESSION,
                session_id=session_id,
                expires_at=None  # session 类型默认不过期
            )
            distilled.append("session_summary")

        return distilled

    def get_strategy(self, task_type: str) -> dict:
        """获取基于历史的优化策略。

        Args:
            task_type: 任务类型

        Returns:
            优化策略建议
        """
        all_stats = db_get_all_tool_stats()

        strategies = {
            "code": {
                "preferred_tools": ["write_file", "edit_file", "read_file"],
                "avoid_tools": [],
                "strategy": "使用文件操作工具时优先读写，复杂修改用 edit_file"
            },
            "search": {
                "preferred_tools": ["web_search", "browse"],
                "avoid_tools": [],
                "strategy": "搜索任务优先使用 web_search"
            },
            "general": {
                "preferred_tools": [],
                "avoid_tools": [],
                "strategy": "根据上下文选择合适工具"
            }
        }

        # 分析历史表现调整策略
        for stats in all_stats:
            total = stats["success_count"] + stats["failure_count"]
            if total < 3:
                continue

            reliability = stats["success_count"] / total
            tool_name = stats["tool_name"]

            if reliability < 0.6:
                # 低可靠性工具加入避免列表
                for task in strategies.values():
                    if tool_name not in task["avoid_tools"]:
                        task["avoid_tools"].append(tool_name)

        return strategies.get(task_type, strategies["general"])

    def get_evolved_memory(self, session_id: str) -> list[dict]:
        """获取该会话的进化记忆。"""
        return db_get_memory(session_id=session_id, memory_type=MEMORY_TYPE_EVOLVED)


# ============================================================================
# 清理任务
# ============================================================================

def run_memory_cleanup() -> dict:
    """运行记忆清理任务。返回清理统计。"""
    stats = {
        "expired": cleanup_expired_memory(),
        "low_confidence": cleanup_low_confidence_memory(),
        "low_access": cleanup_low_access_memory()
    }
    return stats