"""守护进程管理抽象基类。"""

import platform
from abc import ABC, abstractmethod


class DaemonManager(ABC):
    """守护进程管理抽象基类。"""

    @abstractmethod
    def install(self) -> None:
        """注册为系统服务。"""
        ...

    @abstractmethod
    def uninstall(self) -> None:
        """移除系统服务注册。"""
        ...

    @abstractmethod
    def start(self) -> None:
        """启动服务。"""
        ...

    @abstractmethod
    def stop(self) -> None:
        """停止服务。"""
        ...

    @abstractmethod
    def restart(self) -> None:
        """重启服务。"""
        ...

    @abstractmethod
    def is_running(self) -> bool:
        """检查服务是否运行中。"""
        ...

    @abstractmethod
    def get_pid(self) -> int | None:
        """获取服务 PID。"""
        ...


def get_daemon_manager() -> DaemonManager:
    """根据当前操作系统返回对应的守护进程管理器。"""
    from .launchd import LaunchdManager
    from .systemd import SystemdManager

    if platform.system() == "Darwin":
        return LaunchdManager()
    elif platform.system() == "Linux":
        return SystemdManager()
    else:
        raise RuntimeError(f"不支持的操作系统: {platform.system()}")
