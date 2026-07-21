#!/usr/bin/env python3
"""Rubric 元评估 CLI：从人工标注样本 jsonl 跑 RubricJudge，输出 Pearson / Cohen's kappa。

用法：
    python scripts/eval_rubrics.py \\
        --samples ~/.nexus/evaluations/rubric_eval_samples.jsonl \\
        --output ~/.nexus/evaluations/eval_report.json

默认路径在 ~/.nexus/evaluations/ 下(与 nexus.db 同区,不入库)。
旧路径 ./data/* 仍可通过 --samples/--output 显式覆盖。

jsonl 样本格式（每行一个 JSON）：
    {
        "prompt": "什么是 Python？",
        "response": "Python 是一种解释型语言。",
        "expected_score": 0.9,
        "expected_verdict": "accept",
        "rubric_name": "faithfulness"
    }

退出码：
    0 = kappa >= 0.4（rubric 质量合格）
    1 = kappa < 0.4（rubric 不可信，需要重写 prompt）
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# 让脚本能从 nexus 顶层 import
sys.path.insert(0, str(Path(__file__).parent.parent))

from nexus.backend.rubrics.judge import RubricJudge
from nexus.backend.rubrics.meta_eval import (
    KAPPA_ALERT_THRESHOLD,
    MetaEvalResult,
    MetaEvalSample,
    run_meta_eval,
)
from nexus.backend.rubrics.schemas import RubricVerdict


def _load_samples(path: Path) -> list[MetaEvalSample]:
    """从 jsonl 文件读人工标注样本。"""
    samples: list[MetaEvalSample] = []
    with path.open(encoding="utf-8") as f:
        for _line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            samples.append(
                MetaEvalSample(
                    prompt=data["prompt"],
                    response=data["response"],
                    expected_score=float(data["expected_score"]),
                    expected_verdict=RubricVerdict(data["expected_verdict"]),
                    rubric_name=data.get("rubric_name", "faithfulness"),
                )
            )
    return samples


def _build_judge() -> RubricJudge:
    """构造默认 RubricJudge（用 nexus 配置的 LLM）。

    用 :func:`nexus.backend.agent.get_llm` 而非手动构造 ChatOpenAI，
    避免与主 Agent 的 model_config 不一致（model_name / api_base 不同会 404）。
    """
    from nexus.backend.agent import get_llm
    from nexus.backend.config import CONFIG
    from nexus.backend.models_config import get_active_model
    from nexus.backend.rubrics.prompts import apply_prompts_to_default_rubrics

    apply_prompts_to_default_rubrics()
    if not CONFIG.get("minimax_api_key"):
        print("ERROR: minimax_api_key 未配置，无法跑 judge", file=sys.stderr)
        sys.exit(2)

    model_config = get_active_model() or {}
    llm = get_llm(
        api_key=model_config.get("api_key") or CONFIG.get("minimax_api_key", ""),
        api_base=model_config.get("api_base") or CONFIG.get("minimax_api_base"),
        model_name=model_config.get("name", CONFIG.get("model_name", "MiniMax-M2.7")),
        temperature=model_config.get("temperature", CONFIG.get("temperature", 0.0)),
    )
    return RubricJudge(llm=llm)


def _print_report(result: MetaEvalResult) -> None:
    """打印元评估报告。"""
    print("=" * 60)
    print(f"Rubric 元评估报告（{result.n_samples} 样本）")
    print("=" * 60)
    print(f"Pearson 相关系数：     {result.pearson:+.3f}")
    print(f"Cohen's kappa：       {result.cohens_kappa:+.3f}")
    print(f"报警阈值：            {KAPPA_ALERT_THRESHOLD}")
    print(f"质量合格 (kappa>={KAPPA_ALERT_THRESHOLD})：  {result.is_acceptable}")
    print("-" * 60)
    if result.judge_scores:
        print("前 5 个样本对比：")
        for i in range(min(5, result.n_samples)):
            js = result.judge_scores[i]
            hs = result.human_scores[i]
            jv = result.judge_verdicts[i]
            hv = result.human_verdicts[i]
            mark = "✓" if jv == hv else "✗"
            print(f"  [{i + 1}] {mark}  Judge: {js:.2f} ({jv:6s})  Human: {hs:.2f} ({hv:6s})")


def _save_report(result: MetaEvalResult, output_path: Path) -> None:
    """把报告写成 json 供 CI 消费。"""
    report = {
        "n_samples": result.n_samples,
        "pearson": result.pearson,
        "cohens_kappa": result.cohens_kappa,
        "is_acceptable": result.is_acceptable,
        "alert_threshold": KAPPA_ALERT_THRESHOLD,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


def main() -> int:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(
        description="Rubric 元评估：跑人工标注样本 vs RubricJudge，输出 Pearson / Cohen's kappa"
    )
    parser.add_argument(
        "--samples",
        required=True,
        type=Path,
        help="人工标注样本 jsonl 路径",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="（可选）报告输出 json 路径",
    )
    args = parser.parse_args()

    if not args.samples.exists():
        print(f"ERROR: 样本文件不存在：{args.samples}", file=sys.stderr)
        return 2

    samples = _load_samples(args.samples)
    if not samples:
        print("ERROR: 样本文件为空", file=sys.stderr)
        return 2

    judge = _build_judge()
    result = asyncio.run(run_meta_eval(judge, samples))
    _print_report(result)

    if args.output:
        _save_report(result, args.output)
        print(f"\n报告已保存：{args.output}")

    return 0 if result.is_acceptable else 1


if __name__ == "__main__":
    sys.exit(main())
