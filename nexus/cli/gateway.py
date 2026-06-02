"""Nexus Gateway 子命令。"""

import platform
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from .daemon import get_daemon_manager

console = Console()
gateway_app = typer.Typer(help="管理 Nexus 网关服务")


def _get_nexus_home() -> Path:
    """获取 Nexus 运行时目录。"""
    return Path.home() / ".nexus"


def _get_venv_python() -> Path:
    """获取虚拟环境的 Python 解释器。"""
    nexus_home = _get_nexus_home()
    return nexus_home / ".venv" / "bin" / "python"


def run_gateway() -> None:
    """启动网关（向前兼容：裸 nexus 命令）。"""
    nexus_home = _get_nexus_home()
    python_path = _get_venv_python()

    if not python_path.exists():
        console.print("[red]错误[/red]: 虚拟环境未找到，请运行安装脚本")
        raise typer.Exit(code=1)

    console.print("[green]启动 Nexus 网关...[/green]")

    import os

    import uvicorn

    os.environ["NEXUS_HOME"] = str(nexus_home)
    sys.path.insert(0, str(nexus_home))

    uvicorn.run(
        "nexus.backend.main:app",
        host="0.0.0.0",
        port=30000,
        log_level="info",
    )


@gateway_app.command("run")
def run_cmd(
    host: str = typer.Option("0.0.0.0", help="监听地址"),
    port: int = typer.Option(30000, help="监听端口"),
) -> None:
    """前台运行网关（开发模式）。"""
    console.print("[green]启动 Nexus 网关 (前台模式)[/green]")
    console.print(f"地址: [cyan]{host}:{port}[/cyan]")

    nexus_home = _get_nexus_home()
    python_path = _get_venv_python()

    if not python_path.exists():
        console.print("[red]错误[/red]: 虚拟环境未找到")
        raise typer.Exit(code=1)

    import os

    import uvicorn

    os.environ["NEXUS_HOME"] = str(nexus_home)
    sys.path.insert(0, str(nexus_home))

    uvicorn.run(
        "nexus.backend.main:app",
        host=host,
        port=port,
        log_level="info",
    )


@gateway_app.command("start")
def start_cmd(
    replace: bool = typer.Option(False, "--replace", help="替换已有实例"),
) -> None:
    """以后台服务方式启动网关。"""
    manager = get_daemon_manager()

    if manager.is_running() and not replace:
        console.print("[yellow]网关已在运行中[/yellow]，使用 [cyan]nexus gateway restart[/cyan] 重启")
        return

    console.print("[green]启动 Nexus 网关 (后台模式)[/green]")
    manager.start()
    console.print("[green]✔ 网关已启动[/green]")


@gateway_app.command("stop")
def stop_cmd() -> None:
    """停止网关服务。"""
    manager = get_daemon_manager()

    if not manager.is_running():
        console.print("[yellow]网关未运行[/yellow]")
        return

    console.print("[green]停止 Nexus 网关...[/green]")
    manager.stop()
    console.print("[green]✔ 网关已停止[/green]")


@gateway_app.command("restart")
def restart_cmd() -> None:
    """重启网关服务。"""
    console.print("[green]重启 Nexus 网关...[/green]")
    manager = get_daemon_manager()
    manager.restart()
    console.print("[green]✔ 网关已重启[/green]")


@gateway_app.command("status")
def status_cmd() -> None:
    """查看网关运行状态。"""
    manager = get_daemon_manager()
    pid = manager.get_pid()

    if manager.is_running():
        console.print(
            Panel(
                f"[green]● 运行中[/green]\n\nPID: [cyan]{pid}[/cyan]\n平台: [cyan]{platform.system()}[/cyan]",
                title="Nexus Gateway",
                border_style="green",
            )
        )
    else:
        console.print(
            Panel(
                "[red]● 未运行[/red]",
                title="Nexus Gateway",
                border_style="red",
            )
        )


@gateway_app.command("install")
def install_cmd() -> None:
    """注册为系统服务（launchd/systemd）。"""
    manager = get_daemon_manager()
    manager.install()
    console.print("[green]✔ 已注册为系统服务[/green]")
    console.print("使用 [cyan]nexus gateway start[/cyan] 启动服务")


@gateway_app.command("uninstall")
def uninstall_cmd() -> None:
    """移除系统服务注册。"""
    manager = get_daemon_manager()

    if manager.is_running():
        console.print("[yellow]先停止服务...[/yellow]")
        manager.stop()

    manager.uninstall()
    console.print("[green]✔ 已移除系统服务注册[/green]")
