"""WebSocket 客户端注册表(供微信等外部通道在主事件循环中广播)。

模块化拆分后,本模块只暴露注册表 + 锁。``api/ws/handlers.py`` 在
WS 连接建立 / 断开时调 ``register`` / ``unregister``。``main.py``
``_build_broadcast_to_ws`` 工厂和 ``api/ws/handlers.py`` 直接遍历 ``clients()``。
"""

from __future__ import annotations

import threading

from fastapi import WebSocket

__all__ = ["_ws_clients", "_clients_lock", "register", "unregister", "clients"]


# 当前已注册的 WebSocket 客户端列表
_ws_clients: list[WebSocket] = []
_clients_lock = threading.RLock()


def register(websocket: WebSocket) -> None:
    """把客户端加入注册表(幂等)。"""
    with _clients_lock:
        if websocket not in _ws_clients:
            _ws_clients.append(websocket)


def unregister(websocket: WebSocket) -> bool:
    """从注册表移除客户端。返回是否实际移除(便于日志)。"""
    with _clients_lock:
        if websocket in _ws_clients:
            _ws_clients.remove(websocket)
            return True
        return False


def clients() -> list[WebSocket]:
    """返回注册表当前快照(在锁内 list 复制)。"""
    with _clients_lock:
        return list(_ws_clients)
