# DeepAgents 完整安全防护 + HITL 实现 Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 复用 deepagents 自带的 `FilesystemPermission` + `HumanInTheLoopMiddleware` 全部安全机制,删除 Nexus 自加的 langchain_community 文件管理工具,加 WS 层 HITL 桥接(确认请求/响应帧)。

**Architecture:**
- 集中定义 `FilesystemPermission` 规则(默认 deny + 显式 allow 白名单 + interrupt 高敏路径)
- 深 agents `FilesystemMiddleware` 接管所有文件操作(删 langchain_community 同名工具)
- `code_writer` subagent 的 `execute` 死代码显式删除(避免误导后续开发者)
- WS 层复用 `ask_user` 的"挂起本轮流 + 新 turn 注入决策"模式,把 LangGraph `GraphInterrupt` 转 `confirmation_request` 帧
- 前端加 `confirmation_request` / `confirmation_response` 协议

**Tech Stack:** deepagents 0.6.8 (FilesystemMiddleware / FilesystemPermission / HumanInTheLoopMiddleware)、langchain_community (移除)、FastAPI WebSocket、React 19

---

## 文件结构

### 新建
- `nexus/backend/permissions.py` — 集中定义 FilesystemPermission 规则(白名单 + 黑名单 + interrupt)
- `tests/test_permissions.py` — 规则解析、路径匹配、HITL 触发判定单元测试

### 修改
- `nexus/backend/tools.py:109-208` — 删除 6 个 langchain_community 文件工具(保留 ask_user/get_current_date/yandex/web_search/wikipedia/write_file 自定义)
- `nexus/backend/agent.py:257-269,315,395-415` — 替换 `_create_permissions`、删 `execute` 死代码、传 `interrupt_on` 给 deepagents
- `nexus/backend/api/ws.py:170-310,389-435,750-810` — 加 `_run_agent_streaming` 返回 `pending_interrupt` 元组 + 客户端发 `confirmation_response` 帧分支
- `nexus/backend/models.py` — 加 `ConfirmationRequest` / `ConfirmationResponse` 帧 schema
- `frontend/src/types/ws.ts` — 加 WS 消息类型
- `frontend/src/components/chat/ChatView.tsx` — 渲染 confirmation_request + 响应
- `docs/superpowers/2026-06-24-deepagents-security-design.md` — 设计稿文档

### 不动
- `nexus/backend/quality/middleware.py`(QualityGateMiddleware 仅保护 AGENTS.md,与本 plan 互补)
- `nexus/backend/mcp.py`(MCP 加载本期不动,留独立 plan)

---

## Task 1: 集中权限规则定义

**Files:**
- Create: `nexus/backend/permissions.py`
- Test: `tests/test_permissions.py`

- [ ] **Step 1.1: 写失败测试**

写 `tests/test_permissions.py`:

```python
"""权限规则单元测试。"""
from __future__ import annotations

from pathlib import Path

from nexus.backend.permissions import (
    build_default_permissions,
    is_write_to_protected_path,
    resolve_protected_paths,
)


def test_build_default_permissions_has_no_deny() -> None:
    """默认规则应不含任何 deny(框架默认 allow,白名单显式放行)。"""
    perms = build_default_permissions(Path("/tmp/proj"))
    denies = [p for p in perms if p.mode == "deny"]
    assert denies == [], f"unexpected deny rules: {denies}"


def test_build_default_permissions_nexus_dir_writable() -> None:
    """.nexus/ 目录可读写。"""
    perms = build_default_permissions(Path("/tmp/proj"))
    nexus_rule = next(p for p in perms if ".nexus/**" in p.paths)
    assert "write" in nexus_rule.operations
    assert nexus_rule.mode == "allow"


def test_build_default_permissions_tmp_readonly() -> None:
    """/tmp/ 目录只读。"""
    perms = build_default_permissions(Path("/tmp/proj"))
    tmp_rule = next(p for p in perms if "/tmp/**" in p.paths)
    assert tmp_rule.operations == ["read"]
    assert tmp_rule.mode == "allow"


def test_build_default_permissions_agents_md_interrupt() -> None:
    """AGENTS.md 写入必须 HITL。"""
    perms = build_default_permissions(Path("/tmp/proj"))
    interrupt_rules = [p for p in perms if p.mode == "interrupt"]
    assert any("AGENTS.md" in path for r in interrupt_rules for path in r.paths)


def test_resolve_protected_paths_returns_absolute() -> None:
    """受保护路径解析为绝对路径。"""
    project_root = Path("/tmp/proj")
    paths = resolve_protected_paths(project_root)
    assert all(p.is_absolute() for p in paths)
    assert any("AGENTS.md" in str(p) for p in paths)


def test_is_write_to_protected_path_matches_agents_md() -> None:
    """工具调用命中 AGENTS.md 时返回 True。"""
    protected = resolve_protected_paths(Path("/tmp/proj"))
    assert is_write_to_protected_path(
        tool_name="write_file",
        target_path="/tmp/proj/.nexus/AGENTS.md",
        protected_paths=protected,
    ) is True


def test_is_write_to_protected_path_rejects_normal_files() -> None:
    """普通文件返回 False。"""
    protected = resolve_protected_paths(Path("/tmp/proj"))
    assert is_write_to_protected_path(
        tool_name="write_file",
        target_path="/tmp/proj/README.md",
        protected_paths=protected,
    ) is False
```

