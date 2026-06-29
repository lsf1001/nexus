"""C002 修复回归测试 — wechat token Fernet 加密 + 旧 base64 自动迁移。

覆盖:
  1. 新账号保存/读取 round-trip (tokenVersion=2)
  2. 磁盘上 token 是 Fernet 密文,不是 base64 明文
  3. 旧 base64 (tokenVersion 缺省或=1) 自动迁移并升级
  4. 损坏 / 篡改的 Fernet token 返回 None
  5. 加密 key 文件首次生成且权限 0o600
  6. 环境变量 NEXUS_TOKEN_ENCRYPTION_KEY 优先于文件
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from nexus.backend.channels import wechat_account
from nexus.backend.channels.wechat_types import WeixinAccount


@pytest.fixture
def isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """隔离 ~.nexus/weixin 到 tmp_path,并把 secret 文件也放过去。

    返回 state_dir 让测试可以直接验证文件存在。
    """
    state_dir = tmp_path / "weixin"
    state_dir.mkdir()
    secret_file = tmp_path / ".secret"

    # _get_state_dir() 固定走 Path.home() / .nexus / weixin;
    # monkeypatch 后让所有路径都基于 tmp_path。
    monkeypatch.setattr(wechat_account, "_SECRET_FILE", secret_file)

    def fake_state_dir() -> Path:
        state_dir.mkdir(parents=True, exist_ok=True)
        return state_dir

    monkeypatch.setattr(wechat_account, "_get_state_dir", fake_state_dir)

    # 默认清掉环境变量,避免污染
    monkeypatch.delenv("NEXUS_TOKEN_ENCRYPTION_KEY", raising=False)

    return state_dir


def _make_account(token: str = "bot_token_abc_123_xyz") -> WeixinAccount:
    return WeixinAccount(
        account_id="test-bot@im.bot",
        user_id="user_42",
        token=token,
        base_url="https://example.com",
    )


def test_save_and_load_roundtrip_uses_fernet(isolated_state: Path) -> None:
    """新账号保存后,磁盘上是 Fernet 密文(tokenVersion=2);加载回明文正确。"""
    account = _make_account(token="my_secret_bot_token")
    wechat_account._save_account(account)

    file_path = wechat_account._resolve_account_file_path("test-bot@im.bot")
    assert file_path.exists()

    raw = json.loads(file_path.read_text(encoding="utf-8"))
    assert raw["tokenVersion"] == 2
    # 磁盘上不应出现明文 token (任何位置的子串)
    assert "my_secret_bot_token" not in file_path.read_text(encoding="utf-8")
    # 密文应是合法 base64 (Fernet 密文 base64 编码后 ≥ 100 字节)
    ciphertext = raw["token"]
    assert len(ciphertext) > 80, f"Fernet ciphertext too short: {len(ciphertext)}"
    import base64

    base64.urlsafe_b64decode(ciphertext)  # 不抛即合法

    loaded = wechat_account._load_account("test-bot@im.bot")
    assert loaded is not None
    assert loaded.token == "my_secret_bot_token"
    assert loaded.user_id == "user_42"
    assert loaded.base_url == "https://example.com"


def test_old_base64_format_auto_migrates(isolated_state: Path) -> None:
    """旧 base64 格式 (无 tokenVersion 或 tokenVersion=1) 首次加载自动迁移。

    迁移后:
      - 内存返回的 token 仍是明文(原值)
      - 磁盘文件被重写为 tokenVersion=2 (Fernet)
    """
    account_id = "old-bot@im.bot"
    account_file = wechat_account._resolve_account_file_path(account_id)
    account_file.parent.mkdir(parents=True, exist_ok=True)
    old_plain = "legacy_bot_token_xyz_999"
    old_cipher = base64.b64encode(old_plain.encode()).decode()
    account_file.write_text(
        json.dumps(
            {
                "token": old_cipher,
                # 没有 tokenVersion 字段 → 走默认 1 (旧格式)
                "savedAt": "2026-01-01T00:00:00Z",
                "baseUrl": "https://legacy.example.com",
                "userId": "user_legacy",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    loaded = wechat_account._load_account(account_id)
    assert loaded is not None
    # 明文 token 仍是迁移前的值
    assert loaded.token == old_plain
    assert loaded.user_id == "user_legacy"

    # 磁盘已被重写为 Fernet 格式
    raw = json.loads(account_file.read_text(encoding="utf-8"))
    assert raw["tokenVersion"] == 2
    assert old_plain not in account_file.read_text(encoding="utf-8")


def test_corrupted_fernet_token_returns_none(isolated_state: Path) -> None:
    """Fernet 密文被篡改 → 解密抛 InvalidToken → 返回 None。"""
    account_id = "bad-bot@im.bot"
    account_file = wechat_account._resolve_account_file_path(account_id)
    account_file.parent.mkdir(parents=True, exist_ok=True)
    account_file.write_text(
        json.dumps(
            {
                "token": "AAAA-this-is-not-a-valid-fernet-token",
                "tokenVersion": 2,
                "savedAt": "2026-01-01T00:00:00Z",
                "baseUrl": "https://example.com",
                "userId": "user_x",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    loaded = wechat_account._load_account(account_id)
    assert loaded is None


def test_secret_file_generated_with_0600_on_first_use(isolated_state: Path) -> None:
    """首次 _resolve_encryption_key 自动生成 ~/.nexus/.secret 且 chmod 0o600。"""
    secret_file = wechat_account._SECRET_FILE
    assert not secret_file.exists()

    key = wechat_account._resolve_encryption_key()
    assert secret_file.exists()

    # 0o600: owner rw, group/other 无权限 (Unix-only 检查)
    if hasattr(os, "geteuid"):  # 跳过 Windows
        mode = secret_file.stat().st_mode & 0o777
        assert mode == 0o600, f"expected 0o600, got {oct(mode)}"

    # 生成的 key 是合法 Fernet key
    Fernet(key)


def test_env_var_takes_precedence_over_secret_file(isolated_state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """NEXUS_TOKEN_ENCRYPTION_KEY 环境变量优先于 ~/.nexus/.secret。"""
    # 预先在 secret 文件里放一个 key
    secret_key = Fernet.generate_key()
    wechat_account._SECRET_FILE.write_text(secret_key.decode(), encoding="utf-8")

    # 环境变量放另一个 key
    env_key = Fernet.generate_key()
    monkeypatch.setenv("NEXUS_TOKEN_ENCRYPTION_KEY", env_key.decode())

    resolved = wechat_account._resolve_encryption_key()
    # env_key 是 bytes (Fernet.generate_key 直接返回 bytes)
    assert resolved == env_key


def test_env_var_invalid_format_raises(isolated_state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """NEXUS_TOKEN_ENCRYPTION_KEY 格式非法 → RuntimeError,不静默回退到文件。"""
    monkeypatch.setenv("NEXUS_TOKEN_ENCRYPTION_KEY", "not-a-fernet-key!!!")

    with pytest.raises(RuntimeError, match="NEXUS_TOKEN_ENCRYPTION_KEY"):
        wechat_account._resolve_encryption_key()


def test_saved_file_chmod_0o600(isolated_state: Path) -> None:
    """_save_account 后账号文件也是 0o600 (旧实现已是,保留回归保护)。"""
    if not hasattr(os, "geteuid"):
        pytest.skip("Windows 无 chmod 语义")

    wechat_account._save_account(_make_account())
    file_path = wechat_account._resolve_account_file_path("test-bot@im.bot")
    mode = file_path.stat().st_mode & 0o777
    assert mode == 0o600
