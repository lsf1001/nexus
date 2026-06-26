"""Nexus Gateway 子命令 —— 只保留 `run`(前台 dev 模式)。

设计:产品环境后端由 Electron 拉起(在 Nexus.app/Contents/Resources/nexus-backend/),
CLI 不再提供后台启停。本子命令只用于 dev 阶段手测,直接前台绑定到当前 shell。
"""

import sys

import typer
from rich.console import Console

console = Console()
gateway_app = typer.Typer(help="前台运行 backend (dev 模式)")


@gateway_app.command("run")
def run_cmd(
    host: str = typer.Option("0.0.0.0", help="监听地址"),
    port: int = typer.Option(30000, help="监听端口"),
) -> None:
    """前台运行 gateway(等同 ``python -m nexus.backend.run``)。"""
    console.print("[green]启动 Nexus Gateway (前台, dev 模式)[/green]")
    console.print(f"地址: [cyan]{host}:{port}[/cyan]")
    console.print("[dim]Ctrl+C 退出[/dim]")

    import os
    from pathlib import Path

    # 保证 NEXUS_HOME = ~/.nexus 供后端读 models.json / nexus.db
    os.environ.setdefault("NEXUS_HOME", str(Path.home() / ".nexus"))

    import uvicorn

    uvicorn.run(
        "nexus.backend.main:app",
        host=host,
        port=port,
        log_level="info",
    )
    # uvicorn.run 阻塞,跑不到这里;显式 sys.exit 防 IDE 报 unreachable
    sys.exit(0)
