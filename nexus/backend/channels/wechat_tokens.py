"""微信通道 context token 持久化与查询。

从 wechat.py 拆分（2026-06-13 P0 重构）。context token 用于维持与
微信服务器的多轮上下文，存于 _context_tokens 字典并按账号持久化。
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from .wechat_account import _resolve_context_token_file_path
from .wechat_state import _context_tokens

logger = logging.getLogger(__name__)


def _save_context_tokens(account_id: str) -> None:
    """保存 context tokens 到磁盘"""
    file_path = _resolve_context_token_file_path(account_id)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tokens = {}
    prefix = f"{account_id}:"
    for k, v in _context_tokens.items():
        if k.startswith(prefix):
            tokens[k[len(prefix) :]] = v
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(tokens, f, ensure_ascii=False)


def _restore_context_tokens(account_id: str) -> None:
    """从磁盘恢复 context tokens"""
    file_path = _resolve_context_token_file_path(account_id)
    if not file_path.exists():
        return
    try:
        with open(file_path, encoding="utf-8") as f:
            tokens = json.load(f)
        for user_id, token in tokens.items():
            _context_tokens[f"{account_id}:{user_id}"] = token
        logger.info(f"Restored {len(tokens)} context tokens for account={account_id}")
    except Exception as e:
        logger.warn(f"Failed to restore context tokens: {e}")


def _set_context_token(account_id: str, user_id: str, token: str) -> None:
    """设置 context token"""
    key = f"{account_id}:{user_id}"
    _context_tokens[key] = token


def _get_context_token(account_id: str, user_id: str) -> str | None:
    """获取 context token"""
    return _context_tokens.get(f"{account_id}:{user_id}")
