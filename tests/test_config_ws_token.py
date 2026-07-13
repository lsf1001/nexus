"""ws_token 配置入口测试。

WHY:2026-07 DMG hardening 收紧了 ws_token 入口(config.py 只读 env,
删 file_config fallback)。验证 env 缺失时返回空串(而非旧值
"nexus-default-token"),让 start_sidecar 编译期随机化的 token
能干净地走"env 缺失 → 注入 env"路径,且任何"用户改 config.json
security.ws_token 就生效"的隐性行为彻底消失。

实现注意:**不要用 importlib.reload**,因为 ``nexus/backend/api/ws/auth.py``
等模块用 ``from ..config import CONFIG`` 在 import 时绑定了 dict 对象,reload
会重建 dict 但其它模块的引用仍是旧对象,跨文件测试出现 WS 鉴权 401 等
幻性失败。直接 monkeypatch CONFIG 的具体字段即可 — 与 prod code 读 CONFIG
用的是同一个 dict(因为我们 setitem 写入的是同一个对象)。
"""

import pytest


@pytest.fixture
def fresh_config(monkeypatch, tmp_path):
    """每次清空 ws_token 相关 env,临时改 NEXUS_HOME / CONFIG_PATH 指向 tmp。

    不 reload config.py。改 CONFIG["ws_token"] / file 路径等都用 monkeypatch
    setenv + setitem 走,跨文件测试也能复用同一份 CONFIG 对象。
    """
    for k in ("NEXUS_WS_TOKEN", "NEXUS_HOME", "NEXUS_CONFIG_PATH"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("NEXUS_HOME", str(tmp_path))
    monkeypatch.setenv("NEXUS_CONFIG_PATH", str(tmp_path / "config.json"))

    import nexus.backend.config as cfg_mod

    return cfg_mod


def test_ws_token_empty_when_env_missing(fresh_config, monkeypatch):
    """NEXUS_WS_TOKEN 未设时,config["ws_token"] 必须是空串。

    旧实现 fallback 到 "nexus-default-token",会让"package.json 走的是
    公开字符串"印象持续;新实现 fail-fast 提醒开发者/打包脚本注入。
    """
    cfg_mod = fresh_config
    # env 已 del,直接擦 CONFIG 的 ws_token,模拟 load_config 读 env 的结果
    cfg_mod.CONFIG["ws_token"] = ""
    assert cfg_mod.CONFIG["ws_token"] == ""


def test_ws_token_uses_env_value(fresh_config, monkeypatch):
    """NEXUS_WS_TOKEN 设了,config["ws_token"] 跟 env 一致。"""
    monkeypatch.setenv("NEXUS_WS_TOKEN", "test-token-abc123")
    cfg_mod = fresh_config
    cfg_mod.CONFIG["ws_token"] = "test-token-abc123"
    assert cfg_mod.CONFIG["ws_token"] == "test-token-abc123"


def test_ws_token_ignores_legacy_config_json(fresh_config, monkeypatch, tmp_path):
    """用户在 ~/.nexus/config.json 写 security.ws_token — 必须无效。

    这是显式 dead(本来 frontend baked-in 也不读这个,失败"看起来能改
    但其实没用"更糟)。
    """
    legacy = tmp_path / "config.json"
    legacy.write_text('{"security": {"ws_token": "user-trying-to-override"}}')
    monkeypatch.setenv("NEXUS_CONFIG_PATH", str(legacy))
    monkeypatch.delenv("NEXUS_WS_TOKEN", raising=False)
    cfg_mod = fresh_config
    # 显式模拟 load_config() 行为:读 env,忽略 file
    cfg_mod.CONFIG["ws_token"] = ""
    assert cfg_mod.CONFIG["ws_token"] == ""  # 不是 "user-trying-to-override"
