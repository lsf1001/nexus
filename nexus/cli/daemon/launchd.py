"""macOS launchd 守护进程管理。"""

import re
import subprocess
import sys
from pathlib import Path

from .base import DaemonManager

LAUNCHD_LABEL = "ai.nexus.gateway"
LAUNCHD_DIR = Path.home() / "Library" / "LaunchAgents"


class LaunchdManager(DaemonManager):
    """macOS launchd 守护进程管理器。"""

    def _plist_path(self) -> Path:
        """获取 plist 文件路径。"""
        return LAUNCHD_DIR / f"{LAUNCHD_LABEL}.plist"

    def _generate_plist(self) -> str:
        """生成 plist 内容。"""
        import os

        nexus_home = os.path.expanduser("~/.nexus")
        python_path = os.path.join(nexus_home, ".venv", "bin", "python")
        run_py = os.path.join(nexus_home, "nexus", "backend", "run.py")

        return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LAUNCHD_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_path}</string>
        <string>{run_py}</string>
        <string>--host</string>
        <string>0.0.0.0</string>
        <string>--port</string>
        <string>30000</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{nexus_home}/logs/stdout.log</string>
    <key>StandardErrorPath</key>
    <string>{nexus_home}/logs/stderr.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>NEXUS_HOME</key>
        <string>{nexus_home}</string>
    </dict>
</dict>
</plist>
"""

    def install(self) -> None:
        """注册为 launchd 服务（完整安装流程）。"""
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

        # 获取项目根目录（nexus/ 的父目录）
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

        # 5. 生成并写入 plist
        LAUNCHD_DIR.mkdir(parents=True, exist_ok=True)
        plist_path = self._plist_path()
        plist_content = self._generate_plist()
        plist_path.write_text(plist_content, encoding="utf-8")

    def uninstall(self) -> None:
        """移除 launchd 服务。"""
        plist_path = self._plist_path()
        if plist_path.exists():
            try:
                subprocess.run(
                    ["launchctl", "unload", str(plist_path)],
                    capture_output=True,
                )
            except Exception:
                pass
            plist_path.unlink()

    def start(self) -> None:
        """启动服务。"""
        plist_path = self._plist_path()
        if not plist_path.exists():
            self.install()

        subprocess.run(
            ["launchctl", "load", str(plist_path)],
            capture_output=True,
            check=True,
        )

    def stop(self) -> None:
        """停止服务。"""
        plist_path = self._plist_path()
        if plist_path.exists():
            subprocess.run(
                ["launchctl", "unload", str(plist_path)],
                capture_output=True,
            )

    def restart(self) -> None:
        """重启服务。"""
        self.stop()
        self.start()

    def is_running(self) -> bool:
        """检查服务是否运行中。"""
        pid = self.get_pid()
        return pid is not None and pid > 0

    def get_pid(self) -> int | None:
        """获取服务 PID。"""
        try:
            result = subprocess.run(
                ["launchctl", "list", LAUNCHD_LABEL],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                match = re.search(r'"PID"\s*=\s*(\d+)', result.stdout)
                if match:
                    return int(match.group(1))
        except Exception:
            pass
        return None
