"""CLI 顶层命令单测 — 验证 daemon 路径移除后的不变量。

WHY:2026-06 OpenClaw 定位重设计后,CLI 不再提供 launchd/systemd 启停
(install/uninstall/start/stop/restart 全部删除)。本测试守住边界:
- status 只读 lsof 30000 端口,不启停
- 不再有 ``nexus install`` 等会改写用户机器的命令
- 顶层 help 不暴露 daemon 入口
"""

from __future__ import annotations

from typer.testing import CliRunner

from nexus.cli.main import app

cli = CliRunner()


def test_top_level_help_excludes_daemon_commands() -> None:
    """顶层 help 不应再列 install / uninstall / start / stop / restart。

    WHY:daemon 启停逻辑在产品里属于 Electron APP 职责,CLI 不应有权限
    改写 ~/.nexus/nexus/ 或写 launchd plist。一旦这些命令回来,意味着
    有人把 dev 期残留逻辑复活了。
    """
    result = cli.invoke(app, ["--help"], catch_exceptions=False)
    assert result.exit_code == 0
    output = result.stdout
    for forbidden in ("install", "uninstall", "start", "stop", "restart"):
        # 不应出现作为顶级子命令(子串也可能命中 gateway 内的合法命令,
        # 这里通过"出现在 Commands 区块 + 单行"判别)。
        # 简化判别:用换行开头 + 缩进空白 + 单词的方式匹配。
        for line in output.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("─") or stripped.startswith("│"):
                continue
            # typer help 的子命令列以 "命令名   描述" 形式出现
            if stripped.startswith(forbidden + " ") or stripped == forbidden:
                # 允许 status(包含 "start" 子串) → 用更严格判断
                if forbidden == "start" and "status" in line:
                    continue
                raise AssertionError(f"顶层 help 不应暴露 daemon 命令 {forbidden!r},实际行: {line!r}")


def test_status_reads_30000_port_without_touching_daemon() -> None:
    """status 只能查 30000 端口监听,不应尝试调 daemon / launchctl / systemctl。"""
    result = cli.invoke(app, ["status"], catch_exceptions=False)
    assert result.exit_code == 0
    output = result.stdout
    # 不应在输出里出现 daemon manager 的方法痕迹
    assert "DaemonManager" not in output
    assert "launchctl" not in output
    assert "systemctl" not in output
    # 必须有"端口"或"运行中/未运行"字样
    assert ("30000" in output) or ("未运行" in output) or ("运行中" in output)


def test_gateway_subcommands_only_exposes_run() -> None:
    """``nexus gateway --help`` 只应列出 run 子命令。"""
    from nexus.cli.gateway import gateway_app

    result = cli.invoke(gateway_app, ["--help"], catch_exceptions=False)
    assert result.exit_code == 0
    output = result.stdout
    assert "run" in output
    # 这些子命令在 OpenClaw 定位下被删除,不应再出现在 gateway help 里
    for forbidden in ("start ", "stop ", "restart ", "install ", "uninstall "):
        assert forbidden not in output, f"gateway help 不应再列 {forbidden!r}"
