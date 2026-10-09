"""WS auth query fallback 默认关闭 测试。

WHY: spec §3 P0-1: query fallback 默认从 "true" 改 "false", token 不进 URL。
本测试锁默认行为,防被人改回 true。
"""

from __future__ import annotations


def test_query_fallback_rejected_by_default() -> None:
    """env 未设 NEXUS_WS_AUTH_QUERY_FALLBACK 时,query token 必须拒绝。"""
    import os

    os.environ.pop("NEXUS_WS_AUTH_QUERY_FALLBACK", None)

    from nexus.backend.api.ws import auth as _auth

    assert _auth._is_query_fallback_enabled() is False


def test_query_fallback_explicit_false_rejected() -> None:
    """env 设 "false" 时,query token 必须拒绝。"""
    import os

    os.environ["NEXUS_WS_AUTH_QUERY_FALLBACK"] = "false"
    try:
        from nexus.backend.api.ws import auth as _auth

        assert _auth._is_query_fallback_enabled() is False
    finally:
        os.environ.pop("NEXUS_WS_AUTH_QUERY_FALLBACK", None)


def test_query_fallback_wrong_token_rejected() -> None:
    """query fallback 即便开启,token 错误也必须 401(由 _hmac_compare 兜底)。

    WHY: _extract_token 只负责抽取候选 token,验证走 _hmac_compare。两层
    解耦:抽取纯函数 + 常量时间比较 守护边界。本测试断言抽取行为 + 调用
    方 _hmac_compare 必须拒掉错 token。
    """
    import os

    os.environ["NEXUS_WS_AUTH_QUERY_FALLBACK"] = "true"
    try:
        from nexus.backend.api.ws import auth as _auth

        # 1) 抽取层:env 开时,query token 会被抽出来当候选
        result = _auth._extract_token(
            subprotocol_header=None,
            query_params={"token": "wrong-token"},
        )
        assert result == "wrong-token"  # 候选抽出,验证在下一关

        # 2) 验证层:错 token vs 期望 token 必须 False(常量时间比较)
        assert _auth._hmac_compare(result, "expected-correct-token") is False
    finally:
        os.environ.pop("NEXUS_WS_AUTH_QUERY_FALLBACK", None)
