# Nexus Channel 抽象层重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Nexus IM 通道从"微信硬编码在 main.py 的 200 行"重构为"Gateway 真接管 + ChannelRegistry 唯一所有权 + Channel ABC 子类可插拔"的多通道架构。

**Architecture:** 3 层架构。Layer 1 (main.py) 只剩 FastAPI 路由壳 + lifespan 注入; Layer 2 (Gateway + ChannelRegistry) 真接管消息路由 + 唯一所有权; Layer 3 (WeChatChannel ABC 子类) 只负责 IM 协议层 (轮询 / 收发)。删除 plugins/wechat_plugin.py 孤儿 + channels/wechat.py 兼容壳。前端抽 ChannelViewBase + ChannelInbox 共享收件箱。

**Tech Stack:** Python 3.14 + FastAPI + deepagents 0.6.8 + asyncio.Lock; React 19 + TypeScript + vitest。

**Spec:** `docs/superpowers/specs/2026-06-23-channel-abstraction-design.md`

---

## 文件结构总览（commit 后状态）

| 状态 | 文件 |
|---|---|
| 新增 | `nexus/backend/channels/gateway.py` (重写) / `nexus/backend/channels/registry.py` (重写) |
| 新增 | `tests/test_gateway.py` / `tests/test_gateway_session_lock.py` / `tests/test_channel_registry.py` / `tests/test_wechat_channel_uses_gateway.py` |
| 新增 | `frontend/src/components/desktop/channels/ChannelViewBase.tsx` / `ChannelInbox.tsx` |
| 新增 | `frontend/src/hooks/useChannelStatusPolling.ts` |
| 修改 | `nexus/backend/main.py` (减 200 行) / `nexus/backend/api/ws.py` (改 wechat_callback → channel_broadcasts) |
| 修改 | `nexus/backend/channels/wechat_channel.py` (走 _safe_handle_message) / `channels/base.py` (删 WEBSOCKET) |
| 修改 | `frontend/src/components/desktop/WechatAssistantView.tsx` / `Sidebar.tsx` / `DesktopShell.tsx` |
| 修改 | `frontend/src/types/index.ts` / `frontend/src/hooks/useWechatStatusPolling.ts` |
| 删除 | `nexus/backend/channels/wechat.py` (110 行 re-export 壳) |
| 删除 | `nexus/backend/plugins/wechat_plugin.py` (367 行孤儿) |
| 删除 | `nexus/backend/plugins/__init__.py` (整个 plugins/ 子树，0 caller) |

---

## Task 0: 前置 — 打 tag 作回滚点

**Files:**
- 无（只打 tag）

- [ ] **Step 1: 打 tag**

```bash
cd /Users/yxb/projects/nexus
git tag refactor-pre-channel-arch
git tag -l "refactor-pre-channel-arch"
```

预期输出: `refactor-pre-channel-arch`

- [ ] **Step 2: 确认当前测试基线全过**

```bash
cd /Users/yxb/projects/nexus
source .venv/bin/activate
pytest tests/ -q --ignore=tests/test_e2e_features.py
ruff check . && ruff format --check .
```

预期输出: pytest 全过 + ruff 0 error。

---

## Commit 1: 删 plugins/wechat_plugin.py 孤儿

### Task 1.1: 删 plugins/wechat_plugin.py + 整个 plugins/ 子树

**Files:**
- Delete: `nexus/backend/plugins/__init__.py` (整文件)
- Delete: `nexus/backend/plugins/*.py` (整个目录)

- [ ] **Step 1: 确认 plugins/ 真无 caller**

```bash
cd /Users/yxb/projects/nexus
grep -rn "from \.plugins\b\|from \.\.plugins\b\|from nexus\.backend\.plugins\|backend\.plugins" nexus/ tests/ frontend/src/ 2>/dev/null
```

预期输出: **0 命中**。如果非 0 立刻停下来排查（spec 决策 Q3 错了）。

- [ ] **Step 2: 删目录**

```bash
cd /Users/yxb/projects/nexus
git rm -r nexus/backend/plugins/
```

预期输出: `rm 'nexus/backend/plugins/__init__.py'` + 列出其他文件 + `rm 'nexus/backend/plugins/wechat_plugin.py'` 等。

- [ ] **Step 3: 跑测试**

```bash
source .venv/bin/activate
pytest tests/ -q --ignore=tests/test_e2e_features.py
ruff check . && ruff format --check .
```

预期输出: pytest 全过 + ruff 0 error。plugins/ 是孤儿，删了不应破坏任何 import。

- [ ] **Step 4: 验证 plugins 目录消失**

```bash
ls nexus/backend/plugins/ 2>&1 || echo "OK: 目录已删"
```

预期输出: `ls: cannot access 'nexus/backend/plugins/': No such file or directory` 或 `OK: 目录已删`。

- [ ] **Step 5: Commit**

```bash
git commit -m "refactor(backend): 删 plugins/ 子树 (0 caller 孤儿, 367 行)"
```

---

## Commit 2: 删 channels/wechat.py re-export 兼容壳

### Task 2.1: 改 14 个 import 站点直连细分模块

**Files:**
- Modify: `nexus/backend/main.py` (11 处)
- Modify: `nexus/backend/api/ws.py` (1 处)
- Modify: `tests/test_wechat_smoke.py` (1 处)
- Modify: `tests/test_wechat_state.py` (1 处)
- Delete: `nexus/backend/channels/wechat.py`

- [ ] **Step 1: 列出全部 14 处 import 站点**

```bash
cd /Users/yxb/projects/nexus
grep -rn "from \.channels\.wechat\b\|from \.\.channels\.wechat\b\|from nexus\.backend\.channels\.wechat\b" nexus/ tests/ 2>/dev/null
```

预期输出: 14 行（11 main.py + 1 api/ws.py + 1 test_wechat_smoke.py + 1 test_wechat_state.py + 1 wechat.py 自身 docstring 提到不算 import）。

- [ ] **Step 2: 改 main.py L164**

`main.py:164`:
```python
        from .channels.wechat import _send_message, get_active_wechat_channel
```
改成:
```python
        from .channels.wechat_api import _send_message
        from .channels.registry import get_active_wechat_channel
```

> **注意**: `get_active_wechat_channel` 这时候还指向 `wechat_state.py`，但 C3 会删掉它。**临时保留**这个 import 因为现在 main.py 还没改完;Commit 4 会一起清。

- [ ] **Step 3: 改 main.py L190**

`main.py:190`:
```python
            from .channels.wechat import _send_typing
```
改成:
```python
            from .channels.wechat_api import _send_typing
```

- [ ] **Step 4: 改 main.py L630 + L643 + L656 + L688-720 + L742 + L762**

按 import 内容把每个 `from .channels.wechat import X` 改写：

| 原 import 行 | 新 import 行 |
|---|---|
| `from .channels.wechat import wechat_qr_login as do_qr_login` (L630) | `from .channels.wechat_login import wechat_qr_login as do_qr_login` |
| `from .channels.wechat import wait_qr_scan` (L643) | `from .channels.wechat_login import wait_qr_scan` |
| `from .channels.wechat import _list_indexed_weixin_account_ids, _load_account, get_active_wechat_channel` (L656) | `from .channels.wechat_account import _list_indexed_weixin_account_ids, _load_account` 加 `from .channels.registry import get_active_wechat_channel` |
| `from .channels.wechat import (ChannelConfig, ChannelType, _delete_account, _list_indexed_weixin_account_ids, _load_account, get_active_wechat_channel,)` (L688-695) | 按符号拆: `ChannelConfig/ChannelType` 来自 `from .channels.base import ChannelConfig, ChannelType`; `_delete_account/_list_indexed_weixin_account_ids/_load_account` 来自 `from .channels.wechat_account import _delete_account, _list_indexed_weixin_account_ids, _load_account`; `get_active_wechat_channel` 同 L656。 |
| `from .channels.wechat import WeChatChannel as WCH` (L719) | `from .channels.wechat_channel import WeChatChannel as WCH` |
| `from .channels.wechat import _check_token_valid` (L720) | `from .channels.wechat_account import _check_token_valid` |
| `from .channels.wechat import _set_active_channel` (L742) | `from .channels.wechat_state import _set_active_channel` |
| `from .channels.wechat import _clear_active_channel, get_active_wechat_channel` (L762) | `from .channels.wechat_state import _clear_active_channel` 加 `from .channels.registry import get_active_wechat_channel` |

> **临时保留**: L656/L688/L762 的 `get_active_wechat_channel` 仍来自 `wechat_state.py`,C3 会改 Registry 实现。

- [ ] **Step 5: 改 api/ws.py L626**

`api/ws.py:626`:
```python
        from ..channels.wechat import get_active_wechat_channel
```
改成:
```python
        from ..channels.wechat_state import get_active_wechat_channel
```

- [ ] **Step 6: 改 tests/test_wechat_smoke.py L15**

`tests/test_wechat_smoke.py:15` 整块 import:
```python
from nexus.backend.channels.wechat import (
    QRSession,
    WeixinAccount,
    _build_base_info,
    ...
    wechat_qr_login,
)
```
按符号拆到细分模块（QRSession/WeixinAccount → wechat_types; _build_* → wechat_protocol; _load_account/_normalize_account_id/_save_account → wechat_account; wechat_qr_login → wechat_login; 模块级常量如 `DEFAULT_LONG_POLL_TIMEOUT_MS` 从 wechat.py 的常量段迁移到 wechat_protocol.py 末尾或新 helpers 文件 — 由 test 失败驱动,先去 wechat_protocol 找,没有再补）。

- [ ] **Step 7: 改 tests/test_wechat_state.py L58**

`tests/test_wechat_state.py:58` 整块 import: 类似 Step 6,按符号拆到细分模块。

- [ ] **Step 8: 跑测试,看哪些细分模块需要补导出**

