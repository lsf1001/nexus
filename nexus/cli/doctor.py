"""诊断工具。"""

import socket
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from .config_store import NEXUS_CONFIG_PATH, NEXUS_MODELS_PATH, load_nexus_config
from .daemon import get_daemon_manager

console = Console()


class CheckStatus(Enum):
    """检查结果状态。"""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass
class CheckResult:
    """检查结果。"""

    name: str
    status: CheckStatus
    message: str
    fixable: bool = False


def _check_python_version() -> CheckResult:
    """检查 Python 版本。"""
    version = sys.version_info
    if version >= (3, 11):
        return CheckResult("Python 版本", CheckStatus.PASS, f"Python {version.major}.{version.minor}.{version.micro}")
    return CheckResult(
        "Python 版本", CheckStatus.FAIL, f"Python {version.major}.{version.minor}.{version.micro} (需要 >= 3.11)"
    )


def _check_nexus_home() -> CheckResult:
    """检查 NEXUS_HOME 目录。"""
    nexus_home = Path.home() / ".nexus"
    if nexus_home.exists():
        return CheckResult("NEXUS_HOME", CheckStatus.PASS, str(nexus_home))
    return CheckResult("NEXUS_HOME", CheckStatus.FAIL, f"{nexus_home} 不存在", fixable=True)


def _check_venv() -> CheckResult:
    """检查虚拟环境。"""
    nexus_home = Path.home() / ".nexus"
    venv_python = nexus_home / ".venv" / "bin" / "python"
    if venv_python.exists():
        return CheckResult("虚拟环境", CheckStatus.PASS, str(venv_python))
    return CheckResult("虚拟环境", CheckStatus.FAIL, "虚拟环境不存在", fixable=True)


