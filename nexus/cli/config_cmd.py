"""配置管理子命令。"""

import typer
from rich.console import Console
from rich.panel import Panel

from .config_store import (
    NEXUS_CONFIG_PATH,
    load_nexus_config,
    resolve_config_key,
    save_nexus_config,
    set_config_key,
)

console = Console()
config_app = typer.Typer(help="管理 Nexus 配置")


def _mask_api_key(value: str) -> str:
    """脱敏 API Key。"""
    if not isinstance(value, str) or len(value) < 8:
        return value
    return value[:4] + "****" + value[-4:]


def _print_config_tree(config: dict, prefix: str = "") -> None:
    """递归打印配置树。"""
    for key, value in config.items():
        if isinstance(value, dict):
            console.print(f"{prefix}[cyan]{key}[/cyan]:")
            _print_config_tree(value, prefix + "  ")
        elif isinstance(value, list):
            console.print(f"{prefix}[cyan]{key}[/cyan]: [dim]({len(value)} items)[/dim]")
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    name = item.get("name", item.get("id", f"[{i}]"))
                    console.print(f"{prefix}  [{i}] {name}")
        else:
            display_value = value
            if key == "api_key" and isinstance(value, str):
                display_value = _mask_api_key(value)
            console.print(f"{prefix}[cyan]{key}[/cyan]: [green]{display_value}[/green]")


@config_app.command("get")
def config_get(
    key: str = typer.Argument(..., help="配置键，如 server.port 或 models[0].api_key"),
) -> None:
    """读取配置项。"""
    config = load_nexus_config()
    value = resolve_config_key(config, key)

    if value is None:
        console.print(f"[red]配置键不存在[/red]: {key}")
        raise typer.Exit(code=1)

    if isinstance(value, str) and "api_key" in key:
        console.print(_mask_api_key(value))
    else:
        console.print(value)


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="配置键"),
    value: str = typer.Argument(..., help="配置值"),
) -> None:
    """设置配置项。"""
    config = load_nexus_config()

    # 尝试转换为数字
    try:
        typed_value = int(value)
    except ValueError:
        try:
            typed_value = float(value)
        except ValueError:
            typed_value = value

    set_config_key(config, key, typed_value)
    save_nexus_config(config)

    display_value = typed_value
    if isinstance(typed_value, str) and "api_key" in key:
        display_value = _mask_api_key(typed_value)

    console.print(f"[green]✔ 已设置[/green] [cyan]{key}[/cyan] = [green]{display_value}[/green]")


@config_app.command("list")
def config_list() -> None:
    """列出所有配置项。"""
    config = load_nexus_config()

    console.print(
        Panel(
            f"[dim]配置文件:[/dim] {NEXUS_CONFIG_PATH}",
            title="Nexus 配置",
            border_style="cyan",
        )
    )

    _print_config_tree(config)
