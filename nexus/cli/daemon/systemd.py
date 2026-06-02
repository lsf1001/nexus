"""Linux systemd 守护进程管理。"""

import subprocess
import sys
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
        import os

        nexus_home = os.path.expanduser("~/.nexus")
        python_path = os.path.join(nexus_home, ".venv", "bin", "python")
        run_py = os.path.join(nexus_home, "nexus", "backend", "run.py")

        return f"""[Unit]
Description=Nexus Gateway
After=network-online.target

[Service]
Type=simple
ExecStart={python_path} {run_py} --host 0.0.0.0 --port 30000
Environment=NEXUS_HOME={nexus_home}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""

    def install(self) -> None:
        """注册为 systemd 服务（完整安装流程）。"""
        import os
        import shutil
        import subprocess

        nexus_home = os.path.expanduser("~/.nexus")

        # 1. 创建目录结构
        os.makedirs(nexus_home, exist_ok=True)
        os.makedirs(os.path.join(nexus_home, "logs"), exist_ok=True)

        # 2. 复制代码到 ~/.nexus/nexus/
        dest_nexus = os.path.join(nexus_home, "nexus")
        if os.path.exists(dest_nexus):
            shutil.rmtree(dest_nexus)

        # 获取项目根目录
        project_root = Path(__file__).parent.parent.parent.parent
        src_nexus = project_root / "nexus"

        # 自定义忽略函数：排除缓存和临时文件
        def _ignore_patterns(dirname, names):
            ignore = {".DS_Store", "__pycache__", ".pyc", ".pyo", ".git", ".playwright-mcp", "_temp"}
            return {n for n in names if n in ignore or n.startswith(".")}

        shutil.copytree(src_nexus, dest_nexus, ignore=_ignore_patterns)

        # 3. 创建虚拟环境
        venv_path = os.path.join(nexus_home, ".venv")
        subprocess.run(
            [sys.executable, "-m", "venv", venv_path],
            check=True,
            capture_output=True,
        )

        # 4. 安装依赖
        pip_path = os.path.join(venv_path, "bin", "pip")
        requirements = os.path.join(dest_nexus, "backend", "requirements.txt")
        subprocess.run(
            [pip_path, "install", "--upgrade", "pip"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [pip_path, "install", "-r", requirements],
            check=True,
            capture_output=True,
        )

        # 5. 生成并写入 service 文件
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
