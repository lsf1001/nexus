"""测试 WebSocket 鉴权（/api/ws）。"""

import pytest
from fastapi.testclient import TestClient

from nexus.backend.main import app


class TestWebSocketAuth:
    """WebSocket 应校验 token 参数。"""

    def test_missing_token_rejected(self) -> None:
        """无 token 应被 4001 关闭。"""
        client = TestClient(app)
        with pytest.raises(Exception):
            with client.websocket_connect("/api/ws") as ws:
                ws.receive_json()  # 应在 accept 前就关闭

    def test_wrong_token_rejected(self) -> None:
        """错误 token 应被 4001 关闭。"""
        client = TestClient(app)
        with pytest.raises(Exception):
            with client.websocket_connect("/api/ws?token=wrong") as ws:
                ws.receive_json()
