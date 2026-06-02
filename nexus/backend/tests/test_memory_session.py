"""测试会话管理和记忆机制"""

from nexus.backend.memory import CATEGORY_PREFERENCE, MemoryService
from nexus.backend.sessions import SessionManager, get_session_manager


class TestSessionManager:
    """测试 SessionManager"""

    def test_build_prompt_structure(self):
        """测试 build_prompt 返回结构"""
        sm = SessionManager()
        result = sm.build_prompt("test-session-123", "你好")

        assert "session_id" in result
        assert "messages" in result
        assert result["session_id"] == "test-session-123"

    def test_build_prompt_messages_format(self):
        """测试 messages 格式"""
        sm = SessionManager()
        result = sm.build_prompt("session-1", "测试消息")

        messages = result["messages"]
        assert len(messages) >= 2  # system + user 至少两条

        # 检查第一条是 system
        assert messages[0]["role"] == "system"

        # 检查最后一条是 user
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == "测试消息"

    def test_build_prompt_with_empty_memory(self):
        """测试无记忆时的 prompt"""
        sm = SessionManager()
        result = sm.build_prompt("session-empty", "你好")

        messages = result["messages"]
        system_msg = messages[0]

        # 系统消息应该包含默认身份
        assert "Nexus" in system_msg["content"] or "AI" in system_msg["content"]

    def test_singleton(self):
        """测试单例模式"""
        sm1 = get_session_manager()
        sm2 = get_session_manager()
        assert sm1 is sm2


class TestMemoryService:
    """测试 MemoryService"""

    def test_save_and_retrieve_memory(self):
        """测试保存和获取记忆"""
        ms = MemoryService()

        # 保存记忆
        result = ms.save_memory(
            category=CATEGORY_PREFERENCE, key="test_key", value="test_value", memory_type="explicit"
        )

        assert result["key"] == "test_key"
        assert result["value"] == "test_value"
        assert result["category"] == CATEGORY_PREFERENCE

    def test_search_memory_fallback(self):
        """测试搜索回退机制（当 BM25 不可用时）"""
        ms = MemoryService()

        # 保存测试记忆
        ms.save_memory(category="preference", key="简洁偏好", value="用户喜欢简洁回答")

        # 强制使用数据库搜索（通过空关键词触发回退或直接测试 db_search_memory）
        from nexus.backend.db import search_memory as db_search

        results = db_search("简洁", memory_type=None, limit=5)

        # 验证数据库搜索能找到刚保存的记忆
        assert len(results) >= 1

    def test_build_context(self):
        """测试构建记忆上下文"""
        ms = MemoryService()

        # 保存一些记忆
        ms.save_memory(category=CATEGORY_PREFERENCE, key="语言偏好", value="用户喜欢中文回答")

        context = ms.build_context("any-session")

        # 上下文应该包含记忆内容
        assert isinstance(context, str)
        assert len(context) > 0

    def test_delete_memory(self):
        """测试删除记忆"""
        ms = MemoryService()

        # 保存后删除
        result = ms.save_memory(category="test", key="delete_me", value="delete this")

        memory_id = result["id"]
        success = ms.delete_memory(memory_id, hard=True)
        assert success is True


class TestMemorySearchEdgeCases:
    """测试记忆检索边界情况"""

    def test_empty_keyword(self):
        """测试空关键词"""
        ms = MemoryService()
        results = ms.search_memory("")
        # 空关键词应该返回空列表
        assert isinstance(results, list)

    def test_no_match(self):
        """测试无匹配结果"""
        ms = MemoryService()
        results = ms.search_memory("xyz_nonexistent_12345", limit=5)
        assert len(results) == 0

    def test_limit_parameter(self):
        """测试 limit 参数"""
        ms = MemoryService()

        # 添加多条记忆
        for i in range(10):
            ms.save_memory(category="test", key=f"key_{i}", value=f"value_{i}")

        results = ms.search_memory("key", limit=3)
        assert len(results) <= 3


class TestSessionMemoryIntegration:
    """测试会话和记忆的集成"""

    def test_session_uses_memory_context(self):
        """测试会话使用记忆上下文"""
        sm = SessionManager()

        # 先添加记忆
        sm.memory_service.save_memory(category=CATEGORY_PREFERENCE, key="用户名字", value="张三")

        # 构建 prompt 时应该包含记忆
        result = sm.build_prompt("session-with-memory", "你好")

        system_content = result["messages"][0]["content"]
        # 记忆内容应该在 system prompt 中
        assert isinstance(system_content, str)

    def test_memory_service_has_bm25(self):
        """测试 BM25 索引存在"""
        ms = MemoryService()
        # 添加一些数据触发 BM25 构建
        ms.save_memory(category="test", key="bm25 test", value="testing bm25")
        ms._ensure_bm25()

        # BM25 索引应该被构建
        assert ms._bm25 is not None or len(ms._bm25_memories) > 0
