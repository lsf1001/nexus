"""Linux systemd 守护进程管理。"""
import subprocess
from pathlib import Path

from .base import DaemonManager

SYSTEMD_SERVICE_NAME = "nexus"
SYSTEMD_DIR = Path.home() / ".config" / "systemd" / "user"


class SystemdManager(DaemonManager):
    """Linux systemd 守护进程管理器。"""

    def _service_path(self) -> Path:
        """获取 service 文件路径。"""
        return SYSTEMD_DIR / f"{SYSTEMD_SERVICE_NAME}.service"

    def _generate_unit(self) -> str:
        """生成 systemd unit 文件内容。"""
        nexus_home = Path.home() / ".nexus"
        python_path = nexus_home / ".venv" / "bin" / "python"
        nexus_path = nexus_home / "nexus"

        return f"""[Unit]
Description=Nexus Gateway
After=network-online.target

[Service]
Type=simple
ExecStart={python_path} -m uvicorn nexus.backend.main:app --host 0.0.0.0 --port 30000
WorkingDirectory={nexus_path}
Environment=PATH={nexus_home}/.venv/bin:/usr/local/bin:/usr/bin:/bin
Environment=NEXUS_HOME={nexus_home}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""

    def install(self) -> None:
        """注册为 systemd 服务。"""
        SYSTEMD_DIR.mkdir(parents=True, exist_ok=True)
        service_path = self._service_path()
        unit_content = self._generate_unit()
        service_path.write_text(unit_content, encoding="utf-8")

        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            capture_output=True,
        )
        subprocess.run(
            ["systemctl", "--user", "enable", SYSTEMD_SERVICE_NAME],
            capture_output=True,
        )

    def uninstall(self) -> None:
        """移除 systemd 服务。"""
        service_path = self._service_path()
        if service_path.exists():
            subprocess.run(
                ["systemctl", "--user", "stop", SYSTEMD_SERVICE_NAME],
                capture_output=True,
            )
            subprocess.run(
                ["systemctl", "--user", "disable", SYSTEMD_SERVICE_NAME],
                capture_output=True,
            )
            service_path.unlink()
            subprocess.run(
                ["systemctl", "--user", "daemon-reload"],
                capture_output=True,
            )

    def start(self) -> None:
        """启动服务。"""
        service_path = self._service_path()
        if not service_path.exists():
            self.install()

        subprocess.run(
            ["systemctl", "--user", "start", SYSTEMD_SERVICE_NAME],
            capture_output=True,
            check=True,
        )

    def stop(self) -> None:
        """停止服务。"""
        subprocess.run(
            ["systemctl", "--user", "stop", SYSTEMD_SERVICE_NAME],
            capture_output=True,
        )

    def restart(self) -> None:
        """重启服务。"""
        subprocess.run(
            ["systemctl", "--user", "restart", SYSTEMD_SERVICE_NAME],
            capture_output=True,
        )

    def is_running(self) -> bool:
        """检查服务是否运行中。"""
        try:
            result = subprocess.run(
                ["systemctl", "--user", "is-active", SYSTEMD_SERVICE_NAME],
                capture_output=True,
                text=True,
            )
            return result.stdout.strip() == "active"
        except Exception:
            return False

    def get_pid(self) -> int | None:
        """获取服务 PID。"""
        try:
            result = subprocess.run(
                ["systemctl", "--user", "show", SYSTEMD_SERVICE_NAME, "--property=MainPID"],
                capture_output=True,
                text=True,
            )
            for line in result.stdout.splitlines():
                if line.startswith("MainPID="):
                    pid_str = line.split("=")[1].strip()
                    if pid_str.isdigit() and int(pid_str) > 0:
                        return int(pid_str)
        except Exception:
            pass
        return None
