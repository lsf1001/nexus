"""Nexus CLI 主入口。

用法:
    nexus                  # 向后兼容，启动网关
    nexus gateway <cmd>    # 网关管理
    nexus config <cmd>     # 配置管理
    nexus doctor           # 环境诊断
    nexus setup            # 交互式设置
"""
import typer

from .gateway import gateway_app
from .config_cmd import config_app

app = typer.Typer(
    name="nexus",
    help="Nexus - AI 助手平台",
    no_args_is_help=False,
)

app.add_typer(gateway_app, name="gateway", help="管理 Nexus 网关服务")
app.add_typer(config_app, name="config", help="管理 Nexus 配置")


@app.callback(invoke_without_command=True)
def main_callback(ctx: typer.Context) -> None:
    """无子命令时默认启动网关（向后兼容）。"""
    if ctx.invoked_subcommand is None:
        from .gateway import run_gateway

        run_gateway()


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
