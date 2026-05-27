"""守护进程管理模块。"""
from .base import DaemonManager, get_daemon_manager

__all__ = ["DaemonManager", "get_daemon_manager"]
