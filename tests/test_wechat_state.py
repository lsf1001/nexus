"""wechat_state 拆分模块的合法 state dir API 烟雾测试。

C4 重构后，`_active_channel` 全局 + `get_active_wechat_channel` /
`_set_active_channel` / `_clear_active_channel` 已被 ChannelRegistry
取代，对应测试一并删除。本文件保留一个最小烟雾测试，确保拆分模块路径
仍可被直接 import（替代旧的 wechat 兼容层测试）。
"""

from __future__ import annotations


def test_state_imports_via_split_module() -> None:
    """拆分模块路径直接 import 仍可加载（合法 state dir API 烟雾测试）。"""
    from nexus.backend.channels import wechat_state  # noqa: F401
