"""Tests for fact_check.pipeline orchestrator."""

from nexus.backend.fact_check.pipeline import FactCheckPipeline


class TestFactCheckPipeline:
    def test_empty_text_returns_empty_report(self):
        pipeline = FactCheckPipeline()
        report = pipeline.check("今天天气不错")
        assert report.claims_total == 0
        assert report.has_conflict is False

    def test_correct_date_passes(self):
        pipeline = FactCheckPipeline()
        report = pipeline.check("明天是 2026年7月11日 星期六")
        assert report.claims_total == 1
        assert report.has_conflict is False

    def test_wrong_date_triggers_conflict(self):
        pipeline = FactCheckPipeline()
        report = pipeline.check("明天是 2026年7月11日 星期五")  # wrong weekday
        assert report.claims_total == 1
        assert report.has_conflict is True
        assert report.conflicts[0].verdict == "conflict"

    def test_wrong_math_triggers_conflict(self):
        pipeline = FactCheckPipeline()
        report = pipeline.check("23 + 32 = 56")  # should be 55
        assert report.has_conflict is True

    def test_disabled_claim_type_skipped(self):
        config = {"enabled_claim_types": ["date_weekday"]}
        pipeline = FactCheckPipeline(config=config)
        report = pipeline.check("23 + 32 = 56")
        assert report.claims_total == 0  # math not enabled

    def test_pipeline_returns_full_report(self):
        pipeline = FactCheckPipeline()
        text = "明天是 2026年7月11日 星期六。气温 23 + 32 = 55。"
        report = pipeline.check(text)
        assert report.claims_total == 2
        assert report.passed == 2
        assert report.failed == 0
