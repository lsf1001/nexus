"""Nexus PPT Master 集成包。

把 hugohe3/ppt-master 作为"文档 → PPT"功能的子进程后端,通过 runner.generate_pptx 调用。
本包不直接依赖 ppt-master 的内部 API,只通过 `python -m ppt_master` 子进程边界通讯,
避免版本耦合,失败时也能在边界统一捕获。
"""

from __future__ import annotations

from .runner import PPTMasterError, generate_pptx

__all__ = ["PPTMasterError", "generate_pptx"]
