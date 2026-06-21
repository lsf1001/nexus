"""Nexus → ppt-master 集成层。

封装对 `ppt_master` 命令行工具的子进程调用,负责:
- 拼装命令行参数(--input / --output / 可选 --template)
- 用 asyncio 子进程异步执行,避免阻塞 FastAPI 事件循环
- 捕获 stdout / stderr,失败时抛出带上下文的 PPTMasterError
- 成功时返回目标 .pptx 路径
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# ppt-master 的 Python 模块入口(与 PyPI / git 仓库里的包名一致)
_PPT_MASTER_MODULE = "ppt_master"


class PPTMasterError(RuntimeError):
    """ppt-master 子进程执行失败时抛出的业务异常,带 stderr 上下文。"""


def _build_command(
    input_path: Path,
    output_path: Path,
    template_path: Path | None = None,
) -> list[str]:
    """构造 `python -m ppt_master ...` 命令行。"""
    cmd: list[str] = [
        sys.executable,
        "-m",
        _PPT_MASTER_MODULE,
        "--input",
        str(input_path),
        "--output",
        str(output_path),
    ]
    if template_path is not None:
        cmd.extend(["--template", str(template_path)])
    return cmd


async def _run_subprocess(cmd: list[str]) -> tuple[int, str, str]:
    """异步起子进程,等待结束,返回 (returncode, stdout, stderr)。"""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    return (
        proc.returncode or 0,
        stdout_bytes.decode("utf-8", errors="replace"),
        stderr_bytes.decode("utf-8", errors="replace"),
    )


async def generate_pptx(
    input_path: Path,
    output_path: Path,
    template_path: Path | None = None,
) -> Path:
    """调用 ppt-master 把 input 转成 output,返回 output_path。

    参数:
        input_path: 输入文件路径(PDF / DOCX / MD 等)或 URL(由 ppt-master 自行判定)
        output_path: 目标 .pptx 路径
        template_path: 可选模板路径,用于套用样式

    异常:
        PPTMasterError: 子进程退出码非 0,信息含 stderr
    """
    cmd = _build_command(input_path, output_path, template_path)
    returncode, _stdout, stderr = await _run_subprocess(cmd)

    if returncode != 0:
        raise PPTMasterError(f"ppt-master 失败 (exit={returncode}) input={input_path}: {stderr.strip()}")

    return output_path