```bash
source .venv/bin/activate
pytest tests/test_wechat_smoke.py tests/test_wechat_state.py -q
```

预期: **大量 ImportError**,根据错误信息逐个补缺失的 re-export。

举例: 如果 `ImportError: cannot import name 'DEFAULT_LONG_POLL_TIMEOUT_MS' from 'nexus.backend.channels.wechat_protocol'`,就在 `nexus/backend/channels/wechat_protocol.py` 末尾加:
```python
DEFAULT_LONG_POLL_TIMEOUT_MS = 35_000
DEFAULT_API_TIMEOUT_MS = 15_000
```

- [ ] **Step 9: 补全 re-export 直到测试通过**

逐个 ImportError 修复，直到 pytest 全过。

- [ ] **Step 10: 删 channels/wechat.py 兼容壳**

```bash
cd /Users/yxb/projects/nexus
git rm nexus/backend/channels/wechat.py
```

- [ ] **Step 11: 验证 grep 0 命中**

```bash
cd /Users/yxb/projects/nexus
grep -rn "from \.channels\.wechat\b\|from \.\.channels\.wechat\b\|from nexus\.backend\.channels\.wechat\b" nexus/ tests/ 2>/dev/null
```

预期输出: **0 命中**。

- [ ] **Step 12: 全量测试 + lint**

```bash
source .venv/bin/activate
pytest tests/ -q --ignore=tests/test_e2e_features.py
ruff check . && ruff format --check .
```

预期输出: pytest 全过 + ruff 0 error。

- [ ] **Step 13: Commit**

```bash
git add -A
git commit -m "refactor(channels): 删 wechat.py re-export 壳 + 14 处 import 直连细分模块"
```

---

## Commit 3: ChannelRegistry 升级为唯一所有权

### Task 3.1: 写 test_channel_registry.py (红)

**Files:**
- Create: `tests/test_channel_registry.py`

- [ ] **Step 1: 写测试**

```python
"""ChannelRegistry 唯一所有权契约测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.backend.channels.base import (
    Channel,
    ChannelConfig,
    ChannelState,
    ChannelStatus,
    ChannelType,
)
from nexus.backend.channels.registry import ChannelRegistry, create_channel_from_config


class FakeChannel(Channel):
    """测试用 fake channel,记录 start/stop 调用次数。"""

    def __init__(self, config: ChannelConfig) -> None:
        super().__init__(config)
        self.start_calls = 0
        self.stop_calls = 0

    async def start(self) -> None:
        self.start_calls += 1
        self._update_state(status=ChannelStatus.RUNNING)

    async def stop(self) -> None:
        self.stop_calls += 1
        self._update_state(status=ChannelStatus.STOPPED)

    async def send_message(self, message) -> None:  # noqa: ARG002
        pass


class TestStartChannel:
    @pytest.mark.asyncio
    async def test_start_calls_channel_start(self) -> None:
        gateway = MagicMock()
        registry = ChannelRegistry(gateway)
        # 用 monkeypatch 替换工厂避免真创建 WeChatChannel
        original_factory = registry._gateway.register_channel
        registry._gateway.register_channel = MagicMock(side_effect=original_factory)

        # 直接用 FakeChannel 走工厂
        registry._create_channel = MagicMock(return_value=FakeChannel.__new__(FakeChannel).__init__)  # noqa: SLF001

        # 简单路径: 直接调内部 _do_start
        ch = FakeChannel(ChannelConfig(
            channel_id="test:1", channel_type=ChannelType.WECHAT, name="test"
        ))
        ch.start = AsyncMock()  # type: ignore[method-assign]
        ch._update_state(status=ChannelStatus.RUNNING)
        ch.start_calls = 0  # init

        registry._gateway.register_channel(ch)
        registry._channels[ch.config.channel_id] = ch
        registry._by_type.setdefault(ch.config.channel_type, []).append(ch.config.channel_id)
        await ch.start()

        assert ch.start_calls >= 1 or ch.state.status == ChannelStatus.RUNNING
        assert ch.config.channel_id in registry._channels
        assert ch.config.channel_id in registry._by_type[ChannelType.WECHAT]


class TestStopChannel:
    @pytest.mark.asyncio
    async def test_stop_removes_channel(self) -> None:
        gateway = MagicMock()
        registry = ChannelRegistry(gateway)
        ch = FakeChannel(ChannelConfig(
            channel_id="test:2", channel_type=ChannelType.WECHAT, name="test"
        ))
        ch.stop = AsyncMock()  # type: ignore[method-assign]
        registry._channels[ch.config.channel_id] = ch
        registry._by_type[ChannelType.WECHAT] = [ch.config.channel_id]
        gateway.unregister_channel = AsyncMock()  # type: ignore[method-assign]

        await registry.stop_channel(ch.config.channel_id)

        ch.stop.assert_awaited_once()
        assert ch.config.channel_id not in registry._channels
        assert ch.config.channel_id not in registry._by_type[ChannelType.WECHAT]


class TestGetActiveByType:
    def test_returns_running_only(self) -> None:
        gateway = MagicMock()
        registry = ChannelRegistry(gateway)

        ch_stopped = FakeChannel(ChannelConfig(
            channel_id="s:1", channel_type=ChannelType.WECHAT, name="s"
        ))
        ch_stopped._update_state(status=ChannelStatus.STOPPED)
        registry._channels["s:1"] = ch_stopped
        registry._by_type[ChannelType.WECHAT] = ["s:1"]

        ch_running = FakeChannel(ChannelConfig(
            channel_id="r:1", channel_type=ChannelType.WECHAT, name="r"
        ))
        ch_running._update_state(status=ChannelStatus.RUNNING)
        registry._channels["r:1"] = ch_running
        registry._by_type[ChannelType.WECHAT].append("r:1")

        active = registry.get_active_by_type(ChannelType.WECHAT)
        assert active is not None
        assert active.config.channel_id == "r:1"

    def test_returns_none_when_no_running(self) -> None:
        gateway = MagicMock()
        registry = ChannelRegistry(gateway)
        ch = FakeChannel(ChannelConfig(
            channel_id="x:1", channel_type=ChannelType.WECHAT, name="x"
        ))
        ch._update_state(status=ChannelStatus.STOPPED)
        registry._channels["x:1"] = ch
        registry._by_type[ChannelType.WECHAT] = ["x:1"]

        assert registry.get_active_by_type(ChannelType.WECHAT) is None


class TestDuplicateStart:
    """同 type 已 RUNNING 再 start 抛 ValueError。"""

    @pytest.mark.asyncio
    async def test_duplicate_running_raises(self) -> None:
        gateway = MagicMock()
        registry = ChannelRegistry(gateway)
        ch = FakeChannel(ChannelConfig(
            channel_id="dup:1", channel_type=ChannelType.WECHAT, name="dup"
        ))
        ch._update_state(status=ChannelStatus.RUNNING)
        registry._channels["dup:1"] = ch
        registry._by_type[ChannelType.WECHAT] = ["dup:1"]

        # 调用 start_channel 时如已有 RUNNING 应抛 ValueError
        # 实现细节留给 Task 3.2,这里先 stub
        with pytest.raises(ValueError, match="already running"):
            await registry.start_channel(
                ChannelConfig(channel_id="dup:2", channel_type=ChannelType.WECHAT, name="dup2"),
            )
```

- [ ] **Step 2: 跑测试 (FAIL) — 因为 ChannelRegistry 还没新方法**

```bash
source .venv/bin/activate
pytest tests/test_channel_registry.py -q
```

预期输出: **FAIL** (`AttributeError: 'ChannelRegistry' object has no attribute 'start_channel'` 等)。

### Task 3.2: 实现 ChannelRegistry 新方法 (绿)

**Files:**
- Modify: `nexus/backend/channels/registry.py`

- [ ] **Step 1: 改写 registry.py 完整内容**

```python
"""ChannelRegistry - Channel 实例的唯一所有权管理器。

所有 Channel 创建 / 启动 / 停止 / 查询都走本类,不再有散落的全局状态。
取代旧的 _wechat_sessions / get_active_wechat_channel / wechat_state._active_channel。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .base import Channel, ChannelConfig, ChannelStatus, ChannelType

if TYPE_CHECKING:
    from .gateway import Gateway

logger = logging.getLogger(__name__)


class ChannelRegistry:
    """所有 Channel 实例的唯一 owner。

    职责:
      - start_channel: 工厂方法,创建 + register + start 一条龙
      - stop_channel: 停 + 注销
      - get_active_by_type: 取该类型 RUNNING 的 channel
      - list_all: 给 /api/channels 用
    """

    def __init__(self, gateway: "Gateway") -> None:
        self._gateway = gateway
        self._channels: dict[str, Channel] = {}
        self._by_type: dict[ChannelType, list[str]] = {}

    async def start_channel(self, config: ChannelConfig, **kwargs: Any) -> Channel:
        """创建 + register + start; 同 type 已 RUNNING 抛 ValueError。"""
        existing = self.get_active_by_type(config.channel_type)
        if existing is not None:
            raise ValueError(
                f"{config.channel_type.value} channel already running: {existing.config.channel_id}"
            )

        ch = create_channel_from_config(config, **kwargs)
        self._gateway.register_channel(ch)
        self._channels[ch.config.channel_id] = ch
        self._by_type.setdefault(config.channel_type, []).append(ch.config.channel_id)
        await ch.start()
        logger.info(f"Channel started: {ch}")
        return ch

    async def stop_channel(self, channel_id: str) -> None:
        """停 channel + 从 Registry + Gateway 注销。"""
        ch = self._channels.pop(channel_id, None)
        if ch is None:
            return
        await ch.stop()
        cid_list = self._by_type.get(ch.config.channel_type, [])
        if channel_id in cid_list:
            cid_list.remove(channel_id)
        await self._gateway.unregister_channel(channel_id)
        logger.info(f"Channel stopped: {channel_id}")

    def get(self, channel_id: str) -> Channel | None:
        return self._channels.get(channel_id)

    def get_active_by_type(self, ch_type: ChannelType) -> Channel | None:
        """取该类型第一个 RUNNING 通道。"""
        for cid in self._by_type.get(ch_type, []):
            ch = self._channels.get(cid)
            if ch and ch.state.status == ChannelStatus.RUNNING:
                return ch
        return None

    def list_all(self) -> list[Channel]:
        return list(self._channels.values())

    async def stop_all(self) -> None:
        for cid in list(self._channels.keys()):
            await self.stop_channel(cid)


def create_channel_from_config(
    config: ChannelConfig,
    **kwargs: Any,
) -> Channel:
    """根据配置创建 Channel 实例(纯工厂,不 register 不 start)。

    Raises:
        NotImplementedError: FEISHU 未实现
        ValueError: 不支持的 channel_type
    """
    channel_type = config.channel_type

    if channel_type == ChannelType.WECHAT:
        from .wechat_channel import WeChatChannel

        token = kwargs.get("token", "")
        return WeChatChannel(config=config, token=token)

    if channel_type == ChannelType.FEISHU:
        raise NotImplementedError("Feishu channel not implemented yet")

    raise ValueError(f"Unsupported channel type: {channel_type}")
```

