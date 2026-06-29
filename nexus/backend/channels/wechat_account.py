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
from cryptography.fernet import Fernet, InvalidToken

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


# ---------- 加密 key 管理 ----------
#
# 旧实现 (2026-06 之前): token 仅 base64 编码,等效明文,任何人 cat | base64 -d
# 即可拿 bot_token。 现改用 Fernet (AES-128-CBC + HMAC-SHA256), key 存
# ~/.nexus/.secret (0o600) 或环境变量 NEXUS_TOKEN_ENCRYPTION_KEY。
#
# 旧 base64 文件通过 tokenVersion=1 标记,首次 _load_account 时自动迁移到
# tokenVersion=2 (Fernet), 写入新格式, 加载侧无感。

_SECRET_FILE = Path.home() / ".nexus" / ".secret"
_ENV_KEY_NAME = "NEXUS_TOKEN_ENCRYPTION_KEY"


def _resolve_encryption_key() -> bytes:
    """解析 token 加密 key (Fernet 格式, 44 字节 url-safe base64)。

    优先级:
      1. 环境变量 NEXUS_TOKEN_ENCRYPTION_KEY (生产 / DMG 注入)
      2. ~/.nexus/.secret 文件 (用户本地首次启动自动生成, 0o600)

    Raises:
        RuntimeError: 环境变量格式无效或两种来源都不可用。
    """
    env_key = os.environ.get(_ENV_KEY_NAME, "").strip()
    if env_key:
        try:
            Fernet(env_key.encode())  # 校验格式
            return env_key.encode()
        except (ValueError, TypeError) as exc:
            raise RuntimeError(
                f"{_ENV_KEY_NAME} 环境变量格式无效,必须是 Fernet key (44 字节 url-safe base64 字符串)"
            ) from exc

    if _SECRET_FILE.exists():
        try:
            content = _SECRET_FILE.read_text(encoding="utf-8").strip()
            if content:
                Fernet(content.encode())  # 校验格式
                return content.encode()
        except (OSError, ValueError) as exc:
            logger.error("读取 secret 文件失败, 将重新生成: %s", exc)

    # 首次启动: 自动生成并写入 secret 文件
    new_key = Fernet.generate_key()
    try:
        _SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SECRET_FILE.write_text(new_key.decode(), encoding="utf-8")
        os.chmod(_SECRET_FILE, 0o600)
        logger.warning(
            "已为 wechat token 生成新加密 key 到 %s (0o600); 旧账号 (base64) token 会在首次加载时自动迁移到 Fernet",
            _SECRET_FILE,
        )
    except OSError as exc:
        raise RuntimeError(
            f"无法写入 secret 文件 {_SECRET_FILE}: {exc}; 请通过环境变量 {_ENV_KEY_NAME} 注入 Fernet key"
        ) from exc
    return new_key


def _encrypt_token(plaintext: str) -> str:
    """Fernet 加密 token,返回 url-safe base64 字符串(密文)。"""
    return Fernet(_resolve_encryption_key()).encrypt(plaintext.encode()).decode()


def _decrypt_token(ciphertext: str) -> str:
    """Fernet 解密,失败抛 InvalidToken。"""
    return Fernet(_resolve_encryption_key()).decrypt(ciphertext.encode()).decode()


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
    """保存账号到磁盘 (token 用 Fernet 真加密, 不再是 base64)。"""
    account_dir = _get_state_dir() / "accounts"
    account_dir.mkdir(parents=True, exist_ok=True)
    file_path = _resolve_account_file_path(account.account_id)

    encrypted_token = _encrypt_token(account.token)

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "token": encrypted_token,
                "tokenVersion": 2,  # 2 = Fernet 加密, 1 = 旧 base64
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
    """从磁盘加载账号 (token 自动解密; 旧 base64 格式自动迁移到 Fernet)。"""
    file_path = _resolve_account_file_path(account_id)
    if not file_path.exists():
        return None
    try:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    encoded_token = data.get("token", "")
    token_version = data.get("tokenVersion", 1)  # 缺字段默认旧格式
    plain_token = ""

    if token_version == 2:
        # 当前 Fernet 格式: 直接解密
        try:
            plain_token = _decrypt_token(encoded_token)
        except InvalidToken:
            logger.error(
                "账号 %s 的 token 解密失败 (Fernet key 可能已变更, 需重新扫码)",
                account_id,
            )
            return None
    else:
        # 旧 base64 格式: 解码 + 自动迁移到 Fernet
        try:
            plain_token = base64.b64decode(encoded_token).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            logger.error("账号 %s 的旧 base64 token 解码失败", account_id)
            return None

        # 迁移: 用 Fernet 重写 (升级 tokenVersion 到 2)
        logger.info(
            "账号 %s 检测到旧 base64 token 格式, 自动迁移到 Fernet 加密",
            account_id,
        )
        migrated = WeixinAccount(
            account_id=account_id,
            user_id=data.get("userId", ""),
            token=plain_token,
            base_url=data.get("baseUrl", ""),
        )
        try:
            _save_account(migrated)
        except Exception as exc:  # noqa: BLE001 - 迁移失败下次重试
            logger.warning(
                "账号 %s 自动迁移失败: %s (本次能正常用, 下次加载会再试)",
                account_id,
                exc,
            )

    return WeixinAccount(
        account_id=account_id,
        user_id=data.get("userId", ""),
        token=plain_token,
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
    """检查 token 是否有效(通过 notifyStart 检测)。

    调用 iLink ``/ilink/bot/msg/notifystart`` 端点:
    - errcode == 0 → 有效
    - errcode != 0 → 服务端拒绝(过期 / 撤销)
    - 网络 / JSON 解析错误 → 视为无效,降级到 ``_delete_account`` 清理

    Returns:
        True 表示 token 仍可用,False 表示需重新扫码。
    """
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
    except (httpx.RequestError, json.JSONDecodeError):
        # 网络抖动 / 上游返回非 JSON → 视为无效,等下次启动重试
        return False