def _check_dependencies() -> CheckResult:
    """检查核心依赖。"""
    nexus_home = Path.home() / ".nexus"
    venv_python = nexus_home / ".venv" / "bin" / "python"

    if not venv_python.exists():
        return CheckResult("核心依赖", CheckStatus.FAIL, "虚拟环境不存在")

    try:
        result = subprocess.run(
            [str(venv_python), "-c", "import fastapi, uvicorn, typer, rich"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return CheckResult("核心依赖", CheckStatus.PASS, "fastapi, uvicorn, typer, rich")
        return CheckResult("核心依赖", CheckStatus.FAIL, "部分依赖缺失")
    except Exception as e:
        return CheckResult("核心依赖", CheckStatus.FAIL, str(e))


def _check_config_file() -> CheckResult:
    """检查配置文件。"""
    if NEXUS_CONFIG_PATH.exists():
        return CheckResult("配置文件", CheckStatus.PASS, str(NEXUS_CONFIG_PATH))
    if NEXUS_MODELS_PATH.exists():
        return CheckResult("配置文件", CheckStatus.WARN, f"使用旧配置 {NEXUS_MODELS_PATH}")
    return CheckResult("配置文件", CheckStatus.FAIL, "配置文件不存在", fixable=True)


def _check_api_key() -> CheckResult:
    """检查 API Key 配置。"""
    config = load_nexus_config()
    models = config.get("models", [])
    active_model = next((m for m in models if m.get("is_active")), None)

    if active_model and active_model.get("api_key"):
        return CheckResult("API Key", CheckStatus.PASS, f"{active_model.get('name', 'default')}")
    return CheckResult("API Key", CheckStatus.FAIL, "未配置 API Key", fixable=True)


def _check_port_available() -> CheckResult:
    """检查端口是否可用。"""
    config = load_nexus_config()
    port = config.get("server", {}).get("port", 30000)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("localhost", port))
            return CheckResult(f"端口 {port}", CheckStatus.PASS, "可用")
        except OSError:
            return CheckResult(f"端口 {port}", CheckStatus.WARN, "已被占用")


def _check_gateway_status() -> CheckResult:
    """检查网关运行状态。"""
    try:
        manager = get_daemon_manager()
        pid = manager.get_pid()
        if manager.is_running():
            return CheckResult("网关状态", CheckStatus.PASS, f"运行中 (PID: {pid})")
        return CheckResult("网关状态", CheckStatus.WARN, "未运行")
    except Exception as e:
        return CheckResult("网关状态", CheckStatus.WARN, f"无法检查: {e}")


def _check_frontend_build() -> CheckResult:
    """检查前端构建。"""
    nexus_home = Path.home() / ".nexus"
    frontend_dist = nexus_home / "frontend" / "dist"
    if frontend_dist.exists():
        return CheckResult("前端构建", CheckStatus.PASS, str(frontend_dist))
    return CheckResult("前端构建", CheckStatus.WARN, "前端未构建")


def _check_logs_directory() -> CheckResult:
    """检查日志目录。"""
    nexus_home = Path.home() / ".nexus"
    logs_dir = nexus_home / "logs"
    if logs_dir.exists():
        return CheckResult("日志目录", CheckStatus.PASS, str(logs_dir))
    return CheckResult("日志目录", CheckStatus.WARN, "日志目录不存在", fixable=True)


def _print_check_result(result: CheckResult) -> None:
    """打印检查结果。"""
    status_icon = {
        CheckStatus.PASS: "[green]✔[/green]",
        CheckStatus.WARN: "[yellow]⚠[/yellow]",
        CheckStatus.FAIL: "[red]✖[/red]",
    }
    icon = status_icon.get(result.status, "?")
    console.print(f"{icon} {result.name}: {result.message}")


def _attempt_fixes(results: list[CheckResult]) -> None:
    """尝试自动修复问题。"""
    fixable = [r for r in results if r.fixable]
    if not fixable:
        return

    console.print(f"\n[cyan]尝试修复 {len(fixable)} 个问题...[/cyan]")

    for result in fixable:
        if result.name == "NEXUS_HOME":
            nexus_home = Path.home() / ".nexus"
            nexus_home.mkdir(parents=True, exist_ok=True)
            console.print(f"[green]✔ 已创建 {nexus_home}[/green]")

        elif result.name == "虚拟环境":
            console.print("[yellow]请运行安装脚本重新创建虚拟环境[/yellow]")

        elif result.name == "配置文件":
            from .config_store import get_default_config, save_nexus_config

            config = get_default_config()
            save_nexus_config(config)
            console.print("[green]✔ 已创建默认配置[/green]")

        elif result.name == "API Key":
            console.print("[yellow]请运行 [cyan]nexus setup[/cyan] 配置 API Key[/yellow]")

        elif result.name == "日志目录":
            nexus_home = Path.home() / ".nexus"
            logs_dir = nexus_home / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            console.print(f"[green]✔ 已创建 {logs_dir}[/green]")


def run_doctor(fix: bool = False) -> None:
    """运行环境诊断。"""
    console.print(
        Panel(
            "[bold cyan]Nexus 环境诊断[/bold cyan]",
            border_style="cyan",
        )
    )

    checks = [
        _check_python_version,
        _check_nexus_home,
        _check_venv,
        _check_dependencies,
        _check_config_file,
        _check_api_key,
        _check_port_available,
        _check_gateway_status,
        _check_frontend_build,
        _check_logs_directory,
    ]

    results: list[CheckResult] = []
    for check in checks:
        try:
            result = check()
            results.append(result)
            _print_check_result(result)
        except Exception as e:
            results.append(CheckResult("检查", CheckStatus.FAIL, str(e)))

    # 统计
    pass_count = sum(1 for r in results if r.status == CheckStatus.PASS)
    warn_count = sum(1 for r in results if r.status == CheckStatus.WARN)
    fail_count = sum(1 for r in results if r.status == CheckStatus.FAIL)

    console.print(
        f"\n[green]通过: {pass_count}[/green]  [yellow]警告: {warn_count}[/yellow]  [red]失败: {fail_count}[/red]"
    )

    # 自动修复
    failed = [r for r in results if r.status == CheckStatus.FAIL]
    if failed and fix:
        _attempt_fixes(failed)