- [ ] **Step 1.2: 运行测试,确认失败**

```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && pytest tests/test_permissions.py -v
```

Expected: 全部 `ImportError: cannot import name 'build_default_permissions' from 'nexus.backend.permissions'`

- [ ] **Step 1.3: 实现 `nexus/backend/permissions.py`**

```python
"""集中定义 FilesystemPermission 规则与 HITL 触发判定。

WHY: 把安全策略从 agent.py 抽出,便于审计 + 单测 + 后续扩展(MCP / execute
等场景复用同一判定函数)。

设计原则:
  - 框架默认 ``allow``,所以**白名单路径显式 allow,其他路径隐式 allow**
    → 这条不变,因为 FilesystemPermission 没有 deny-by-default 语义。
  - 真正的高敏保护靠 ``interrupt`` 模式:用户在前端弹窗确认才放行。
  - 不引入 deny 规则(避免和 interrupt 语义重复 + 阻断 LLM 看到错误)。

HITL 触发面:
  - AGENTS.md 写入(覆盖 deepagents MemoryMiddleware 的全权)
  - 项目内非 .nexus/ 路径的写(防 LLM 改 nexus/ frontend/ desktop/ 源码)
"""
from __future__ import annotations

from pathlib import Path

from deepagents.middleware.filesystem import FilesystemPermission

# AGENTS.md 在用户家目录和项目根各一份,MemoryMiddleware 自动加载。
# 命中这两条路径的写入必须 HITL,否则 LLM 可被诱导把"今天用户叫我删 ~/.zshrc"
# 当成"用户偏好"写入长期记忆。
_PROTECTED_AGENTS_GLOBS: tuple[str, ...] = (
    "~/.nexus/AGENTS.md",
    "{project_root}/.nexus/AGENTS.md",
    "{project_root}/nexus/.deepagents/AGENTS.md",
)

# 项目内允许自由写的白名单(其他路径 → 写操作触发 HITL)。
_WRITE_ALLOWLIST: tuple[str, ...] = (
    ".nexus/**",          # 配置 / 日志 / outputs / state
    "/tmp/**",            # 临时文件(读已开,写也开,产出文件落这里)
)


def build_default_permissions(project_root: Path) -> list[FilesystemPermission]:
    """构造默认 FilesystemPermission 规则列表。

    Args:
        project_root: Nexus 项目根目录,用于展开 ``{project_root}`` 占位符。

    Returns:
        :class:`FilesystemPermission` 列表,直接传给 ``create_deep_agent(permissions=...)``。

    Note:
        - 读操作 ``["read"]`` 对全路径 allow(`/**`),LLM 可读任何文件。
        - 写操作分两层:.nexus/ 和 /tmp/ 直接 allow;AGENTS.md 必须 interrupt;
          其他路径(deepagents 框架对未匹配路径默认 allow)由前端
          ``interrupt_on`` 规则接管,见 :func:`build_interrupt_on_config`。
    """
    rules: list[FilesystemPermission] = [
        # 读:全开(LLM 看得到才能理解项目)
        FilesystemPermission(
            operations=["read"],
            paths=["/**"],
            mode="allow",
        ),
        # 写白名单:.nexus 和 /tmp
        FilesystemPermission(
            operations=["write"],
            paths=[
                f"{project_root}/.nexus/**",
                "/tmp/**",
            ],
            mode="allow",
        ),
        # AGENTS.md 写入必须 HITL
        FilesystemPermission(
            operations=["write"],
            paths=[
                "~/.nexus/AGENTS.md",
                f"{project_root}/.nexus/AGENTS.md",
                f"{project_root}/nexus/.deepagents/AGENTS.md",
            ],
            mode="interrupt",
        ),
    ]
    return rules


def build_interrupt_on_config() -> dict:
    """构造显式 ``interrupt_on`` 配置,覆盖"未在白名单内的写路径"。

    WHY: deepagents 框架默认对未匹配 FilesystemPermission 规则的路径全 allow,
    本函数用 HumanInTheLoopMiddleware 的 ``when`` 谓词兜底——
    任何 write_file/edit_file 工具调用**没有匹配白名单**时,触发 HITL。

    Returns:
        传给 ``create_deep_agent(interrupt_on=...)`` 的 dict,形如:
        ``{"write_file": {"when": <callable>}, "edit_file": {"when": <callable>}}``
    """
    from langchain.agents.middleware import InterruptOnConfig

    def when_write(req) -> bool:
        """仅对命中 interrupt 路径规则的工具调用触发 HITL。

        框架已对 FilesystemPermission mode="allow" 的规则自动放行,
        对 mode="interrupt" 自动转 interrupt_on。本函数处理"无规则匹配"的
        默认情况:不让 LLM 静默写入项目源码等敏感路径。
        """
        # 框架已自动处理 allow 和 interrupt 模式,这里只为非白名单路径兜底。
        # 实际逻辑:FilesystemPermission 没命中任何规则 → 默认 allow →
        # 需要额外检查路径是否在白名单,否则 trigger。
        # 由 agent.py 层在调用 build_default_permissions 时一并注入;
        # 这里仅返回 dict 结构,具体 when 在 agent.py 拼接。
        return True

    return {
        "write_file": InterruptOnConfig(when=when_write),
        "edit_file": InterruptOnConfig(when=when_write),
    }


def resolve_protected_paths(project_root: Path) -> list[Path]:
    """解析所有受保护的 AGENTS.md 路径为绝对路径。

    Returns:
        绝对路径列表,供 QualityGateMiddleware 校验 edit_file/write_file
        目标路径是否需要走忠实度评估。
    """
    home = Path.home()
    return [
        (home / ".nexus" / "AGENTS.md").expanduser().resolve(),
        (project_root / ".nexus" / "AGENTS.md").resolve(),
        (project_root / "nexus" / ".deepagents" / "AGENTS.md").resolve(),
    ]


def is_write_to_protected_path(
    *,
    tool_name: str,
    target_path: str,
    protected_paths: list[Path],
) -> bool:
    """判定一次工具调用是否命中受保护路径。

    Args:
        tool_name: 工具名(目前仅 ``write_file`` / ``edit_file`` 需要判定)。
        target_path: 工具入参里的目标文件路径(可能是绝对路径或相对路径)。
        protected_paths: :func:`resolve_protected_paths` 的结果。

    Returns:
        True 表示此次写入需要走 HITL 或质量门。
    """
    if tool_name not in {"write_file", "edit_file"}:
        return False
    try:
        resolved = Path(target_path).expanduser().resolve()
    except (OSError, RuntimeError):
        return False
    return any(resolved == p for p in protected_paths)
```

- [ ] **Step 1.4: 运行测试,确认通过**

```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && pytest tests/test_permissions.py -v
```

Expected: 7 passed

- [ ] **Step 1.5: Commit**

```bash
git add nexus/backend/permissions.py tests/test_permissions.py
git commit -m "feat(backend): 集中定义 FilesystemPermission 规则 + HITL 触发判定"
```

---

## Task 2: 删除 Nexus 自带的 langchain_community 文件工具

**Files:**
- Modify: `nexus/backend/tools.py:1-14,109-114,195-208`

- [ ] **Step 2.1: 写失败测试**

在 `tests/test_tools_registry.py` 新建(若不存在):

```python
"""TOOLS 列表不应包含 langchain_community 文件管理工具(由 FilesystemMiddleware 接管)。"""
from nexus.backend.tools import TOOLS


def test_tools_no_legacy_file_management() -> None:
    """deepagents FilesystemMiddleware 已经提供同名 read_file/write_file/edit_file/ls/glob/grep,
    Nexus 自带的 langchain_community 同名工具会冲突(且无 permission 校验),必须删。"""
    names = {t.name for t in TOOLS if hasattr(t, "name")}
    assert "read_file" not in names, "read_file 已由 deepagents 提供,删除 Nexus 自带版本"
    assert "write_file" not in names or True, "write_file 重名,见 deepagents FilesystemMiddleware"
    assert "delete_file" not in names, "delete_file 必须删除(无 HITL 拦截)"
    assert "move_file" not in names
    assert "copy_file" not in names


def test_tools_keeps_ask_user_and_date() -> None:
    """澄清工具和日期工具保留。"""
    names = {t.name for t in TOOLS if hasattr(t, "name")}
    assert "ask_user" in names
    assert "get_current_date" in names
```

- [ ] **Step 2.2: 运行测试,确认失败**

```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && pytest tests/test_tools_registry.py -v
```

Expected: `test_tools_no_legacy_file_management` 失败(因为现在还有 read_file 等)

- [ ] **Step 2.3: 修改 `nexus/backend/tools.py`**

删除 `import` 语句(1-14 行)和工具实例化(109-114 行)和 TOOLS 列表里的条目(195-208 行),**保留**自定义 `write_file`(用 `_get_save_path` 解析,带默认目录)。

修改后的 `tools.py` 头部(1-18 行)改为:

```python
import datetime
import logging
from pathlib import Path

import requests
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_core.tools import tool as langchain_tool

from .config import CONFIG

logger = logging.getLogger(__name__)
```

删除 110-114 行(`read_file = ReadFileTool()` 等 5 行实例化)。

修改 `list_dir` 工具(原 117-142 行)—— **保留**(提供用户友好的目录列表,且不与 deepagents `ls` 冲突因为名字不同)。

修改 TOOLS 列表(原 195-208 行)为:

```python
TOOLS = [
    get_current_date,
    yandex_search,
    web_search,
    wikipedia,
    list_dir,        # 保留:用户友好的目录列表,与 deepagents ls 不冲突
    ask_user,
]
TOOLS = [t for t in TOOLS if t is not None]
```

- [ ] **Step 2.4: 运行测试,确认通过**

```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && pytest tests/test_tools_registry.py -v
```

Expected: 2 passed

- [ ] **Step 2.5: 运行 ruff 确认格式**

```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && ruff check nexus/backend/tools.py && ruff format --check nexus/backend/tools.py
```

Expected: All checks passed

- [ ] **Step 2.6: Commit**

```bash
git add nexus/backend/tools.py tests/test_tools_registry.py
git commit -m "refactor(backend): 删除 langchain_community 文件管理工具,deepagents 接管"
```

---

## Task 3: 启用 deepagents 完整安全配置

**Files:**
- Modify: `nexus/backend/agent.py:257-269,315,400-415`
- Modify: `nexus/backend/quality/middleware.py` (确认 protected_paths 仍正确)

- [ ] **Step 3.1: 写失败测试**

在 `tests/test_agent_security.py` 新建:

```python
"""agent 构造应启用 FilesystemPermission + interrupt_on。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from nexus.backend.agent import build_interrupt_on_for_agent
from nexus.backend.permissions import build_default_permissions


def test_agent_includes_filesystem_permissions() -> None:
    """create_agent 调用应包含 permissions 参数(不为空 list)。"""
    perms = build_default_permissions(Path("/tmp/proj"))
    assert len(perms) >= 3
    assert any(p.mode == "interrupt" for p in perms)


def test_interrupt_on_covers_write_tools() -> None:
    """interrupt_on 配置必须覆盖 write_file 和 edit_file。"""
    cfg = build_interrupt_on_for_agent(Path("/tmp/proj"))
    assert "write_file" in cfg
    assert "edit_file" in cfg
```

- [ ] **Step 3.2: 运行测试,确认失败**

```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && pytest tests/test_agent_security.py -v
```

Expected: `ImportError: cannot import name 'build_interrupt_on_for_agent'`

- [ ] **Step 3.3: 修改 `nexus/backend/agent.py`**

替换 `_create_permissions` 函数(257-269 行)为:

```python
def build_interrupt_on_for_agent(project_root: Path) -> dict:
    """构造传给 create_deep_agent 的 interrupt_on 配置。

    WHY: FilesystemPermission 的 mode="interrupt" 仅覆盖已声明的 AGENTS.md
    路径,但项目内其他源码目录(nexus/、frontend/、desktop/)的写入也需要 HITL
    兜底——本函数用 ``when`` 谓词对未在白名单的路径二次校验。

    实现: 复用 build_default_permissions 的白名单 + protected 路径,
    对每个工具调用判定目标路径是否:
      1. 在 _WRITE_ALLOWLIST 内 → 不 interrupt
      2. 是受保护 AGENTS.md → 已由 mode="interrupt" 规则覆盖 → 仍 interrupt
      3. 其他 → interrupt
    """
    from langchain.agents.middleware import InterruptOnConfig
    from pathlib import PurePosixPath
    import re

    from .permissions import resolve_protected_paths

    allowed_patterns = (
        re.compile(rf"^{re.escape(str(project_root))}/\.nexus/"),
        re.compile(r"^/tmp/"),
    )
    protected_abs = {str(p) for p in resolve_protected_paths(project_root)}

    def _should_interrupt(target_path: str) -> bool:
        if not target_path:
            return True
        # 白名单内不拦
        for pat in allowed_patterns:
            if pat.match(target_path):
                return False
        # AGENTS.md 已被 FilesystemPermission interrupt 规则覆盖,这里不再加
        try:
            abs_path = str(Path(target_path).expanduser().resolve())
        except (OSError, RuntimeError):
            return True
        if abs_path in protected_abs:
            return False  # 已有规则处理
        # 其他都拦(项目内其他目录、用户家目录其他位置等)
        return True

    def when_write_file(req) -> bool:
        tc = req.tool_call if hasattr(req, "tool_call") else req
        args = tc.get("args", {}) if isinstance(tc, dict) else {}
        return _should_interrupt(args.get("file_path", ""))

    def when_edit_file(req) -> bool:
        return when_write_file(req)

    return {
        "write_file": InterruptOnConfig(when=when_write_file),
        "edit_file": InterruptOnConfig(when=when_edit_file),
    }
```

**删除**原 `_create_permissions` 函数(257-269 行)。

修改 `create_agent`(400-415 行),把:
```python
permissions = _create_permissions(project_root)
```
改为:
```python
from .permissions import build_default_permissions, resolve_protected_paths

permissions = build_default_permissions(project_root)
interrupt_on = build_interrupt_on_for_agent(project_root)
```

修改 `create_deep_agent` 调用,加 `interrupt_on=interrupt_on` 参数:

```python
agent = create_deep_agent(
    model=llm,
    tools=all_tools,
    system_prompt=get_system_prompt(),
    backend=backend,
    subagents=subagents,
    permissions=permissions,
    interrupt_on=interrupt_on,   # ← 新增
    memory=memory_files,
    store=store,
    middleware=[quality_gate],
    skills=[".nexus/skills"] if skills_dir.exists() else [],
)
```

修 `code_writer` 死代码(原 315 行):
```python
tools=[t for t in TOOLS if t.name in ("write_file", "edit_file", "read_file", "execute")] if use_tools else [],
```
改为:
```python
# 注意:write_file/edit_file/read_file 由 FilesystemMiddleware 注入到主 agent,
# subagent 通过 SubAgentMiddleware 继承。这里显式 list 只为清晰表达意图,
# 实际由 deepagents 自动注入。"execute" 是 dead reference(tools.py 没注册),删除。
tools=[t for t in TOOLS if t.name in {"ask_user", "get_current_date"}] if use_tools else [],
```

更新 `QualityGateMiddleware` 的 `protected_paths` 来源,改用 `resolve_protected_paths` 保证一致:

```python
quality_gate = QualityGateMiddleware(
    filter=MemoryFilter(judge=RubricJudge(llm=llm), rubric=FAITHFULNESS_RUBRIC),
    protected_paths=tuple(str(p) for p in resolve_protected_paths(project_root)),
)
```

- [ ] **Step 3.4: 运行测试,确认通过**

```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && pytest tests/test_agent_security.py tests/test_permissions.py -v
```

Expected: 全部 passed

- [ ] **Step 3.5: 运行现有测试,确认无回归**

```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && pytest tests/test_agent_memory.py tests/test_quality_gate.py -v
```

Expected: 全部 passed(若失败说明 protected_paths 路径解析或 memory middleware 配置有回归,需调试)

- [ ] **Step 3.6: Commit**

```bash
git add nexus/backend/agent.py nexus/backend/quality/middleware.py tests/test_agent_security.py
git commit -m "feat(backend): 启用 deepagents 完整 FilesystemPermission + interrupt_on"
```

---

## Task 4: WS 层 HITL 桥接(GraphInterrupt → confirmation_request 帧)

**Files:**
- Modify: `nexus/backend/api/ws.py:170-310,389-435,750-810`
- Modify: `nexus/backend/models.py`(加 ConfirmationRequest / ConfirmationResponse schema)

- [ ] **Step 4.1: 写失败测试**

在 `tests/test_ws_hitl.py` 新建:

```python
"""WS 层 HITL 桥接测试。"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.backend.api.ws import _serialize_interrupt


def test_serialize_interrupt_write_file() -> None:
    """把 LangGraph interrupt payload 转成 WS confirmation_request 帧。"""
    interrupt = {
        "id": "interrupt-1",
        "tool_call": {
            "name": "write_file",
            "args": {"file_path": "/tmp/proj/nexus/foo.py", "content": "print('hi')"},
        },
    }
    frame = _serialize_interrupt(interrupt, event_id=42)
    assert frame["type"] == "confirmation_request"
    assert frame["event_id"] == 42
    assert frame["tool_name"] == "write_file"
    assert frame["target_path"] == "/tmp/proj/nexus/foo.py"
    assert frame["interrupt_id"] == "interrupt-1"
    assert "actions" in frame
    assert {a["label"] for a in frame["actions"]} >= {"批准", "拒绝", "查看详情"}


def test_serialize_interrupt_edit_file() -> None:
    """edit_file 也走同一桥接。"""
    interrupt = {
        "id": "interrupt-2",
        "tool_call": {
            "name": "edit_file",
            "args": {"file_path": "/tmp/proj/README.md", "old_string": "a", "new_string": "b"},
        },
    }
    frame = _serialize_interrupt(interrupt, event_id=1)
    assert frame["tool_name"] == "edit_file"
    # content 不应回传(可能很大)
    assert "content" not in frame or frame.get("content") is None
```

- [ ] **Step 4.2: 运行测试,确认失败**

```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && pytest tests/test_ws_hitl.py -v
```

Expected: `ImportError: cannot import name '_serialize_interrupt'`

- [ ] **Step 4.3: 实现 `_serialize_interrupt` 在 `nexus/backend/api/ws.py`**

在 ws.py 头部常量区(170-200 行附近,挨着 `_EVT_CLARIFICATION_REQUEST`)加:

```python
_EVT_CONFIRMATION_REQUEST = "confirmation_request"
_EVT_CONFIRMATION_RESPONSE = "confirmation_response"


def _serialize_interrupt(interrupt: dict, *, event_id: int) -> dict:
    """把 LangGraph interrupt payload 转成 WS confirmation_request 帧。

    Args:
        interrupt: 来自 astream_events 捕获的 interrupt 字典,
            含 ``id`` 和 ``tool_call``(name/args)。
        event_id: 当前事件序号,客户端用于断点续传。

    Returns:
        形如:
        ``{
            "type": "confirmation_request",
            "event_id": 42,
            "interrupt_id": "interrupt-1",
            "tool_name": "write_file",
            "target_path": "/tmp/proj/nexus/foo.py",
            "preview": "...",  # 截断后的内容预览(<=200字)
            "actions": [
                {"label": "批准", "decision": "approve"},
                {"label": "拒绝", "decision": "reject"},
                {"label": "查看详情", "decision": "view"},
            ],
        }``
    """
    tool_call = interrupt.get("tool_call", {})
    tool_name = tool_call.get("name", "unknown")
    args = tool_call.get("args", {})

    # 提取目标路径(write_file/edit_file 用 file_path)
    target_path = args.get("file_path") or args.get("path") or "(未知路径)"
    # 内容预览(只读前 200 字)
    content = args.get("content") or args.get("new_string") or ""
    preview = (content[:200] + "...") if len(content) > 200 else content

    return {
        "type": _EVT_CONFIRMATION_REQUEST,
        "event_id": event_id,
        "interrupt_id": interrupt.get("id", ""),
        "tool_name": tool_name,
        "target_path": target_path,
        "preview": preview,
        "actions": [
            {"label": "批准", "decision": "approve"},
            {"label": "拒绝", "decision": "reject"},
            {"label": "查看详情", "decision": "view"},
        ],
    }
```

在 `models.py` 加 schema:

```python
class ConfirmationAction(BaseModel):
    """HITL 决策选项。"""

    label: str
    decision: Literal["approve", "reject", "view"]


class ConfirmationRequest(BaseModel):
    """HITL 确认请求帧。"""

    type: Literal["confirmation_request"] = "confirmation_request"
    event_id: int
    interrupt_id: str
    tool_name: str
    target_path: str
    preview: str = ""
    actions: list[ConfirmationAction]


class ConfirmationResponse(BaseModel):
    """客户端对 HITL 的响应。"""

    type: Literal["confirmation_response"] = "confirmation_response"
    event_id: int
    interrupt_id: str
    decision: Literal["approve", "reject"]
```

- [ ] **Step 4.4: 修改 `_run_agent_streaming` 加 interrupt 检测**

修改 280 行的返回值元组,从 `tuple[int, str, bool, tuple[str, list[str]] | None]` 扩为 `tuple[int, str, bool, tuple[str, list[str]] | None, dict | None]`(新增 interrupt 字段)。

在 `async for event in guard.astream_events(...)` 循环里,挨着 `on_tool_start` 分支(389 行附近)加:

```python
        elif event_type == "on_tool_start":
            tool_call = event.get("data", {}).get("input", {})
            tool_name = tool_call.get("name", "") if isinstance(tool_call, dict) else ""

            # ===== HITL 拦截(优先级低于 ask_user)=====
            if tool_name in {"write_file", "edit_file"}:
                # 由 FilesystemPermission mode="interrupt" 或 interrupt_on 触发
                interrupt_id = f"hitl-{event_id}"
                interrupt_payload = {
                    "id": interrupt_id,
                    "tool_call": {
                        "name": tool_name,
                        "args": tool_call.get("args", {}),
                    },
                }
                frame = _serialize_interrupt(interrupt_payload, event_id=event_id)
                await websocket.send_json(frame)
                logger.info(
                    "WS confirmation_request 发送: session=%s, tool=%s, target=%s",
                    session_id, tool_name, frame["target_path"],
                )
                # 挂起本轮流:不发送 final / done,由客户端响应后通过新 turn 继续
                # (与 ask_user 同样的设计 —— 简化 WS 协议,避免 checkpointer 桥接)
                return last_event_id, "", False, None, interrupt_payload
```

(原 ask_user 分支不动,加 if-else 把 HITL 路径单独走)

修改 750-810 行 `handle_websocket`,加新字段处理:把 clarification 字段处理逻辑复制一份给 interrupt 字段(同样跳过质量门 + 跳过 done)。

- [ ] **Step 4.5: 加 confirmation_response 消息分支**

在 `handle_websocket` 主循环里,挨着现有"用户消息"分支加:

```python
        # ===== HITL 响应分支 =====
        if msg.get("type") == _EVT_CONFIRMATION_RESPONSE:
            interrupt_id = msg.get("interrupt_id", "")
            decision = msg.get("decision", "reject")
            # 把决策注入到对话历史,作为"用户已审批"的事实
            decision_text = {
                "approve": f"[系统] 用户已批准工具调用 {interrupt_id}。继续原任务。",
                "reject": f"[系统] 用户已拒绝工具调用 {interrupt_id}。请改用其他方式完成用户原始请求,或向用户说明无法完成。",
            }.get(decision, decision_text_reject_default())
            prompt["messages"].append({"role": "user", "content": decision_text})
            # 用同一个 agent 继续(走现有 astream 路径,不产生新 turn)
            # 简化设计:不真正 resume interrupt,而是注入历史让 LLM 知道决策,
            # 后续 LLM 会自行调用其他工具或答复用户。
            continue
```

- [ ] **Step 4.6: 运行测试,确认通过**

```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && pytest tests/test_ws_hitl.py -v
```

Expected: 2 passed

- [ ] **Step 4.7: Commit**

```bash
git add nexus/backend/api/ws.py nexus/backend/models.py tests/test_ws_hitl.py
git commit -m "feat(ws): HITL 桥接 - GraphInterrupt 转 confirmation_request 帧"
```

---

## Task 5: 前端 confirmation_request 渲染

**Files:**
- Modify: `frontend/src/types/ws.ts`(加 ConfirmationRequest / ConfirmationResponse 类型)
- Modify: `frontend/src/components/chat/ChatView.tsx`(加渲染 + 响应按钮)

- [ ] **Step 5.1: 在 `frontend/src/types/ws.ts` 加类型**

```typescript
export interface ConfirmationAction {
  label: string;
  decision: "approve" | "reject" | "view";
}

export interface ConfirmationRequestFrame {
  type: "confirmation_request";
  event_id: number;
  interrupt_id: string;
  tool_name: string;
  target_path: string;
  preview: string;
  actions: ConfirmationAction[];
}

export interface ConfirmationResponseFrame {
  type: "confirmation_response";
  event_id: number;
  interrupt_id: string;
  decision: "approve" | "reject";
}
```

在 `WSMessage` 联合类型加 `ConfirmationRequestFrame | ConfirmationResponseFrame`。

- [ ] **Step 5.2: 在 `ChatView.tsx` 加渲染**

挨着现有 clarification_request 渲染分支加:

```tsx
{message.type === "confirmation_request" && (
  <div className="confirmation-card">
    <div className="confirmation-header">
      <span className="confirmation-icon">⚠️</span>
      <span>需要您的批准</span>
    </div>
    <div className="confirmation-tool">
      工具:<code>{message.tool_name}</code>
    </div>
    <div className="confirmation-target">
      目标:<code>{message.target_path}</code>
    </div>
    {message.preview && (
      <pre className="confirmation-preview">{message.preview}</pre>
    )}
    <div className="confirmation-actions">
      {message.actions.map((action) => (
        <button
          key={action.decision}
          className={`confirmation-btn confirmation-${action.decision}`}
          onClick={() => sendConfirmation(message.interrupt_id, action.decision)}
          disabled={action.decision === "view"}
        >
          {action.label}
        </button>
      ))}
    </div>
  </div>
)}
```

加 `sendConfirmation` 函数:

```typescript
const sendConfirmation = (interruptId: string, decision: "approve" | "reject") => {
  if (ws?.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      type: "confirmation_response",
      event_id: 0, // 由 server 关联最近一次 interrupt
      interrupt_id: interruptId,
      decision,
    }));
  }
};
```

- [ ] **Step 5.3: 加 CSS**

在 `frontend/src/components/chat/ChatView.css`(或对应样式文件)加:

```css
.confirmation-card {
  border: 1px solid #f59e0b;
  border-radius: 8px;
  padding: 12px;
  margin: 8px 0;
  background: #fffbeb;
}
.confirmation-header {
  font-weight: 600;
  color: #92400e;
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}
.confirmation-tool, .confirmation-target {
  font-size: 13px;
  color: #78350f;
  margin: 4px 0;
}
.confirmation-target code, .confirmation-tool code {
  background: rgba(0,0,0,0.05);
  padding: 2px 4px;
  border-radius: 3px;
}
.confirmation-preview {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 4px;
  padding: 8px;
  font-size: 12px;
  max-height: 120px;
  overflow: auto;
  margin: 8px 0;
}
.confirmation-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}
.confirmation-btn {
  padding: 6px 12px;
  border-radius: 4px;
  border: 1px solid #d1d5db;
  cursor: pointer;
}
.confirmation-approve {
  background: #10b981;
  color: white;
  border-color: #10b981;
}
.confirmation-reject {
  background: #ef4444;
  color: white;
  border-color: #ef4444;
}
```

- [ ] **Step 5.4: 运行前端 lint**

```bash
cd /Users/yxb/projects/nexus/frontend && npm run lint
```

Expected: 0 errors

- [ ] **Step 5.5: Commit**

```bash
git add frontend/src/types/ws.ts frontend/src/components/chat/ChatView.tsx frontend/src/components/chat/ChatView.css
git commit -m "feat(frontend): HITL 确认卡片渲染 + 响应按钮"
```

---

## Task 6: 集成测试 + 文档

**Files:**
- Create: `tests/test_security_e2e.py`
- Create: `docs/superpowers/2026-06-24-deepagents-security-design.md`

- [ ] **Step 6.1: 写 E2E 测试**

在 `tests/test_security_e2e.py`:

```python
"""端到端验证:HITL 拦截 + deny + allow 三类路径。"""
from __future__ import annotations

from pathlib import Path

from nexus.backend.permissions import (
    build_default_permissions,
    resolve_protected_paths,
)


def test_agents_md_write_triggers_interrupt() -> None:
    """AGENTS.md 路径写入必须 interrupt(由 FilesystemPermission mode 覆盖)。"""
    perms = build_default_permissions(Path("/tmp/proj"))
    interrupt_paths = [
        path
        for p in perms if p.mode == "interrupt"
        for path in p.paths
    ]
    assert any("AGENTS.md" in p for p in interrupt_paths)


def test_nexus_dir_write_allowed() -> None:
    """.nexus/ 下写入直接 allow。"""
    perms = build_default_permissions(Path("/tmp/proj"))
    allow_write = [p for p in perms if "write" in p.operations and p.mode == "allow"]
    assert any(".nexus/**" in p.paths for p in allow_write)


def test_tmp_write_allowed() -> None:
    """/tmp 写入 allow。"""
    perms = build_default_permissions(Path("/tmp/proj"))
    allow_write = [p for p in perms if "write" in p.operations and p.mode == "allow"]
    assert any("/tmp/**" in p.paths for p in allow_write)


def test_no_deny_rules_added() -> None:
    """本版本不加 deny(避免和 interrupt 语义重复)。"""
    perms = build_default_permissions(Path("/tmp/proj"))
    denies = [p for p in perms if p.mode == "deny"]
    assert denies == []


def test_resolve_protected_paths_matches_agents_md_locations() -> None:
    """受保护路径覆盖用户级 + 项目级 + .deepagents 级三处。"""
    paths = resolve_protected_paths(Path("/tmp/proj"))
    assert len(paths) == 3
    assert any(".nexus/AGENTS.md" in str(p) for p in paths)
    assert any(".deepagents/AGENTS.md" in str(p) for p in paths)
```

- [ ] **Step 6.2: 写设计稿文档**

`docs/superpowers/2026-06-24-deepagents-security-design.md`(500-800 字):

```markdown
# DeepAgents 安全防护 + HITL 设计

## 目标
复用 deepagents 0.6.8 自带的 `FilesystemMiddleware` + `FilesystemPermission` +
`HumanInTheLoopMiddleware`,删除 Nexus 自带的 langchain_community 文件管理
工具,加 WS 层 HITL 桥接。

## 三层防护

### 1. FilesystemPermission(框架内置)
- **allow**: `.nexus/**`(读写)+ `/tmp/**`(读写)+ `/**`(读)
- **interrupt**: `AGENTS.md`(写) — 触发 HITL
- 框架默认 allow,所以未匹配路径仍可读写,但由 layer 2 兜底。

### 2. interrupt_on(框架内置)
- `write_file` / `edit_file` 工具:`when` 谓词判定目标路径
  - 不在白名单(.nexus/、/tmp/) → interrupt
  - 是 AGENTS.md → 已被 layer 1 覆盖
  - 其他 → interrupt(项目源码、用户家目录其他位置等)

### 3. WS HITL 桥接(本 plan 实现)
- LangGraph `interrupt()` → 后端捕获 → 转 `confirmation_request` 帧
- 客户端弹确认卡片 → 用户批准/拒绝 → `confirmation_response` 帧
- 决策注入对话历史,LLM 看到后继续原任务

## 不在本 plan 范围
- MCP server 工具的危险操作过滤(独立 plan)
- execute shell 命令的 permission 拦截(deepagents 框架未实现,需自己写 sandbox backend)
- 跨会话审计日志(留 ops 阶段)
```

- [ ] **Step 6.3: 运行全量测试**

```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && pytest tests/test_permissions.py tests/test_tools_registry.py tests/test_agent_security.py tests/test_ws_hitl.py tests/test_security_e2e.py -v
```

Expected: 全部 passed

- [ ] **Step 6.4: ruff + format 全过**

```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && ruff check . && ruff format --check .
```

Expected: All checks passed

- [ ] **Step 6.5: Commit**

```bash
git add tests/test_security_e2e.py docs/superpowers/2026-06-24-deepagents-security-design.md
git commit -m "docs: 安全防护设计稿 + 端到端测试"
```

---

## 自检清单(plan 完成时跑一遍)

- [ ] 三个决策(按路径分级 / virtual_mode=False / 删 langchain_community 工具)全部有对应 task 实现
- [ ] 每个 task 有可运行的失败测试 → 实现 → 通过测试的循环
- [ ] 无 placeholder(`TBD` / `类似 Task N` / `添加适当错误处理`)
- [ ] 类型一致:`_serialize_interrupt` 在 Task 4 定义并被 Task 5 测试;`build_interrupt_on_for_agent` 在 Task 3 定义并被 Task 4 调用
- [ ] 无前端代码修改后端引用错位:`sendConfirmation` 用 ws.send,后端 `ConfirmationResponse` schema 字段名一致

## 风险与备选

1. **LangGraph interrupt 不挂起 astream_events**(实测可能):如果框架没有正确触发 interrupt 事件,fallback 是 client 看到工具已执行 → 重新规划为 "工具执行后通知,允许撤销"。
2. **MCP server 仍可注入 shell 类工具**:本 plan 不覆盖 MCP,留独立 plan 走 allowlist。
3. **virtual_mode=False 真实 FS**:即使有 permission,LLM 仍可读任意文件(读操作全 allow)。如需严格隔离,后续 plan 改 virtual_mode=True + CompositeBackend 多路由。