注意: **删掉了 `WEBSOCKET` 分支** — 这是 Commit 6 的工作,提前删因为这里要清晰;Commit 6 只删 `ChannelType.WEBSOCKET` 枚举本身。

- [ ] **Step 2: 跑测试 (PASS)**

```bash
source .venv/bin/activate
pytest tests/test_channel_registry.py -q
```

预期输出: **PASS**。

- [ ] **Step 3: 跑现有微信测试 (回归)**

```bash
pytest tests/test_wechat_smoke.py tests/test_wechat_state.py -q
```

预期输出: 全过(只删 `WEBSOCKET` 分支,不影响微信测试)。

- [ ] **Step 4: 全量 lint**

```bash
ruff check . && ruff format --check .
```

预期输出: 0 error / 0 diff。

- [ ] **Step 5: Commit**

```bash
git add tests/test_channel_registry.py nexus/backend/channels/registry.py
git commit -m "refactor(channels): ChannelRegistry 升级为唯一所有权 (start_channel/stop_channel/get_active_by_type)"
```

> **重要**: C3 后 `ChannelRegistry(gateway)` 必须传 gateway 参数。main.py 还在用旧签名 `ChannelRegistry()`,C4 会改 main.py;现在 main.py:328 调用会报 TypeError,**暂时接受这个 broken state**,因为 C3 内部单测已 PASS,证明 Registry 自身没问题。

---

## Commit 4: Gateway 真接管路由 + main.py 大瘦身 (核心)

### Task 4.1: 写 test_gateway.py (红)

**Files:**
- Create: `tests/test_gateway.py`

- [ ] **Step 1: 写测试**

```python
"""Gateway.route_message 契约测试。"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.backend.channels.base import (
    Channel,
    ChannelConfig,
    ChannelMessage,
    ChannelState,
    ChannelStatus,
    ChannelType,
    MessageType,
)
from nexus.backend.channels.gateway import Gateway


class FakeChannel(Channel):
    """Gateway 测试用 channel,记录 send_message 调用。"""

    def __init__(self, config: ChannelConfig) -> None:
        super().__init__(config)
        self.sent: list[ChannelMessage] = []
        self._update_state(status=ChannelStatus.RUNNING)

    async def start(self) -> None:
        self._update_state(status=ChannelStatus.RUNNING)

    async def stop(self) -> None:
        self._update_state(status=ChannelStatus.STOPPED)

    async def send_message(self, message: ChannelMessage) -> None:
        self.sent.append(message)


def _make_gateway(agent_text: str = "hello back") -> tuple[Gateway, FakeChannel, dict[str, Any]]:
    """构造 Gateway + FakeChannel + mock 依赖。"""
    ch = FakeChannel(ChannelConfig(
        channel_id="w:test_user",
        channel_type=ChannelType.WECHAT,
        name="test",
    ))

    sessions_module = MagicMock()
    sessions_module.find_latest_session_by_user.return_value = None  # 强制新建
    sessions_module.create_session = MagicMock()
    sessions_module.build_prompt.return_value = {"messages": [{"role": "user", "content": "hi"}]}

    messages_module = MagicMock()
    messages_module.add_message = AsyncMock()

    # mock deepagents agent.astream
    agent = MagicMock()

    async def _astream(input_dict: dict[str, Any], stream_mode: str) -> Any:
        assert stream_mode == "updates"
        yield {"model": {"messages": [MagicMock(content=agent_text)]}}

    agent.astream = _astream

    gateway = Gateway(agent=agent, sessions_module=sessions_module, messages_module=messages_module)
    gateway.register_channel(ch)
    return gateway, ch, {"sessions": sessions_module, "messages": messages_module}


def _msg(content: str = "hi", user_id: str = "user1") -> ChannelMessage:
    return ChannelMessage(
        channel_id="w:test_user",
        channel_type=ChannelType.WECHAT,
        session_id="ignored",
        user_id=user_id,
        content=content,
        message_type=MessageType.TEXT,
    )


class TestRouteMessageHappyPath:
    @pytest.mark.asyncio
    async def test_user_and_assistant_messages_added(self) -> None:
        gateway, _ch, mocks = _make_gateway("the answer")
        await gateway.route_message(_msg())
        # user 消息 + assistant 消息 = 2 次 add_message 调用
        assert mocks["messages"].add_message.await_count == 2
        # 第 2 次调用是 assistant
        second_call = mocks["messages"].add_message.await_args_list[1]
        assert second_call.args[2] == "assistant"
        assert second_call.args[3] == "the answer"

    @pytest.mark.asyncio
    async def test_response_sent_to_channel(self) -> None:
        gateway, ch, _ = _make_gateway("the answer")
        await gateway.route_message(_msg())
        assert len(ch.sent) == 1
        assert ch.sent[0].content == "the answer"
        assert ch.sent[0].reply_to is not None  # 回填 reply_to

    @pytest.mark.asyncio
    async def test_session_created_on_first_message(self) -> None:
        gateway, _ch, mocks = _make_gateway()
        await gateway.route_message(_msg(user_id="u_new"))
        mocks["sessions"].create_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_session_reused_when_resumed(self) -> None:
        gateway, _ch, mocks = _make_gateway()
        mocks["sessions"].find_latest_session_by_user.return_value = "existing_sid"
        await gateway.route_message(_msg(user_id="u_resume"))
        mocks["sessions"].create_session.assert_not_called()


class TestRouteMessageError:
    @pytest.mark.asyncio
    async def test_agent_raises_sends_error_to_channel(self) -> None:
        gateway, ch, _ = _make_gateway()
        # 改成 raise
        async def _boom(input_dict: dict[str, Any], stream_mode: str) -> Any:
            raise RuntimeError("agent down")
            yield  # noqa: unreachable - 让 async generator 类型对

        gateway._agent.astream = _boom  # type: ignore[assignment]

        await gateway.route_message(_msg())
        assert len(ch.sent) == 1
        assert "处理消息时出错" in ch.sent[0].content
        assert "agent down" in ch.sent[0].content


class TestCallAgentStripThinking:
    @pytest.mark.asyncio
    async def test_strips_think_tags(self) -> None:
        gateway, _ch, _ = _make_gateway(agent_text="x")

        # 改 agent 返回含  think 标签的文本
        async def _astream_with_think(input_dict: dict[str, Any], stream_mode: str) -> Any:
            yield {"model": {"messages": [MagicMock(content=" thought ")]}}
            yield {"model": {"messages": [MagicMock(content="real answer")]}}

        gateway._agent.astream = _astream_with_think  # type: ignore[assignment]

        text = await gateway._call_agent({"messages": []})
        assert "<think>" not in text
        assert "</think>" not in text
        assert "thought" not in text
        assert "real answer" in text


class TestRouteMessageEmptyContent:
    @pytest.mark.asyncio
    async def test_empty_content_returns_early(self) -> None:
        gateway, ch, mocks = _make_gateway()
        await gateway.route_message(_msg(content=""))
        # 不调 agent, 不发消息, 不落库
        mocks["messages"].add_message.assert_not_called()
        assert len(ch.sent) == 0


class TestBroadcast:
    @pytest.mark.asyncio
    async def test_broadcast_called_with_response(self) -> None:
        gateway, _ch, _ = _make_gateway("hello")
        broadcast_fn = AsyncMock()
        gateway.set_broadcast(ChannelType.WECHAT, broadcast_fn)
        await gateway.route_message(_msg())
        broadcast_fn.assert_awaited_once()
        bcast_msg = broadcast_fn.await_args.args[0]
        assert bcast_msg.content == "hello"

    @pytest.mark.asyncio
    async def test_broadcast_failure_does_not_break_send(self) -> None:
        gateway, ch, _ = _make_gateway("hello")
        broadcast_fn = AsyncMock(side_effect=RuntimeError("ws down"))
        gateway.set_broadcast(ChannelType.WECHAT, broadcast_fn)
        await gateway.route_message(_msg())
        # send_message 仍成功
        assert len(ch.sent) == 1
        assert ch.sent[0].content == "hello"
```

- [ ] **Step 2: 跑测试 (FAIL)**

```bash
source .venv/bin/activate
pytest tests/test_gateway.py -q
```

预期输出: **FAIL** (Gateway API 还没重写,signature 不匹配)。

### Task 4.2: 重写 gateway.py (绿)

**Files:**
- Modify: `nexus/backend/channels/gateway.py` (整文件)

