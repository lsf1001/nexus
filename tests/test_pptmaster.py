"""PPT Master 集成测试 — 验证 nexus ↔ ppt-master 的 CLI 与 runner 走通(不实际起子进程)。

仅覆盖集成层:CLI 参数透传、subprocess 命令拼装、stdout/stderr 异常捕获。
真实文档 → .pptx 的生成留给上层(七七)验证。
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from nexus.cli.main import app

# === CLI 测试辅助 ===

cli = CliRunner()


# === 1. runner: subprocess 真的被调起 ===


@pytest.mark.asyncio
async def test_generate_pptx_actually_invokes_subprocess(tmp_path: Path) -> None:
    """runner 必须真起子进程 `python -m ppt_master --input ... --output ...`,并把 stdout/stderr 接回。"""
    from nexus.pptmaster import generate_pptx

    in_file = tmp_path / "src.pdf"
    out_file = tmp_path / "dst.pptx"

    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)) as mock_exec:
        result = await generate_pptx(in_file, out_file, None)

    assert result == out_file
    mock_exec.assert_awaited_once()
    cmd = mock_exec.await_args.args
    # 必须是 python -m ppt_master
    assert cmd[0] == sys.executable
    assert cmd[1:3] == ("-m", "ppt_master")
    # --input / --output 必须出现且值正确
    assert "--input" in cmd and str(in_file) in cmd
    assert "--output" in cmd and str(out_file) in cmd
    # 不带 --template
    assert "--template" not in cmd


@pytest.mark.asyncio
async def test_generate_pptx_passes_template_flag(tmp_path: Path) -> None:
    """传入 template 时,命令必须含 --template。"""
    from nexus.pptmaster import generate_pptx

    in_file = tmp_path / "src.md"
    out_file = tmp_path / "dst.pptx"
    tpl_file = tmp_path / "base.pptx"

    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)) as mock_exec:
        await generate_pptx(in_file, out_file, tpl_file)

    cmd = mock_exec.await_args.args
    assert "--template" in cmd and str(tpl_file) in cmd


# === 2. runner: 异常路径 — subprocess 失败时抛错,带 stderr 上下文 ===


@pytest.mark.asyncio
async def test_generate_pptx_raises_on_nonzero_exit(tmp_path: Path) -> None:
    """子进程非零退出 → 抛 PPTMasterError,错误信息含 stderr。"""
    from nexus.pptmaster import generate_pptx
    from nexus.pptmaster.runner import PPTMasterError

    in_file = tmp_path / "src.pdf"
    out_file = tmp_path / "dst.pptx"

    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(b"", b"PDF parse failed"))
    mock_proc.returncode = 1

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
        with pytest.raises(PPTMasterError, match="PDF parse failed"):
            await generate_pptx(in_file, out_file, None)


# === 3. CLI: `nexus ppt <input>` 走通 ===


def test_cli_ppt_invokes_runner_with_default_output(tmp_path: Path) -> None:
    """`nexus ppt <input>` 必须调起 generate_pptx(input, input.with_suffix('.pptx'), None)。"""
    in_file = tmp_path / "doc.pdf"
    expected_out = in_file.with_suffix(".pptx")

    with patch("nexus.cli.main.generate_pptx") as mock_gen:
        result = cli.invoke(app, ["ppt", str(in_file)])

    assert result.exit_code == 0, result.output
    mock_gen.assert_called_once()
    args = mock_gen.call_args.args
    assert args[0] == in_file
    assert args[1] == expected_out
    assert args[2] is None


def test_cli_ppt_passes_output_and_template(tmp_path: Path) -> None:
    """`--output` / `--template` 必须透传到 generate_pptx。"""
    in_file = tmp_path / "doc.pdf"
    out_file = tmp_path / "custom.pptx"
    tpl_file = tmp_path / "tpl.pptx"

    with patch("nexus.cli.main.generate_pptx") as mock_gen:
        result = cli.invoke(
            app,
            ["ppt", str(in_file), "--output", str(out_file), "--template", str(tpl_file)],
        )

    assert result.exit_code == 0, result.output
    assert mock_gen.call_args.args == (in_file, out_file, tpl_file)


def test_cli_ppt_propagates_runner_error(tmp_path: Path) -> None:
    """runner 抛错时 CLI 退出码 != 0,并向用户报告。"""
    in_file = tmp_path / "doc.pdf"
    with patch("nexus.cli.main.generate_pptx", side_effect=RuntimeError("boom")):
        result = cli.invoke(app, ["ppt", str(in_file)])

    assert result.exit_code != 0
    assert "boom" in result.output or "失败" in result.output
