"""Deterministic fact-check pipeline.

Catches factual errors (date/weekday, math, units, exchange rate) before
user-facing output. Rule-based verifiers, never LLM-judged.
"""

from nexus.backend.fact_check.pipeline import FactCheckPipeline, FactCheckReport, VerificationResult

__all__ = ["FactCheckPipeline", "FactCheckReport", "VerificationResult"]
