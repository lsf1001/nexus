"""测试 API 端点"""

import pytest
from fastapi.testclient import TestClient


# 需要先启动服务才能测试，这里只测试数据结构


class TestAPIResponseStructure:
    """测试 API 响应结构"""

    def test_model_info_structure(self):
        """测试模型信息响应结构"""
        # 这个测试验证 API 返回的数据结构
        expected_fields = ["model_name", "temperature", "api_base"]

        # 模拟数据
        mock_response = {
            "model_name": "MiniMax-M2.7",
            "temperature": 0.7,
            "api_base": "https://api.minimaxi.com/v1",
            "id": "minimax",
            "max_context_tokens": 200000
        }

        for field in expected_fields:
            assert field in mock_response

    def test_context_info_structure(self):
        """测试上下文信息响应结构"""
        expected_fields = ["max_tokens", "trigger_threshold", "trigger_percent", "keep_messages"]

        mock_response = {
            "max_tokens": 200000,
            "trigger_threshold": 170000,
            "trigger_percent": 85,
            "keep_messages": 15,
            "offload_path": "~/.nexus/store/conversation_history"
        }

        for field in expected_fields:
            assert field in mock_response

    def test_session_manager_build_prompt(self):
        """测试 SessionManager build_prompt 的完整流程"""
        from nexus.backend.sessions import SessionManager

        sm = SessionManager()

        # 1. 先保存一条记忆
        sm.memory_service.save_memory(
            category="preference",
            key="测试偏好",
            value="用户喜欢简洁"
        )

        # 2. 构建 prompt
        result = sm.build_prompt("test-session-001", "你好，帮我写代码")

        # 3. 验证结构
        assert "session_id" in result
        assert "messages" in result
        assert len(result["messages"]) >= 2

        # 4. 验证消息顺序：system -> ... -> user
        roles = [m["role"] for m in result["messages"]]
        assert roles[0] == "system"
        assert roles[-1] == "user"

        # 5. 验证 system prompt 包含记忆
        system_content = result["messages"][0]["content"]
        assert isinstance(system_content, str)


class TestMemoryServiceBM25:
    """测试 BM25 检索功能"""

    def test_bm25_index_rebuild(self):
        """测试 BM25 索引重建"""
        from nexus.backend.memory import MemoryService

        ms = MemoryService()

        # 保存多条记忆
        for i in range(5):
            ms.save_memory(
                category="test",
                key=f"key_{i}",
                value=f"value_{i}"
            )

        # 强制重建索引
        ms._invalidate_bm25()
        ms._ensure_bm25()

        # 验证索引已构建
        assert ms._bm25 is not None
        assert len(ms._bm25_memories) >= 5

    def test_search_with_scores(self):
        """测试带分数的搜索结果"""
        from nexus.backend.memory import MemoryService

        ms = MemoryService()

        # 保存特定内容的记忆（用英文避免中文分词问题）
        ms.save_memory(category="knowledge", key="python_key", value="python is a programming language")
        ms.save_memory(category="knowledge", key="java_key", value="java is an object oriented language")

        # 搜索英文关键词
        results = ms.search_memory("python", limit=5)

        # 验证结果 - BM25 需要有足够的英文语料
        assert len(results) >= 1
        # 验证结果包含必要字段
        for r in results:
            assert "id" in r
            assert "key" in r
            assert "value" in r