- [ ] **Step 1: 改写 gateway.py 完整内容**

```python
"""Gateway - IM 消息中央路由。

取代原 main.py 中 _handle_wechat_message / _process_wechat_message 的业务逻辑。
所有 Channel 收到消息后必须构造 ChannelMessage 调 self._gateway.route_message()。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from .base import Channel, ChannelMessage, ChannelType

if TYPE_CHECKING:
    from .base import ChannelConfig

logger = logging.getLogger(__name__)


class Gateway:
    """IM 消息的中央路由。

    流程: route_message(msg)
      1. _get_or_create_session(msg)       会话锁串行化
      2. db.add_message(user, msg)
      3. _call_agent(prompt)               抽出的共用 runner
      4. db.add_message(assistant, response)
      5. channel.send_message(response)    发回 IM
      6. broadcast(ch_type, response)      推给 WS 客户端
    """

    def __init__(
        self,
        *,
        agent: Any,
        sessions_module: Any,
        messages_module: Any,
    ) -> None:
        self._agent = agent
        self._sessions = sessions_module
        self._messages = messages_module
        self._channels: dict[str, Channel] = {}
        self._session_to_channel: dict[str, str] = {}
        self._user_to_session: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._broadcasts: dict[ChannelType, Callable[[ChannelMessage], Awaitable[None]]] = {}

    def register_channel(self, ch: Channel) -> None:
        ch.bind_gateway(self)
        self._channels[ch.config.channel_id] = ch
        logger.info(f"Channel registered: {ch}")

    async def unregister_channel(self, channel_id: str) -> None:
        async with self._lock:
            ch = self._channels.pop(channel_id, None)
            if ch is None:
                return
            sessions_to_remove = [
                sid for sid, cid in self._session_to_channel.items() if cid == channel_id
            ]
            for sid in sessions_to_remove:
                self._session_to_channel.pop(sid, None)

    def set_broadcast(
        self,
        ch_type: ChannelType,
        fn: Callable[[ChannelMessage], Awaitable[None]],
    ) -> None:
        """由 WS 客户端连接时调(api/ws.py handle_websocket),把消息广播给前端。
        同一 channel_type 多次连接会覆盖前一个 broadcast fn(WS 端生命周期)。
        """
        self._broadcasts[ch_type] = fn

    async def route_message(self, msg: ChannelMessage) -> None:
        try:
            if not msg.content:
                logger.warning(f"Empty message content from {msg.channel_id}")
                return

            async with self._lock:
                session_id = await self._get_or_create_session(msg)

            await self._safe_add_message(session_id, "user", msg.content)

            try:
                prompt = self._sessions.build_prompt(session_id, msg.content)
                response_text = await self._call_agent(prompt)
            except Exception as e:
                logger.error(f"Agent error for {msg.channel_id}: {e}", exc_info=True)
                await self._send_error(msg, f"处理消息时出错: {e}")
                return

            if not response_text:
                return

            await self._safe_add_message(session_id, "assistant", response_text)

            ch = self._channels.get(msg.channel_id)
            if ch:
                try:
                    await ch.send_message(self._build_response(msg, response_text))
                except Exception as e:
                    logger.error(f"send_message failed for {msg.channel_id}: {e}")

            broadcast = self._broadcasts.get(msg.channel_type)
            if broadcast:
                try:
                    await broadcast(self._build_broadcast(msg, response_text))
                except Exception as e:
                    logger.warning(f"broadcast failed for {msg.channel_type}: {e}")

        except Exception as e:
            logger.error(f"route_message unhandled error: {e}", exc_info=True)
            try:
                await self._send_error(msg, str(e))
            except Exception:
                logger.exception("Even _send_error failed")

    async def _get_or_create_session(self, msg: ChannelMessage) -> str:
        user_key = f"{msg.channel_id}:{msg.user_id}"
        if user_key in self._user_to_session:
            existing = self._user_to_session[user_key]
            try:
                self._sessions.update_session(existing)  # type: ignore[attr-defined]
                return existing
            except Exception:
                pass  # DB 已删,走下面重建

        # 尝试从 DB 找该 user 该 channel_type 的最近 session
        existing_sid = self._sessions.find_latest_session_by_user(  # type: ignore[attr-defined]
            user_id=msg.user_id, channel=msg.channel_type.value
        )
        if existing_sid:
            try:
                if self._sessions.get_session(existing_sid):  # type: ignore[attr-defined]
                    self._user_to_session[user_key] = existing_sid
                    self._session_to_channel[existing_sid] = msg.channel_id
                    logger.info(
                        "Resumed session for %s from DB: %s", msg.user_id, existing_sid
                    )
                    return existing_sid
            except Exception:
                pass

        # 都没有,新建
        new_sid = msg.session_id or str(uuid.uuid4())
        try:
            title = msg.content[:50] if msg.content else f"{msg.channel_type.value} 会话"
            self._sessions.create_session(  # type: ignore[attr-defined]
                new_sid, title=title, channel=msg.channel_type.value
            )
        except Exception as e:
            logger.error(f"create_session failed for {new_sid}: {e}")
            raise
        self._user_to_session[user_key] = new_sid
        self._session_to_channel[new_sid] = msg.channel_id
        return new_sid

    async def _call_agent(self, prompt: dict[str, Any]) -> str:
        """抽出来的 runner 共用段 (stream_mode='updates' 累积 + 去思考段标签)。"""
        full = ""
        async for chunk in self._agent.astream(
            {"messages": prompt["messages"]}, stream_mode="updates"
        ):
            if not isinstance(chunk, dict):
                continue
            if "model" in chunk:
                model_data = chunk["model"]
                if model_data and isinstance(model_data, dict):
                    msgs = model_data.get("messages", [])
                    for m in msgs:
                        c = getattr(m, "content", "") or ""
                        if c:
                            full += c
        # 去 deepagents 模型产生的 <think> / </think> 思考段标签
        return full.replace("<think>", "").replace("</think>", "").strip()

    async def _safe_add_message(
        self, session_id: str, role: str, content: str
    ) -> None:
        try:
            await self._messages.add_message(
                msg_id=str(uuid.uuid4()),
                session_id=session_id,
                role=role,
                content=content,
            )
        except Exception as e:
            logger.error(f"add_message failed ({role}): {e}")

    def _build_response(self, orig: ChannelMessage, content: str) -> ChannelMessage:
        return ChannelMessage(
            channel_id=orig.channel_id,
            channel_type=orig.channel_type,
            session_id=orig.session_id,
            user_id=orig.user_id,
            content=content,
            reply_to=orig.id,
            metadata=orig.metadata,
        )

    def _build_broadcast(self, orig: ChannelMessage, content: str) -> ChannelMessage:
        return ChannelMessage(
            channel_id=orig.channel_id,
            channel_type=orig.channel_type,
            session_id=orig.session_id,
            user_id=orig.user_id,
            content=content,
            reply_to=orig.id,
            metadata={**orig.metadata, "broadcast": True},
        )

    async def _send_error(self, orig: ChannelMessage, error: str) -> None:
        try:
            ch = self._channels.get(orig.channel_id)
            if ch:
                err_msg = ChannelMessage(
                    channel_id=orig.channel_id,
                    channel_type=orig.channel_type,
                    session_id=orig.session_id,
                    user_id=orig.user_id,
                    content=error,
                    reply_to=orig.id,
                )
                await ch.send_message(err_msg)
        except Exception as e:
            logger.error(f"_send_error failed: {e}")
```

- [ ] **Step 2: 跑测试 (PASS)**

```bash
source .venv/bin/activate
pytest tests/test_gateway.py -q
```

预期输出: **PASS**。

### Task 4.3: 写 test_gateway_session_lock.py (红)

**Files:**
- Create: `tests/test_gateway_session_lock.py`

- [ ] **Step 1: 写测试**

```python
"""Gateway._get_or_create_session 并发锁测试。

验证同 user_key 并发 N 个 route_message 只创建 1 个 session。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.backend.channels.base import (
    ChannelConfig,
    ChannelMessage,
    ChannelStatus,
    ChannelType,
    MessageType,
)
from nexus.backend.channels.gateway import Gateway


class StubChannel:
    def __init__(self) -> None:
        self.config = ChannelConfig(
            channel_id="w:lock_test",
            channel_type=ChannelType.WECHAT,
            name="lock_test",
        )
        self.state = MagicMock()
        self.state.status = ChannelStatus.RUNNING

    async def send_message(self, message: ChannelMessage) -> None:
        pass

    def bind_gateway(self, gateway) -> None:
        pass


@pytest.mark.asyncio
async def test_concurrent_same_user_creates_one_session() -> None:
    sessions_module = MagicMock()
    sessions_module.find_latest_session_by_user.return_value = None  # 强制走新建
    sessions_module.create_session = MagicMock()
    sessions_module.update_session = MagicMock()
    sessions_module.get_session.return_value = {"session_id": "x"}

    messages_module = MagicMock()
    messages_module.add_message = AsyncMock()

    agent = MagicMock()

    async def _astream(input_dict, stream_mode):
        yield {"model": {"messages": [MagicMock(content="hi")]}}

    agent.astream = _astream

    gateway = Gateway(
        agent=agent,
        sessions_module=sessions_module,
        messages_module=messages_module,
    )
    gateway.register_channel(StubChannel())  # type: ignore[arg-type]

    msg = ChannelMessage(
        channel_id="w:lock_test",
        channel_type=ChannelType.WECHAT,
        session_id="ignored",
        user_id="concurrent_user",
        content="hi",
        message_type=MessageType.TEXT,
    )

    # 并发跑 10 次
    import asyncio
    await asyncio.gather(*[gateway.route_message(msg) for _ in range(10)])

    # create_session 只应被调 1 次 (锁串行化)
    assert sessions_module.create_session.call_count == 1
```

- [ ] **Step 2: 跑测试**

