"""TOOLS 列表不应包含 langchain_community 文件管理工具(由 FilesystemMiddleware 接管)。"""

from nexus.backend.tools import TOOLS


def test_tools_no_legacy_file_management() -> None:
    """Nexus TOOLS 不应再含 deepagents FilesystemMiddleware 同名工具。

    deepagents 实际工具名(以 FilesystemMiddleware 为准):
    ``ls / read_file / glob / grep / write_file / edit_file``。
    此前 langchain_community 的 ``file_management.DeleteFileTool`` 等已被删除;
    本测试**正面对接 deepagents 工具集**,防止未来误回滚或重复实现。
    """
    names = {t.name for t in TOOLS if hasattr(t, "name")}
    deepagents_fs_tools = {"ls", "read_file", "glob", "grep", "write_file", "edit_file"}
    overlap = names & deepagents_fs_tools
    assert not overlap, f"Nexus TOOLS 不应重名 deepagents 文件工具(由 FilesystemMiddleware 接管): {overlap}"


def test_tools_keeps_ask_user_and_date() -> None:
    """澄清工具和日期工具保留。"""
    names = {t.name for t in TOOLS if hasattr(t, "name")}
    assert "ask_user" in names
    assert "get_current_date" in names
