"""Test fact_verify MCP server's verify_claims tool."""

import json

from nexus.backend.mcp.fact_verify import FactVerifyResult, verify_claims  # noqa: F401


class TestVerifyClaims:
    def test_no_claims_yields_ok(self):
        r = verify_claims("好的,我帮你查一下")
        assert r.ok is True
        assert r.conflicts_total == 0

    def test_correct_date_weekday_passes(self):
        # 2026-07-11 is 星期六 (per T13's weekday mapping)
        r = verify_claims("明天是2026年7月11日 星期六")
        assert r.ok is True
        assert r.conflicts_total == 0

    def test_wrong_weekday_caught(self):
        r = verify_claims("明天是2026年7月11日 星期五")
        assert r.ok is False
        assert r.conflicts_total >= 1

    def test_correct_math_passes(self):
        r = verify_claims("温差是 23 + 9 = 32 度")
        assert r.ok is True

    def test_wrong_math_caught(self):
        r = verify_claims("温差是 23 + 9 = 33 度")
        assert r.ok is False

    def test_to_dict_is_json_safe(self):
        r = verify_claims("明天是2026年7月11日 星期六")
        d = r.to_dict()
        # Must not raise
        json.dumps(d, ensure_ascii=False)
        assert "ok" in d

    def test_empty_string_no_crash(self):
        r = verify_claims("")
        assert r.ok is True
        assert r.conflicts_total == 0