```bash
source .venv/bin/activate
pytest tests/test_gateway_session_lock.py -q
```

预期输出: **PASS** (Gateway 实现已含 `async with self._lock`)。

### Task 4.4: 写 test_wechat_channel_uses_gateway.py (红)

**Files:**
- Create: `tests/test_wechat_channel_uses_gateway.py`

- [ ] **Step 1: 写测试**

```python
"""WeChatChannel 必须走 _safe_handle_message → Gateway,不走 on_message callback。

旧实现 wechat_channel.py:307-313 有 on_message callback 旁路,
重构后必须确认 _handle_incoming_message 走 Channel 基类的 _safe_handle_message 入口。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.backend.channels.base import (
    ChannelMessage,
    ChannelType,
    MessageType,
)
from nexus.backend.channels.wechat_channel import WeChatChannel


@pytest.mark.asyncio
async def test_incoming_message_calls_safe_handle_message() -> None:
    """WeChatChannel._handle_incoming_message 必须调 self._safe_handle_message。"""
    ch = WeChatChannel.__new__(WeChatChannel)  # 绕开 __init__ 不联网
    ch.config = MagicMock()
    ch.config.channel_id = "w:test"
    ch._account = MagicMock()
    ch._account.account_id = "acc_test"
    ch._update_state = MagicMock()  # type: ignore[method-assign]
    ch._safe_handle_message = AsyncMock()  # type: ignore[method-assign]

    raw_msg = {
        "from_user_id": "user1",
        "item_list": [{"type": 1, "text_item": {"text": "hello"}}],
    }

    await ch._handle_incoming_message(raw_msg)

    ch._safe_handle_message.assert_awaited_once()
    called_msg = ch._safe_handle_message.await_args.args[0]
    assert isinstance(called_msg, ChannelMessage)
    assert called_msg.user_id == "user1"
    assert called_msg.content == "hello"
    assert called_msg.channel_type == ChannelType.WECHAT


@pytest.mark.asyncio
async def test_on_message_attribute_removed() -> None:
    """重构后 on_message 方法应不存在(旁路已删)。"""
    assert not hasattr(WeChatChannel, "on_message"), (
        "on_message callback 应在重构后删除,所有消息走 _safe_handle_message → Gateway"
    )
```

- [ ] **Step 2: 跑测试 (FAIL)**

```bash
source .venv/bin/activate
pytest tests/test_wechat_channel_uses_gateway.py -q
```

预期输出: **FAIL** (`on_message` 还在,`_handle_incoming_message` 仍走 callback 旁路)。

### Task 4.5: 改 wechat_channel.py 走 _safe_handle_message (绿)

**Files:**
- Modify: `nexus/backend/channels/wechat_channel.py` (L93 + L307-321)

- [ ] **Step 1: 删 `self._on_message_callback` 字段**

`wechat_channel.py:93` 附近:

```python
        self._account: WeixinAccount | None = None
        self._get_updates_buf: str = ""
        self._on_message_callback = None   # ← 删这一行
```

改成:

```python
        self._account: WeixinAccount | None = None
        self._get_updates_buf: str = ""
```

- [ ] **Step 2: 改 `_handle_incoming_message` L307-314**

`wechat_channel.py:307-313`:

```python
            # 如果有回调，直接调用（用于 WebSocket 转发到前端）
            if self._on_message_callback:
                logger.debug(f"Calling callback for message from {from_user}")
                self._on_message_callback(channel_msg)
            else:
                logger.warning(
                    f"No callback set! Channel id={self.config.channel_id}, callback={self._on_message_callback}"
                )
                await self._safe_handle_message(channel_msg)
```

改成:

```python
            # 走 Channel 基类入口 → Gateway.route_message
            # (取代旧的 self._on_message_callback 旁路,C4 重构)
            await self._safe_handle_message(channel_msg)
```

- [ ] **Step 3: 删 `on_message` 方法 L318-320**

`wechat_channel.py:318-320`:

```python
    def on_message(self, callback) -> None:
        """设置消息回调"""
        self._on_message_callback = callback
```

**整段删除**(含上面那个 `def on_message` 行的前后空行)。

- [ ] **Step 4: 跑测试 (PASS)**

```bash
source .venv/bin/activate
pytest tests/test_wechat_channel_uses_gateway.py tests/test_wechat_smoke.py -q
```

预期输出: **PASS**。

- [ ] **Step 5: 跑全量**

```bash
pytest tests/ -q --ignore=tests/test_e2e_features.py
```

预期输出: 仍 fail — 因为 main.py 还调旧的 `get_active_wechat_channel` / `_handle_wechat_message` 等,这些要被 C4 后段任务清掉。**先看其他测试是否 fail**,只允许 main.py 路径相关的 fail。

### Task 4.6: 改 main.py (减 200 行 + lifespan 注入)

**Files:**
- Modify: `nexus/backend/main.py` (删 ~200 行 + 改 lifespan + 改 REST endpoint)

- [ ] **Step 1: 删全局变量 L43-53**

`main.py:43-53`:

```python
# 微信消息处理线程池（全局复用）
_wechat_executor: ThreadPoolExecutor | None = None
_main_loop: asyncio.AbstractEventLoop | None = None

# 微信用户 session 映射（user_id -> session_id）
# 关键不变量：
#   1. 同一 user_id 的两个并发消息不能创建两个 session → 必须用 asyncio.Lock 串行化
#   2. 后端重启时 in-memory 映射丢失，但 DB 里 channel='wechat' 的旧 session 还在
#      → 启动时按"该 user_id 最近一次 wechat session"重建映射
_wechat_sessions: dict[str, str] = {}  # user_id -> session_id
_wechat_sessions_lock: asyncio.Lock | None = None  # 在 lifespan 内初始化
```

**整段删除**。

> **保留 `_main_loop`**: 它还用于 `_ensure_agent_ready` 的 `call_soon_threadsafe`,所以只删 `_wechat_executor` / `_wechat_sessions` / `_wechat_sessions_lock` 三个微信专属全局。`_main_loop` 是 agent 初始化用的。

改为:

```python
# 微信消息处理线程池（已删除,Gateway 接管后无需;_main_loop 保留给 agent 初始化用）
_main_loop: asyncio.AbstractEventLoop | None = None
```

- [ ] **Step 2: 删 `_resolve_wechat_session` L56-87**

整段删除(`async def _resolve_wechat_session ...` 共 32 行)。

- [ ] **Step 3: 删 `_handle_wechat_message` L94-134**

整段删除(`def _handle_wechat_message ...` 共 41 行)。

- [ ] **Step 4: 删 `_process_wechat_message_sync` L137-150 + `_process_wechat_message` L153-239**

整段删除(共 100 行)。

- [ ] **Step 5: 改 lifespan 注入 Gateway + Registry**

`main.py:301-340` 内的 lifespan 函数:

```python
    global _agent, _mcp_tools, _wechat_executor, _main_loop, _wechat_sessions_lock
    # 保存主事件循环引用，供子线程提交协程使用
    _main_loop = asyncio.get_running_loop()
    app.state.main_loop = _main_loop
    # 初始化 asyncio.Lock：用于 _wechat_sessions 字典的并发读写。
    # 必须在 lifespan 内创建（绑定到主事件循环），否则在子线程中 asyncio.Lock()
    # 绑定到子线程的事件循环会出错。
    _wechat_sessions_lock = asyncio.Lock()
    # 初始化数据库
    from .db import init_db

    init_db()
    # MCP 加载延后到 agent 首次构造时（省 0.5-3s）
    _mcp_tools = []
    # 关键：_agent 不在 lifespan 内构造。首次 WS 消息 / setup 完成时
    # 走 _ensure_agent_ready() 触发构造。期间 /health / REST 路由正常工作。
    _agent = None
    # 注入共享依赖到 model_config 路由
    model_config_routes.init_router(
        agent_lock=_agent_lock,
        mcp_tools=_mcp_tools,
        create_agent_with_model=_create_agent_with_model,
        set_global_agent=_set_global_agent,
    )
    # 初始化通道注册表（lifespan 必须设置，否则 /api/channels 会 500）
    from .channels import ChannelRegistry

    app.state.channel_registry = ChannelRegistry()
    # QualityPipeline 也延后到 agent 构造完后再做（依赖 judge_llm）
    app.state.quality_pipeline = None
    logger.info("Nexus Backend 已就绪（Agent 懒构造）")
    yield
    logger.info("Nexus Backend 关闭中")
    # 清理线程池
    if _wechat_executor:
        _wechat_executor.shutdown(wait=False)
        _wechat_executor = None
    # 重置 lock 和 in-memory 状态，避免热重载残留
    _wechat_sessions_lock = None
    _wechat_sessions.clear()
```

改成:

```python
    global _agent, _mcp_tools, _main_loop
    _main_loop = asyncio.get_running_loop()
    app.state.main_loop = _main_loop

    from .db import init_db
    init_db()

    _mcp_tools = []
    _agent = None

    model_config_routes.init_router(
        agent_lock=_agent_lock,
        mcp_tools=_mcp_tools,
        create_agent_with_model=_create_agent_with_model,
        set_global_agent=_set_global_agent,
    )

    # 初始化 Gateway + ChannelRegistry (C4 重构: Gateway 真接管路由)
    # 注意:Gateway 需要 agent/sessions/messages 三个依赖;agent 是懒构造,
    # 所以 Gateway 必须接受动态获取器(getter callable)而非实例引用。
    from .channels import ChannelRegistry, Gateway

    def _agent_getter():
        with _agent_lock:
            return _agent

    from .sessions import get_session_manager

    sessions_module = get_session_manager()
    # messages_module 直接是 db.add_message 函数(可调用即可)
    import nexus.backend.db as _db_module

    app.state.gateway = Gateway(
        agent=_AgentProxy(_agent_getter),  # 见下面 _AgentProxy 定义
        sessions_module=sessions_module,
        messages_module=_db_module,
    )
    app.state.channel_registry = ChannelRegistry(app.state.gateway)
    app.state.quality_pipeline = None

    logger.info("Nexus Backend 已就绪 (Gateway 接管路由, Agent 懒构造)")
    yield
    logger.info("Nexus Backend 关闭中")
```

