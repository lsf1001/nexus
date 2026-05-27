"""交互式设置向导。"""
import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

from .config_store import (
    load_nexus_config,
    save_nexus_config,
    get_default_config,
    NEXUS_CONFIG_PATH,
    NEXUS_MODELS_PATH,
)
from .daemon import get_daemon_manager

console = Console()


def _prompt_api_key() -> str:
    """提示输入 API Key（隐藏输入）。"""
    return typer.prompt("请输入 MiniMax API Key", hide_input=True)


def _prompt_port() -> int:
    """提示输入端口号。"""
    port_str = typer.prompt("服务端口", default="30000")
    try:
        port = int(port_str)
        if 1 <= port <= 65535:
            return port
    except ValueError:
        pass
    console.print("[yellow]无效的端口号，使用默认值 30000[/yellow]")
    return 30000


def _prompt_install_daemon() -> bool:
    """询问是否注册为系统服务。"""
    return Confirm.ask("是否注册为开机自启的系统服务？", default=True)


def _migrate_models_json() -> dict | None:
    """迁移旧的 models.json 配置。"""
    if NEXUS_MODELS_PATH.exists():
        try:
            import json
            with open(NEXUS_MODELS_PATH, encoding="utf-8") as f:
                models_data = json.load(f)
            return models_data.get("models", [])
        except (json.JSONDecodeError, OSError):
            pass
    return None


def run_setup() -> None:
    """交互式设置向导主流程。"""
    console.print(
        Panel(
            "[bold cyan]Nexus 设置向导[/bold cyan]\n\n"
            "本向导将引导你完成 Nexus 的初始配置。",
            title="欢迎",
            border_style="cyan",
        )
    )

    # 检查是否已有配置
    if NEXUS_CONFIG_PATH.exists():
        console.print(f"[yellow]检测到已有配置文件: {NEXUS_CONFIG_PATH}[/yellow]")
        if not Confirm.ask("是否覆盖现有配置？", default=False):
            console.print("[green]设置向导已取消[/green]")
            return

    # 1. 选择模型提供商
    console.print("\n[cyan]步骤 1/4: 选择模型提供商[/cyan]")
    console.print("当前支持: MiniMax (兼容 OpenAI API)")

    # 2. 输入 API Key
    console.print("\n[cyan]步骤 2/4: 配置 API Key[/cyan]")
    api_key = _prompt_api_key()

    if not api_key:
        console.print("[red]API Key 不能为空[/red]")
        raise typer.Exit(code=1)

    # 3. 配置端口
    console.print("\n[cyan]步骤 3/4: 配置服务端口[/cyan]")
    port = _prompt_port()

    # 4. 是否注册为系统服务
    console.print("\n[cyan]步骤 4/4: 系统服务注册[/cyan]")
    install_daemon = _prompt_install_daemon()

    # 生成配置
    config = get_default_config()
    config["server"]["port"] = port
    config["models"][0]["api_key"] = api_key

    # 迁移旧的 models.json
    migrated_models = _migrate_models_json()
    if migrated_models:
        console.print(f"[green]已迁移旧配置: {len(migrated_models)} 个模型[/green]")
        # 更新第一个模型的 API Key
        if migrated_models:
            migrated_models[0]["api_key"] = api_key
        config["models"] = migrated_models

    # 保存配置
    save_nexus_config(config)
    console.print(f"\n[green]✔ 配置已保存到 {NEXUS_CONFIG_PATH}[/green]")

    # 注册系统服务
    if install_daemon:
        console.print("\n[cyan]注册系统服务...[/cyan]")
        try:
            manager = get_daemon_manager()
            manager.install()
            console.print("[green]✔ 系统服务已注册[/green]")
            console.print("使用 [cyan]nexus gateway start[/cyan] 启动服务")
        except Exception as e:
            console.print(f"[yellow]注册系统服务失败: {e}[/yellow]")
            console.print("你可以稍后运行 [cyan]nexus gateway install[/cyan] 手动注册")

    # 完成
    console.print(
        Panel(
            "[bold green]设置完成！[/bold green]\n\n"
            "使用方式:\n"
            "  [cyan]nexus[/cyan]              # 启动网关（向前兼容）\n"
            "  [cyan]nexus gateway run[/cyan]  # 前台运行\n"
            "  [cyan]nexus gateway start[/cyan] # 后台启动\n"
            "  [cyan]nexus config list[/cyan]  # 查看配置\n",
            title="完成",
            border_style="green",
        )
    )
