"""微信通道 - 兼容层 re-export 薄壳。

P0 重构（2026-06-13，7 步拆分）完成。原 ``wechat.py`` 936 行的所有职责已
拆到 ``wechat_types`` / ``wechat_state`` / ``wechat_protocol`` /
``wechat_account`` / ``wechat_tokens`` / ``wechat_api`` / ``wechat_login`` /
``wechat_channel`` 共 8 个模块。本文件保留纯 re-export 向后兼容旧导入路径，
不再承载业务实现；新代码应直接 import 对应的细分模块。

为什么保留兼容层：
  - main.py / registry.py / 旧测试 / 外部插件（如 plugins/wechat_plugin.py）
    都曾用 ``from .channels.wechat import ...`` 拉符号；一次性全切会引入大量
    改动与回归风险。保留本壳做桥梁，逐步迁移到新模块的 import 路径。
  - 重构后本文件 < 100 行，模块边界清晰；任何新增业务逻辑都不应再回这里。
"""

from __future__ import annotations

# 账号管理
from .wechat_account import (  # noqa: F401
    _check_token_valid,
    _delete_account,
    _get_state_dir,
    _list_indexed_weixin_account_ids,
    _load_account,
    _normalize_account_id,
    _register_weixin_account_id,
    _resolve_account_file_path,
    _resolve_account_index_path,
    _resolve_context_token_file_path,
    _save_account,
)

# HTTP API
from .wechat_api import (  # noqa: F401
    _api_get_fetch,
    _api_post_fetch,
    _get_config,
    _send_message,
    _send_typing,
)

# 通道实现 + 暂停控制
from .wechat_channel import (  # noqa: F401
    WeChatChannel,
    _get_remaining_pause_ms,
    _is_session_paused,
    _pause_session,
)

# QR 登录流程
from .wechat_login import (  # noqa: F401
    _fetch_qrcode,
    _get_local_bot_token_list,
    _is_login_fresh,
    _poll_qr_status,
    _purge_expired_logins,
    wait_qr_scan,
    wechat_qr_login,
)

# 协议层（ID / 头 / base_info）
from .wechat_protocol import (  # noqa: F401
    _build_base_info,
    _build_client_version,
    _build_headers,
    _generate_client_id,
    _random_wechat_uin,
)

# 全局状态（含活跃 channel 访问器）
from .wechat_state import (  # noqa: F401
    _accounts,
    _active_channel,
    _active_logins,
    _clear_active_channel,
    _context_tokens,
    _global_lock,
    _set_active_channel,
    get_active_wechat_channel,
)

# context token 管理
from .wechat_tokens import (  # noqa: F401
    _get_context_token,
    _restore_context_tokens,
    _save_context_tokens,
    _set_context_token,
)

# 数据类型
from .wechat_types import (  # noqa: F401
    FIXED_BASE_URL,
    MessageItemType,
    MessageState,
    MessageTypeEnum,
    QRSession,
    WeixinAccount,
)

# 模块级常量（与原文件保持一致，避免引用方硬编码）
DEFAULT_LONG_POLL_TIMEOUT_MS = 35_000
DEFAULT_API_TIMEOUT_MS = 15_000
DEFAULT_CONFIG_TIMEOUT_MS = 10_000
CHANNEL_VERSION = "2.4.4"
DEFAULT_ILINK_BOT_TYPE = "3"
QR_LONG_POLL_TIMEOUT_MS = 35_000
ACTIVE_LOGIN_TTL_MS = 5 * 60 * 1000
SESSION_EXPIRED_ERRCODE = -14
SESSION_PAUSE_DURATION_MS = 60 * 60 * 1000  # 1 小时