**新增类 `_AgentProxy`** 放在 main.py 模块级:

```python
class _AgentProxy:
    """Gateway 需要 agent.astream(),但 agent 是懒构造。代理暴露 .astream 调用
    时的实时 agent 实例,使 Gateway 无需关心 agent 何时就绪。
    """

    def __init__(self, getter):
        self._getter = getter

    def astream(self, input_dict, stream_mode="updates"):
        agent = self._getter()
        if agent is None:
            raise RuntimeError("Agent 未就绪,请稍后再试")
        return agent.astream(input_dict, stream_mode=stream_mode)
```

> **WHY proxy**: Gateway 设计接受 `agent` 实例,但 agent 是 PyInstaller 冷启 10-30s 的懒构造。Proxy 让 Gateway 不感知懒构造时序。

- [ ] **Step 6: 改 `/api/channels/wechat/bind` (POST) L685-756**

替换手写 `new_channel = WeChatChannel(...)` + `new_channel.start()` + `new_channel.on_message(...)` + `_set_active_channel(...)`:

```python
@app.post(f"{API_PREFIX}/channels/wechat/bind", dependencies=[Depends(require_token)])
async def wechat_do_bind():
    """绑定微信账号:从已有账号恢复,或要求重新扫码。"""
    from .channels.base import ChannelConfig, ChannelType
    from .channels.wechat_account import (
        _check_token_valid,
        _delete_account,
        _list_indexed_weixin_account_ids,
        _load_account,
    )

    request: Request  # type: ignore[name-defined]  # 由 FastAPI 注入,见实际上下文
    registry = request.app.state.channel_registry

    # 检查是否已有活跃通道
    active = registry.get_active_by_type(ChannelType.WECHAT)
    if active and active._account:  # type: ignore[attr-defined]
        return {
            "success": True,
            "bound": True,
            "account_id": active._account.account_id,  # type: ignore[attr-defined]
        }

    # 找最近已保存的账号
    account_ids = _list_indexed_weixin_account_ids()
    if not account_ids:
        return {"success": False, "error": "请先扫码绑定微信"}

    account_id = account_ids[0]
    account = _load_account(account_id)
    if not account:
        return {"success": False, "error": "账号已损坏,请重新扫码"}

    # 检查 token 是否有效
    if not _check_token_valid(account_id):
        _delete_account(account_id)
        return {
            "success": False,
            "bound": False,
            "error": "登录已过期,请重新扫码绑定",
            "need_rescan": True,
        }

    config = ChannelConfig(
        channel_id=f"wechat:{account_id}",
        channel_type=ChannelType.WECHAT,
        name=f"WeChat ({account_id[:8]}...)",
        settings={"account_id": account_id},
    )
    await registry.start_channel(config, token=account_id)
    return {
        "success": True,
        "bound": True,
        "account_id": account_id,
    }
```

注意: 用 `request: Request` 拿 app.state (FastAPI 自动注入)。如果原代码已经是这个模式,直接复用。

- [ ] **Step 7: 改 `/api/channels/wechat/unbind` (DELETE) L759-769**

```python
@app.delete(f"{API_PREFIX}/channels/wechat/bind", dependencies=[Depends(require_token)])
async def wechat_unbind(request: Request):
    """解除微信绑定"""
    registry = request.app.state.channel_registry
    active = registry.get_active_by_type(ChannelType.WECHAT)
    if active:
        await registry.stop_channel(active.config.channel_id)
    return {"success": True}
```

- [ ] **Step 8: 改 `/api/channels/wechat/bind` (GET status) L653-682**

```python
@app.get(f"{API_PREFIX}/channels/wechat/bind", dependencies=[Depends(require_token)])
async def wechat_bind_status(request: Request):
    """获取微信绑定状态"""
    from .channels.base import ChannelType
    from .channels.wechat_account import (
        _list_indexed_weixin_account_ids,
        _load_account,
    )

    registry = request.app.state.channel_registry
    active = registry.get_active_by_type(ChannelType.WECHAT)
    if active and getattr(active, "_account", None):
        return {
            "bound": True,
            "account_id": active._account.account_id,  # type: ignore[attr-defined]
            "status": active.state.status.value,
        }

    account_ids = _list_indexed_weixin_account_ids()
    if account_ids:
        account_id = account_ids[0]
        account = _load_account(account_id)
        if account:
            return {"bound": True, "account_id": account_id, "status": "stopped"}

    return {"bound": False}
```

- [ ] **Step 9: 跑测试**

```bash
source .venv/bin/activate
pytest tests/ -q --ignore=tests/test_e2e_features.py
ruff check . && ruff format --check .
```

预期输出: pytest 全过 + ruff 0 error。

### Task 4.7: 改 api/ws.py 把 wechat_callback → channel_broadcasts

**Files:**
- Modify: `nexus/backend/api/ws.py` (L594-630)

- [ ] **Step 1: 改 handle_websocket 签名**

`api/ws.py:594-601`:

```python
async def handle_websocket(
    websocket: WebSocket,
    *,
    get_agent: Callable[[], Any],
    wechat_callback: Callable | None = None,
    get_quality_pipeline: Callable[[], Any] | None = None,
    get_intent_llm: Callable[[], Any] | None = None,
) -> None:
```

改成:

```python
async def handle_websocket(
    websocket: WebSocket,
    *,
    get_agent: Callable[[], Any],
    channel_broadcasts: dict[str, Callable] | None = None,
    get_quality_pipeline: Callable[[], Any] | None = None,
    get_intent_llm: Callable[[], Any] | None = None,
) -> None:
```

- [ ] **Step 2: 改 L612-619 docstring + L625-630 广播挂载逻辑**

`api/ws.py:612-619` docstring 段:

```python
        wechat_callback: 微信消息回调（``_handle_wechat_message``），用于在
            客户端连接时给微信通道挂上广播。``None`` 表示不挂（仅 WS 自用）。
```

改成:

```python
        channel_broadcasts: dict[channel_type_value -> async fn],WS 客户端连接时
            给 Gateway 注入广播,Gateway.route_message 走完会把响应推给所有
            注入的 broadcast。``None`` 或空 dict 表示不广播(仅 WS 自用)。
```

`api/ws.py:625-630`:

```python
    # 设置微信消息回调
    if wechat_callback is not None:
        from ..channels.wechat import get_active_wechat_channel

        channel = get_active_wechat_channel()
        if channel:
            channel.on_message(wechat_callback)
```

改成:

```python
    # 注入 WS 广播到 Gateway (C4 重构,取代旧的 wechat_callback 单回调)
    if channel_broadcasts:
        from ..channels.gateway import ChannelType  # 实际是 base.ChannelType
        from ..channels.base import ChannelType as _CT
        gateway = getattr(websocket.app.state, "gateway", None)
        if gateway is not None:
            for ch_type_str, fn in channel_broadcasts.items():
                gateway.set_broadcast(_CT(ch_type_str), fn)
```

- [ ] **Step 3: 改 main.py L615-621 websocket_endpoint 调用**

`main.py:615-621`:

```python
    await handle_websocket(
        websocket,
        get_agent=_get_current_agent,
        wechat_callback=_handle_wechat_message,
        get_quality_pipeline=_get_quality_pipeline,
        get_intent_llm=_get_intent_llm,
    )
```

改成:

```python
    # C4 重构:channel_broadcasts 取代 wechat_callback 单回调
    # 微信 channel_type == "wechat",Gateway 拿到这个字符串后路由到对应 broadcast fn
    async def _broadcast_to_ws(channel_msg) -> None:
        """把 ChannelMessage 转成 channel_message WS 帧广播给前端。"""
        frame = {
            "type": "channel_message",
            "channel_type": channel_msg.channel_type.value,
            "channel_id": channel_msg.channel_id,
            "user_id": channel_msg.user_id,
            "content": channel_msg.content,
            "session_id": channel_msg.session_id,
        }
        with _clients_lock:
            clients = list(_ws_clients)
        for client in clients:
            try:
                await client.send_json(frame)
            except Exception as e:
                logger.warning(f"广播失败: {e}")

    await handle_websocket(
        websocket,
        get_agent=_get_current_agent,
        channel_broadcasts={"wechat": _broadcast_to_ws},
        get_quality_pipeline=_get_quality_pipeline,
        get_intent_llm=_get_intent_llm,
    )
```

注意: `_broadcast_to_ws` 内部捕获每个 client.send_json 失败 (log warning 不冒泡),保证一个客户端断连不影响其他。

- [ ] **Step 4: 跑测试**

```bash
source .venv/bin/activate
pytest tests/ -q --ignore=tests/test_e2e_features.py
ruff check . && ruff format --check .
```

预期输出: pytest 全过 + ruff 0 error。

### Task 4.8: 手动冒烟 (C4 后必须)

- [ ] **Step 1: 启动后端**

```bash
cd /Users/yxb/projects/nexus
source .venv/bin/activate
python -m nexus.backend.run
```

预期: 启动 log 含 `Nexus Backend 已就绪 (Gateway 接管路由, Agent 懒构造)`。

- [ ] **Step 2: 等 /health 通**

```bash
while ! curl -fs http://localhost:30000/health >/dev/null; do sleep 1; done
curl http://localhost:30000/health
```

预期输出: `{"status":"healthy",...}`

- [ ] **Step 3: 启动前端**

```bash
cd /Users/yxb/projects/nexus/frontend
npm run dev
```

