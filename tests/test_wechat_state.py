"""wechat_state 模块导入契约测试。

C4 重构后,模块仅保留 session dir / context token 等账户状态;
_active_channel 全局 + get/set/clear 三个函数已迁出。
本测试验证模块仍可正常 import,无 dead import。
"""

from __future__ import annotations


def test_state_imports_via_split_module() -> None:
    """拆分模块路径直接 import 仍可加载（合法 state dir API 烟雾测试）。"""
    from nexus.backend.channels import wechat_state  # noqa: F401
