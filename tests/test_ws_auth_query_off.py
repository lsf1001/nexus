"""WS auth query fallback 默认关闭 测试。

WHY: spec §3 P0-1: query fallback 默认从 "true" 改 "false", token 不进 URL。
本测试锁默认行为,防被人改回 true。
"""

from __future__ import annotations

import pytest

from nexus.backend.api.ws import auth as _auth


@pytest.mark.parametrize("raw", [None, "false", "FALSE", "0", ""])
def test_query_fallback_default_and_false_rejected(monkeypatch, raw) -> None:
    """env 未设 / "false" / 异常值 → 全部 fail-closed。

    WHY 5 用例合一: 默认态(None)+ 显式 false + 大写 FALSE + falsy 边界
    "0" 和空串都要被拒。 一次跑遍所有 fail-closed 路径,防有人改阈值。
    """
    if raw is None:
        monkeypatch.delenv("NEXUS_WS_AUTH_QUERY_FALLBACK", raising=False)
    else:
        monkeypatch.setenv("NEXUS_WS_AUTH_QUERY_FALLBACK", raw)

    assert _auth._is_query_fallback_enabled() is False


def test_query_fallback_extracts_candidate_then_hmac_rejects(monkeypatch) -> None:
    """query fallback 开启时, _extract_token 照提候选, _hmac_compare 拒掉。

    WHY: 锁两层合约(候选提取 + 校验解耦)防止后续合并逻辑。
    """
    monkeypatch.setenv("NEXUS_WS_AUTH_QUERY_FALLBACK", "true")

    candidate = _auth._extract_token(
        subprotocol_header=None,
        query_params={"token": "wrong-token"},
    )
    assert candidate == "wrong-token"  # 候选照提
    # 校验由 _hmac_compare 拒掉(单元边界)
    assert _auth._hmac_compare(candidate, "expected-correct-token") is False