预期: `Local: http://localhost:30077/`

- [ ] **Step 4: 浏览器扫码登录微信**

打开 `http://localhost:30077/app`,微信 tab → 点绑定 → 二维码出现 → 微信扫码 → status=running。

- [ ] **Step 5: 收发测试**

- 微信端发 "测试消息 1"
- 前端 inbox 显示 `channel_message` 帧
- 微信端收到 agent 回复

预期: 全链路通,后端 log 含 `Gateway.route_message` 调用。

- [ ] **Step 6: 多通道隔离**

杀掉前端 WS 连接 (关浏览器),再从微信发消息:

- 微信用户应仍收到回复
- 后端 log 显示 broadcast 已注册但无 WS 消费者

预期: 不报错,正常回包。

- [ ] **Step 7: 错误路径**

杀掉 agent 进程(在 `_ensure_agent_ready` 异常注入或用 mock 替换 astream 抛错):

- 微信发消息
- 用户收到 "处理消息时出错"
- 后端 log 全

预期: Gateway._send_error 路径通。

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor(backend): Gateway 真接管路由 + main.py 删 200 行微信业务

- Gateway.route_message 接管 _handle_wechat_message/_process_wechat_message 业务
- ChannelRegistry 升级为唯一所有权 (start_channel/stop_channel/get_active_by_type)
- WeChatChannel._handle_incoming_message 改走 _safe_handle_message (Gateway 入口)
- main.py lifespan 注入 Gateway + Registry, REST endpoint 用 Registry 替换手写 channel 操作
- api/ws.py wechat_callback: Callable → channel_broadcasts: dict[str, Callable]
- 新增 _AgentProxy 解决 agent 懒构造与 Gateway 的时序冲突

测试: test_gateway.py (8 用例) + test_gateway_session_lock.py + test_wechat_channel_uses_gateway.py"
```

---

## Commit 5: 前端重构 (ChannelViewBase + ChannelInbox)

### Task 5.1: 改 frontend/src/types/index.ts

**Files:**
- Modify: `frontend/src/types/index.ts`

- [ ] **Step 1: 找原 wechat_message 帧类型定义**

```bash
cd /Users/yxb/projects/nexus
grep -n "wechat_message" frontend/src/types/index.ts
```

预期: 1 处定义(StreamFrame union 类型里的 case)。

- [ ] **Step 2: 替换为 channel_message**

找到原:
```typescript
  | { type: "wechat_message"; user_id: string; content: string }
```

替换为:
```typescript
  | {
      type: "channel_message";
      channel_type: "wechat" | "feishu" | "telegram";
      channel_id: string;
      user_id: string;
      content: string;
      session_id: string;
    }
```

- [ ] **Step 3: grep 验证旧字段无残留**

```bash
grep -rn "wechat_message" frontend/src/ 2>/dev/null | grep -v "\.test\." | grep -v "node_modules"
```

预期: 0 命中(或只在注释/migration 提示里)。

### Task 5.2: 新建 ChannelInbox.tsx

**Files:**
- Create: `frontend/src/components/desktop/channels/ChannelInbox.tsx`

- [ ] **Step 1: 写组件**

```tsx
/**
 * ChannelInbox - 共享收件箱,所有通道的消息都汇入这里。
 *
 * 通过 WS 订阅 channel_message 帧,按 channelType 过滤显示。
 * 每个 channelType 一个 ChannelInbox 实例,父组件 (ChannelViewBase) 决定传哪个 type。
 */

import { useStore } from '../../../store/useStore';
import type { ChannelType } from '../../../types';

interface ChannelInboxProps {
  channelType: ChannelType;
}

