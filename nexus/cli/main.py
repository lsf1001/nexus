"""Nexus CLI 主入口。

用法:
    nexus status     # 查看 backend 是否在 30000 端口
    nexus logs       # 跟踪 backend 日志
    nexus setup      # 交互式设置向导
    nexus doctor     # 环境诊断
    nexus gateway    # 网关子命令(只含 run,前台 dev)
    nexus config     # 配置管理

设计:Nexus 产品 = DMG APP,后端随 Electron 启停,数据走 ~/.nexus/。
本 CLI 只保留**只读诊断 + dev 辅助**命令,不再提供后台服务管理
(launchd / systemd / pid 文件这套 dev 期残留全部移除)。
"""

from pathlib import Path

import typer

from .config_cmd import config_app
from .gateway import gateway_app

app = typer.Typer(
    name="nexus",
    help="Nexus - AI Gateway",
    no_args_is_help=True,
)

app.add_typer(gateway_app, name="gateway", help="网关子命令(前台 dev)")
app.add_typer(config_app, name="config", help="配置管理")


def _check_port(port: int) -> tuple[bool, str]:
    """检查端口是否在监听(只读,不启停)。

    Returns:
        (is_listening, detail): is_listening=True 时 detail 是进程信息。
    """
    import subprocess

    result = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return False, "无监听"
    # 取第一行进程信息
    lines = [ln for ln in result.stdout.splitlines() if ln and not ln.startswith("COMMAND")]
    if not lines:
        return False, "无监听"
    first = lines[0].split()
    cmd = first[0] if len(first) > 0 else "?"
    pid = first[1] if len(first) > 1 else "?"
    return True, f"{cmd} (PID: {pid})"


@app.command()
def status() -> None:
    """查看 Nexus backend 状态(查 30000 端口是否在监听)。"""
    import platform

    from rich.console import Console
    from rich.panel import Panel

    console = Console()
    running, detail = _check_port(30000)

    if running:
        console.print(
            Panel(
                f"[green]● 运行中[/green]\n\n进程: [cyan]{detail}[/cyan]\n平台: [cyan]{platform.system()}[/cyan]\n端口: [cyan]30000[/cyan]",
                title="Nexus Gateway",
                border_style="green",
            )
        )
    else:
        console.print(
            Panel(
                f"[red]● 未运行[/red]\n\n[dim]{detail}[/dim]\n\n启动方式:\n"
                "  dev  : [cyan].venv/bin/python nexus/backend/run.py[/cyan]\n"
                "  prod : 启动 [cyan]/Applications/Nexus.app[/cyan]",
                title="Nexus Gateway",
                border_style="red",
            )
        )


@app.command()
def logs(
    lines: int = typer.Option(50, "-n", "--lines", help="显示最近 N 行"),
    follow: bool = typer.Option(False, "-f", "--follow", help="实时跟踪日志"),
) -> None:
    """查看 Nexus backend 日志(读 ~/.nexus/logs/nexus.log)。"""
    from rich.console import Console

    console = Console()
    log_file = Path.home() / ".nexus" / "logs" / "nexus.log"

    if not log_file.exists():
        console.print(f"[yellow]日志文件不存在: {log_file}[/yellow]")
        return

    if follow:
        console.print("[cyan]实时跟踪日志 (Ctrl+C 退出)[/cyan]")
        console.print(f"[dim]文件: {log_file}[/dim]\n")

        with open(log_file, encoding="utf-8") as f:
            f.seek(0, 2)  # 跳到末尾
            try:
                while True:
                    line = f.readline()
                    if line:
                        console.print(line.rstrip())
                    else:
                        import time

                        time.sleep(0.5)
            except KeyboardInterrupt:
                pass
    else:
        with open(log_file, encoding="utf-8") as f:
            all_lines = f.readlines()
            tail_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines

        for line in tail_lines:
            console.print(line.rstrip())


@app.command()
def setup() -> None:
    """交互式设置向导。"""
    from .setup_cmd import run_setup

    run_setup()


@app.command()
def doctor(
    fix: bool = typer.Option(False, "--fix", help="自动修复发现的问题"),
) -> None:
    """诊断 Nexus 运行环境。"""
    from .doctor import run_doctor

    run_doctor(fix=fix)


@app.callback(invoke_without_command=True)
def main_callback() -> None:
    """Nexus Gateway - AI 助手平台。"""
    pass
