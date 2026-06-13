"""微信通道账号管理：路径解析、归一化、增删改查、token 校验。

从 wechat.py 拆分（2026-06-13 P0 重构）。
"""
from __future__ import annotations

import base64
import json
import logging
import os
import time
from pathlib import Path

import httpx

from .wechat_protocol import _build_base_info, _build_headers
from .wechat_types import FIXED_BASE_URL, WeixinAccount

logger = logging.getLogger(__name__)


# ---------- 路径解析 ----------


def _get_state_dir() -> Path:
    """获取状态存储目录。"""
    state_dir = Path.home() / ".nexus" / "weixin"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


def _resolve_account_index_path() -> Path:
    return _get_state_dir() / "accounts.json"


def _resolve_account_file_path(account_id: str) -> Path:
    return _get_state_dir() / "accounts" / f"{account_id}.json"


def _resolve_context_token_file_path(account_id: str) -> Path:
    return _get_state_dir() / "accounts" / f"{account_id}.context-tokens.json"


# ---------- ID 归一化 ----------


def _normalize_account_id(raw_id: str) -> str:
    """将原始 account ID 转换为文件系统安全的格式。"""
    return raw_id.replace("@im.bot", "-im-bot").replace("@im.wechat", "-im-wechat")


# ---------- 索引 ----------


def _list_indexed_weixin_account_ids() -> list[str]:
    """返回所有注册的账号 ID。"""
    try:
        path = _resolve_account_index_path()
        if not path.exists():
            return []
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, str) and x.strip()]
    except (OSError, json.JSONDecodeError):
        pass
    return []


def _register_weixin_account_id(account_id: str) -> None:
    """注册账号 ID 到索引。"""
    existing = _list_indexed_weixin_account_ids()
    if account_id in existing:
        return
    updated = existing + [account_id]
    path = _resolve_account_index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(updated, f, ensure_ascii=False, indent=2)


# ---------- 账号增删改查 ----------


def _save_account(account: WeixinAccount) -> None:
    """保存账号到磁盘（token 仅做简单编码，非真正加密）。"""
    account_dir = _get_state_dir() / "accounts"
    account_dir.mkdir(parents=True, exist_ok=True)
    file_path = _resolve_account_file_path(account.account_id)

    encoded_token = base64.b64encode(account.token.encode()).decode()

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "token": encoded_token,
                "savedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "baseUrl": account.base_url,
                "userId": account.user_id,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    os.chmod(file_path, 0o600)


def _load_account(account_id: str) -> WeixinAccount | None:
    """从磁盘加载账号。"""
    file_path = _resolve_account_file_path(account_id)
    if not file_path.exists():
        return None
    try:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    encoded_token = data.get("token", "")
    try:
        token = base64.b64decode(encoded_token).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        token = ""

    return WeixinAccount(
        account_id=account_id,
        user_id=data.get("userId", ""),
        token=token,
        base_url=data.get("baseUrl", ""),
    )


def _delete_account(account_id: str) -> None:
    """删除账号数据。"""
    account_file = _resolve_account_file_path(account_id)
    if account_file.exists():
        account_file.unlink()
    # 更新索引
    existing = _list_indexed_weixin_account_ids()
    if account_id in existing:
        existing.remove(account_id)
        path = _resolve_account_index_path()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
    logger.info(f"Deleted account: {account_id}")


def _check_token_valid(account_id: str) -> bool:
    """检查 token 是否有效（通过 notifyStart 检测）。"""
    try:
        account = _load_account(account_id)
        if not account:
            return False
        body = {"base_info": _build_base_info()}
        resp = httpx.post(
            f"{account.base_url or FIXED_BASE_URL}/ilink/bot/msg/notifystart",
            json=body,
            headers=_build_headers(account.token),
            timeout=10.0,
        )
        data = resp.json()
        errcode = data.get("errcode", 0)
        return errcode == 0
    except httpx.RequestError:
        return False