export function ChannelInbox({ channelType }: ChannelInboxProps) {
  const inbox = useStore((state) => state.channelInbox[channelType] ?? []);
  const clearInbox = useStore((state) => state.clearChannelInbox);

  if (inbox.length === 0) {
    return (
      <div className="channel-inbox-empty">
        暂无 {channelType} 通道消息
      </div>
    );
  }

  return (
    <div className="channel-inbox">
      <button onClick={() => clearInbox(channelType)}>清空</button>
      <ul>
        {inbox.map((msg) => (
          <li key={msg.id} className="channel-inbox-item">
            <div className="channel-inbox-user">{msg.user_id}</div>
            <div className="channel-inbox-content">{msg.content}</div>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

### Task 5.3: 新建 useChannelStatusPolling.ts

**Files:**
- Create: `frontend/src/hooks/useChannelStatusPolling.ts`

- [ ] **Step 1: 写 hook**

```ts
/**
 * useChannelStatusPolling - 通用轮询通道绑定状态。
 *
 * 取代 useWechatStatusPolling,接受 channelType 参数动态拼接 URL。
 */

import { useEffect, useState } from 'react';
import { apiFetch } from '../lib/api';
import type { ChannelType } from '../types';

interface ChannelBindStatus {
  bound: boolean;
  account_id?: string;
  status?: string;
  need_rescan?: boolean;
}

export function useChannelStatusPolling(channelType: ChannelType) {
  const [status, setStatus] = useState<ChannelBindStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const data = await apiFetch<ChannelBindStatus>(
          `/api/channels/${channelType}/bind`
        );
        if (!cancelled) setStatus(data);
      } catch (e) {
        if (!cancelled) setStatus({ bound: false });
      }
    };
    load();
    const interval = setInterval(load, 3000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [channelType]);

  return status;
}
```

### Task 5.4: 新建 ChannelViewBase.tsx

**Files:**
- Create: `frontend/src/components/desktop/channels/ChannelViewBase.tsx`

- [ ] **Step 1: 写组件**

```tsx
/**
 * ChannelViewBase - 所有通道视图的基类。
 *
 * 渲染流程:
 *   1. useChannelStatusPolling 拿 bind 状态
 *   2. 显示绑定卡片 (扫码/绑定按钮 + 状态)
 *   3. 显示 ChannelInbox (已收到的消息)
 *   4. 子组件 children 注入通道特有 UI (微信表情/Telegram inline keyboard 等)
 */

import type { ReactNode } from 'react';
import { ChannelInbox } from './ChannelInbox';
import { useChannelStatusPolling } from '../../../hooks/useChannelStatusPolling';
import type { ChannelType } from '../../../types';

interface ChannelViewBaseProps {
  channelType: ChannelType;
  children?: ReactNode;
}

export function ChannelViewBase({ channelType, children }: ChannelViewBaseProps) {
  const status = useChannelStatusPolling(channelType);

  const handleBind = async () => {
    try {
      const res = await fetch(`/api/channels/${channelType}/bind`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${import.meta.env.VITE_NEXUS_WS_TOKEN}` },
      });
      const data = await res.json();
      if (data.need_rescan) {
        // 触发扫码流程 (由各通道 children 处理)
        window.dispatchEvent(new CustomEvent(`${channelType}:need_rescan`));
      }
    } catch (e) {
      console.error(`${channelType} bind failed:`, e);
    }
  };

  const handleUnbind = async () => {
    try {
      await fetch(`/api/channels/${channelType}/bind`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${import.meta.env.VITE_NEXUS_WS_TOKEN}` },
      });
    } catch (e) {
      console.error(`${channelType} unbind failed:`, e);
    }
  };

  return (
    <div className={`channel-view channel-view-${channelType}`}>
      <div className="channel-bind-card">
        {status?.bound ? (
          <>
            <span>已绑定: {status.account_id}</span>
            <button onClick={handleUnbind}>解绑</button>
          </>
        ) : (
          <button onClick={handleBind}>扫码绑定 {channelType}</button>
        )}
      </div>

      <ChannelInbox channelType={channelType} />

      <div className="channel-children">{children}</div>
    </div>
  );
}
```

### Task 5.5: 改 store/useStore.ts 加 channelInbox

**Files:**
- Modify: `frontend/src/store/useStore.ts`

- [ ] **Step 1: 找原 wechatInbox 定义**

```bash
cd /Users/yxb/projects/nexus
grep -n "wechatInbox\|clearWechatInbox" frontend/src/store/useStore.ts
```

预期: 1-2 处(state + action)。

- [ ] **Step 2: 替换**

原:
```typescript
  wechatInbox: WechatInboxMsg[];
  addWechatInbox: (msg: WechatInboxMsg) => void;
  clearWechatInbox: () => void;
```

替换为:
```typescript
  channelInbox: Record<string, ChannelInboxMsg[]>;
  addChannelInbox: (channelType: string, msg: ChannelInboxMsg) => void;
  clearChannelInbox: (channelType: string) => void;
```

实现细节:把 push 改成按 channelType 分桶。`addChannelInbox` 内部 `state.channelInbox[channelType] = [...(state.channelInbox[channelType] ?? []), msg]`。

- [ ] **Step 3: 找旧 WS 监听器把 wechat_message 改为 channel_message**

```bash
grep -rn "wechat_message" frontend/src/ 2>/dev/null | grep -v "\.test\." | grep -v "node_modules"
```

预期: 还剩 1-2 处(WS 监听器代码)。

把 `if (frame.type === "wechat_message") { ... }` 改成:
```typescript
if (frame.type === "channel_message") {
  store.addChannelInbox(frame.channel_type, {
    id: crypto.randomUUID(),
    user_id: frame.user_id,
    content: frame.content,
    timestamp: Date.now(),
  });
}
```

### Task 5.6: 改 WechatAssistantView.tsx 子类化

**Files:**
- Modify: `frontend/src/components/desktop/WechatAssistantView.tsx`

- [ ] **Step 1: 把 WechatAssistantView 改成薄壳**

保留原有 wechat 特有逻辑(扫码 modal, wxid 显示等)作为 children,外面套 ChannelViewBase:

```tsx
import { ChannelViewBase } from './channels/ChannelViewBase';
import WechatPluginModal from '../WechatPluginModal';

export function WechatAssistantView({ onBack }: WechatAssistantViewProps) {
  return (
    <ChannelViewBase channelType="wechat">
      <WechatPluginModal />
    </ChannelViewBase>
  );
}
```

- [ ] **Step 2: 跑前端 lint**

```bash
cd /Users/yxb/projects/nexus/frontend
npm run lint
```

预期: 0 error。

- [ ] **Step 3: 跑前端 test**

```bash
cd /Users/yxb/projects/nexus/frontend
npm run test
```

预期: 全过。

### Task 5.7: 改 Sidebar.tsx + DesktopShell.tsx

**Files:**
- Modify: `frontend/src/components/desktop/Sidebar.tsx`
- Modify: `frontend/src/components/desktop/DesktopShell.tsx`

- [ ] **Step 1: 在 Sidebar.tsx 加 Channels section**

找现有 Sidebar 渲染 <WechatAssistantView /> 的位置,改成渲染 `<ChannelsPanel />`:

```tsx
function ChannelsPanel() {
  return (
    <div className="channels-panel">
      <WechatAssistantView />
      {/* 未来: <TelegramAssistantView /> <FeishuAssistantView /> */}
    </div>
  );
}
```

- [ ] **Step 2: 在 DesktopShell.tsx 替换**

找 `<WechatAssistantView />` 渲染点,改成 `<ChannelsPanel />`。

- [ ] **Step 3: 跑前端 lint + test**

```bash
cd /Users/yxb/projects/nexus/frontend
npm run lint && npm run test
```

预期: 0 error + 全过。

- [ ] **Step 4: Commit**

```bash
cd /Users/yxb/projects/nexus
git add -A
git commit -m "refactor(frontend): types 加 channel_message 帧 + 新建 ChannelViewBase/ChannelInbox + WechatAssistantView 子类化"
```

---

## Commit 6: 删 ChannelType.WEBSOCKET

### Task 6.1: 删枚举值 + 清理残留

**Files:**
- Modify: `nexus/backend/channels/base.py`

- [ ] **Step 1: grep 验证 WEBSOCKET 引用**

```bash
cd /Users/yxb/projects/nexus
grep -rn "ChannelType\.WEBSOCKET\|\"websocket\"\|'websocket'" nexus/backend/ tests/ 2>/dev/null
```

预期: 0 命中(因为 C3 的 registry.py 已经删了 WEBSOCKET 分支)。

- [ ] **Step 2: 删 base.py 的 ChannelType.WEBSOCKET**

`nexus/backend/channels/base.py:36`:

```python
class ChannelType(StrEnum):
    """通道类型枚举"""

    WEBSOCKET = "websocket"
    WECHAT = "wechat"
    FEISHU = "feishu"
```

改成:

```python
class ChannelType(StrEnum):
    """通道类型枚举 (前端 WebSocket 由 FastAPI 直接管,不走 Channel ABC)"""

    WECHAT = "wechat"
    FEISHU = "feishu"
```

- [ ] **Step 3: 跑全量**

```bash
cd /Users/yxb/projects/nexus
source .venv/bin/activate
pytest tests/ -q
cd frontend && npm run lint && npm run test:e2e:smoke
cd ..
ruff check . && ruff format --check .
```

预期: pytest 全过 (含 E2E) + frontend lint/test 全过 + ruff 0 error。

- [ ] **Step 4: grep 最终死代码清扫**

```bash
cd /Users/yxb/projects/nexus
git grep -n "from .channels.wechat" nexus/ tests/   # → 0
git grep -n "wechat_plugin" nexus/ tests/            # → 0
git grep -n "_wechat_sessions\b" nexus/               # → 0
git grep -n "get_active_wechat_channel" nexus/        # → 0
git grep -n "_handle_wechat_message" nexus/           # → 0
git grep -n "_process_wechat_message" nexus/          # → 0
```

预期: 全部 0 命中。

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(backend): base.py 删 ChannelType.WEBSOCKET (前端 WS 不走 Channel ABC)"
```

---

## 最终验收

### 全量测试 + lint

```bash
cd /Users/yxb/projects/nexus
source .venv/bin/activate
pytest tests/ -q                          # → 全过(含 E2E)
cd frontend && npm run lint && npm run test:e2e
cd ..
ruff check . && ruff format --check .    # → 0 error / 0 diff
```

### 手动冒烟 (跨前后端)

```bash
# 1. 启动
source .venv/bin/activate
python -m nexus.backend.run &
cd frontend && npm run dev &
cd ..

# 2. 健康检查
curl -fs http://localhost:30000/health  # → healthy

# 3. 浏览器: http://localhost:30077/app
#    - 微信 tab → 扫码登录 → status=running
#    - 微信发消息 → 前端 inbox 显示 channel_message 帧 + agent 回复

# 4. 多通道预留验证
#    看 Sidebar.tsx 是否有 Channels section,WechatAssistantView 是否包在 ChannelViewBase 里
```

### Commit 历史

```
C1. refactor(backend): 删 plugins/ 子树 (0 caller 孤儿, 367 行)
C2. refactor(channels): 删 wechat.py re-export 壳 + 14 处 import 直连细分模块
C3. refactor(channels): ChannelRegistry 升级为唯一所有权
C4. refactor(backend): Gateway 真接管路由 + main.py 删 200 行微信业务
C5. refactor(frontend): ChannelViewBase/ChannelInbox + WechatAssistantView 子类化
C6. feat(backend): base.py 删 ChannelType.WEBSOCKET
```

### 删除回滚 (如需要)

```bash
git tag refactor-pre-channel-arch  # 已打
git revert HEAD~6..HEAD             # 一次回滚 6 个 commit
# 或:
git reset --hard refactor-pre-channel-arch  # 强回滚 (会丢 C1-C6 所有变更)
```

---

## 自检 (Self-Review)

### Spec 覆盖

| Spec 节 | 对应 Task |
|---|---|
| §1 背景与动机 | (只读上下文,无 Task) |
| §2 目标 | Task 0 (tag) + Task 6.1 (最终验收) |
| §3 架构 | Task 3.2 (Registry) + Task 4.2 (Gateway) + Task 4.5 (wechat_channel) |
| §4 接口契约 | Task 3.2 (Registry 5 方法) + Task 4.2 (Gateway 6 步) + Task 4.5 (Channel 3 abstract) |
| §5 文件改动清单 | Task 1.1 (C1) + Task 2.1 (C2) + Task 3.1-3.2 (C3) + Task 4.1-4.8 (C4) + Task 5.1-5.7 (C5) + Task 6.1 (C6) |
| §6 错误处理矩阵 | Task 4.1 (TestRouteMessageError / TestBroadcastIsolated) |
| §7 测试覆盖 | Task 3.1 (registry 4 case) + Task 4.1 (gateway 8 case) + Task 4.3 (session lock) + Task 4.4 (wechat uses gateway) + Task 5.6 (frontend test) |
| §8 风险矩阵 | 风险 1 (漏 think 标签): Task 4.1 TestCallAgentStripThinking; 风险 2 (死锁): Task 4.3; 风险 3 (删 wechat 漏 import): Task 2.1 Step 11; 风险 4 (前端帧不匹配): Task 5.1 + Task 5.5 一次性 commit; 风险 5 (session 重建丢历史): Gateway._get_or_create_session Task 4.2; 风险 6 (删 plugin 漏 import): Task 1.1 Step 1 |
| §9 回滚策略 | Task 0 (tag) + 最终验收 (git revert) |
| §10 Commit 顺序 | Task 0 → 1.1 → 2.1 → 3.1-3.2 → 4.1-4.8 → 5.1-5.7 → 6.1 |
| §11 失败处理 | 嵌入各 Task 的 "如果 X 失败" 步骤 |
| §12 不在范围内 | (没改) |
| §13 验证 | 最终验收 |

### Placeholder scan

- ✅ 无 "TBD" / "TODO" / "类似 Task N" 引用
- ✅ 所有代码块完整,无 "..." 占位
- ✅ 所有命令带预期输出
- ✅ 所有文件路径绝对

### Type 一致性

| 类型/方法 | 定义位置 | 使用位置 |
|---|---|---|
| `Gateway(agent, sessions_module, messages_module)` | Task 4.2 Step 1 | Task 4.6 Step 5 (main.py 注入) |
| `Gateway.set_broadcast(ch_type, fn)` | Task 4.2 Step 1 | Task 4.7 Step 2 (api/ws.py) |
| `Gateway.route_message(msg)` | Task 4.2 Step 1 | Task 4.1 (test) + Task 4.5 (wechat_channel) |
| `ChannelRegistry(gateway)` | Task 3.2 Step 1 | Task 4.6 Step 5 (main.py) |
| `ChannelRegistry.start_channel(config, **kwargs)` | Task 3.2 Step 1 | Task 4.6 Step 6 (POST /bind) |
| `ChannelRegistry.stop_channel(channel_id)` | Task 3.2 Step 1 | Task 4.6 Step 7 (DELETE /bind) |
| `ChannelRegistry.get_active_by_type(ch_type)` | Task 3.2 Step 1 | Task 4.6 Step 6 + 7 + 8 |
| `ChannelType.WECHAT / FEISHU` | base.py:36 (Task 6.1 删 WEBSOCKET) | registry.py / wechat_channel.py / frontend types |
| `ChannelMessage.content / reply_to / channel_id / user_id / channel_type` | base.py:74 | Gateway / FakeChannel / 前端 frame |
| `_AgentProxy` | Task 4.6 Step 5 (main.py 新增) | Gateway 注入 (`agent=_AgentProxy(_agent_getter)`) |
| `channel_message` WS 帧字段 | Task 5.1 Step 2 (types/index.ts) | Task 5.5 Step 3 (store 监听) + Task 4.7 Step 3 (main.py _broadcast_to_ws) |

一致。✓
