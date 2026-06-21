"""Nexus CLI 主入口。

用法:
    nexus install    # 安装/注册 launchd（常驻）
    nexus start      # 启动服务
    nexus stop       # 停止服务
    nexus restart    # 重启服务
    nexus status     # 查看状态
    nexus logs       # 查看日志
    nexus uninstall  # 卸载服务
    nexus setup      # 交互式设置向导
    nexus doctor     # 环境诊断
    nexus gateway    # 网关子命令（向后兼容）
"""

from pathlib import Path

import typer

from nexus.pptmaster import generate_pptx

from .config_cmd import config_app
from .gateway import gateway_app

app = typer.Typer(
    name="nexus",
    help="Nexus - AI Gateway",
    no_args_is_help=True,
)

app.add_typer(gateway_app, name="gateway", help="网关子命令（向后兼容）")
app.add_typer(config_app, name="config", help="配置管理")


@app.command()
def install() -> None:
    """注册为系统服务（launchd/systemd），实现开机自启和常驻运行。"""
    from rich.console import Console

    from .daemon import get_daemon_manager

    console = Console()
    console.print("[cyan]注册系统服务...[/cyan]")

    manager = get_daemon_manager()
    manager.install()

    console.print("[green]✔ 已注册为系统服务[/green]")
    console.print("使用 [cyan]nexus start[/cyan] 启动服务")


@app.command()
def uninstall() -> None:
    """移除系统服务注册。"""
    from rich.console import Console

    from .daemon import get_daemon_manager

    console = Console()
    manager = get_daemon_manager()

    if manager.is_running():
        console.print("[yellow]先停止服务...[/yellow]")
        manager.stop()

    manager.uninstall()
    console.print("[green]✔ 已移除系统服务注册[/green]")


@app.command()
def start(
    replace: bool = typer.Option(False, "--replace", help="替换已有实例"),
) -> None:
    """启动 Nexus Gateway 服务（后台运行）。"""
    from rich.console import Console

    from .daemon import get_daemon_manager

    console = Console()
    manager = get_daemon_manager()

    if manager.is_running():
        if replace:
            console.print("[yellow]停止旧实例...[/yellow]")
            manager.stop()
        else:
            console.print(f"[yellow]网关已在运行中 (PID: {manager.get_pid()})[/yellow]")
            console.print("使用 [cyan]nexus restart[/cyan] 重启")
            return

    manager.start()
    console.print(f"[green]✔ 网关已启动 (PID: {manager.get_pid()})[/green]")


@app.command()
def stop() -> None:
    """停止 Nexus Gateway 服务。"""
    from rich.console import Console

    from .daemon import get_daemon_manager

    console = Console()
    manager = get_daemon_manager()

    if not manager.is_running():
        console.print("[yellow]网关未运行[/yellow]")
        return

    manager.stop()
    console.print("[green]✔ 网关已停止[/green]")


@app.command()
def restart() -> None:
    """重启 Nexus Gateway 服务。"""
    from rich.console import Console

    from .daemon import get_daemon_manager

    console = Console()
    manager = get_daemon_manager()
    manager.restart()
    console.print("[green]✔ 网关已重启[/green]")


@app.command()
def status() -> None:
    """查看 Nexus Gateway 运行状态。"""
    import platform

    from rich.console import Console
    from rich.panel import Panel

    from .daemon import get_daemon_manager

    console = Console()
    manager = get_daemon_manager()
    pid = manager.get_pid()

    if manager.is_running():
        console.print(
            Panel(
                f"[green]● 运行中[/green]\n\nPID: [cyan]{pid}[/cyan]\n平台: [cyan]{platform.system()}[/cyan]\n端口: [cyan]30000[/cyan]",
                title="Nexus Gateway",
                border_style="green",
            )
        )
    else:
        console.print(
            Panel(
                "[red]● 未运行[/red]\n\n使用 [cyan]nexus start[/cyan] 启动服务",
                title="Nexus Gateway",
                border_style="red",
            )
        )


@app.command()
def logs(
    lines: int = typer.Option(50, "-n", "--lines", help="显示最近 N 行"),
    follow: bool = typer.Option(False, "-f", "--follow", help="实时跟踪日志"),
) -> None:
    """查看 Nexus Gateway 日志。"""
    from pathlib import Path

    from rich.console import Console

    console = Console()
    nexus_home = Path.home() / ".nexus"
    log_file = nexus_home / "logs" / "stdout.log"

    if not log_file.exists():
        console.print(f"[yellow]日志文件不存在: {log_file}[/yellow]")
        return

    if follow:
        # 实时跟踪
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
        # 显示最后 N 行
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


@app.command()
def ppt(
    input_path: Path = typer.Argument(..., help="输入文件路径 (PDF/DOCX/MD) 或 URL"),
    output: Path | None = typer.Option(None, "--output", "-o", help="输出 .pptx 路径,默认同目录同名 .pptx"),
    template: Path | None = typer.Option(None, "--template", "-t", help="可选模板路径"),
) -> None:
    """把 PDF / DOCX / MD / URL 转成原生可编辑 .pptx(由 ppt-master 后端执行)。"""
    import asyncio

    from rich.console import Console

    console = Console()
    output_path: Path = output if output is not None else input_path.with_suffix(".pptx")

    console.print(f"[cyan]生成 PPT:[/cyan] {input_path} -> {output_path}")

    try:
        asyncio.run(generate_pptx(input_path, output_path, template))
    except Exception as e:
        console.print(f"[red]生成失败:[/red] {e}")
        raise typer.Exit(code=1) from e

    console.print(f"[green]✔ 已生成:[/green] {output_path}")


@app.callback(invoke_without_command=True)
def main_callback() -> None:
    """Nexus Gateway - AI 助手平台。"""
    pass
