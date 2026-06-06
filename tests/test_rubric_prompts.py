"""Phase 2 Task 2.2: 中文 Rubric Prompt 模板单元测试。

覆盖：
  - 4 个 prompt 常量都是非空字符串
  - 每个 prompt 都含：评分维度、JSON 输出格式、正反例、evidence 字段
  - 长度合规（200-500 中文字符）
  - RUBRIC_PROMPTS 字典覆盖全部 4 个内置 Rubric
  - apply_prompts_to_default_rubrics 把 prompt 注入 DEFAULT_RUBRICS
  - prompt 主体是中文（中文 char / total char 比例 > 0.3）

不依赖 LLM / LangChain / DB：prompts 是纯文本模板层。
"""

from __future__ import annotations

from nexus.backend.rubrics.prompts import (
    FAITHFULNESS_PROMPT,
    RELEVANCE_PROMPT,
    RUBRIC_PROMPTS,
    SAFETY_PROMPT,
    TOOL_CORRECTNESS_PROMPT,
    apply_prompts_to_default_rubrics,
)


def _chinese_char_count(text: str) -> int:
    """统计 CJK 统一汉字（U+4E00 - U+9FFF）字符数。"""
    return sum(1 for c in text if "一" <= c <= "鿿")


def _chinese_ratio(text: str) -> float:
    """中文字符占总字符的比例。"""
    chinese = _chinese_char_count(text)
    return chinese / max(1, len(text))


# ====== 4 个 prompt 常量都存在且非空 ======


def test_all_four_prompts_exist():
    """4 个 prompt 都是非空字符串。"""
    assert FAITHFULNESS_PROMPT and isinstance(FAITHFULNESS_PROMPT, str)
    assert RELEVANCE_PROMPT and isinstance(RELEVANCE_PROMPT, str)
    assert SAFETY_PROMPT and isinstance(SAFETY_PROMPT, str)
    assert TOOL_CORRECTNESS_PROMPT and isinstance(TOOL_CORRECTNESS_PROMPT, str)


# ====== 必含结构：评分维度 / JSON 输出 / 正反例 / evidence ======


def test_prompts_contain_required_sections():
    """每个 prompt 都含：评分维度、JSON 输出格式、至少 1 正例 1 反例、evidence 字段。"""
    for name, prompt in RUBRIC_PROMPTS.items():
        # 评分维度（5 档）
        assert "1.0" in prompt, f"{name} 缺 1.0 评分档位"
        assert "0.5" in prompt, f"{name} 缺 0.5 评分档位"
        # JSON 输出格式
        assert "score" in prompt, f"{name} 缺 score 字段"
        assert "reasoning" in prompt, f"{name} 缺 reasoning 字段"
        assert "JSON" in prompt, f"{name} 没强调 JSON 输出"
        # 正反例标记
        assert "正例" in prompt, f"{name} 缺正例"
        assert "反例" in prompt, f"{name} 缺反例"
        # 引用 evidence 字段
        assert "evidence" in prompt, f"{name} 缺 evidence 字段要求"


# ====== 长度合规：200-500 中文字符 ======


def test_prompts_length_200_to_500_chinese_chars():
    """每个 prompt 200-500 中文字符（Task 2.2 硬性要求）。"""
    for name, prompt in RUBRIC_PROMPTS.items():
        n = _chinese_char_count(prompt)
        assert 200 <= n <= 500, f"{name} 中文 {n} 字，超出 200-500 范围"


# ====== RUBRIC_PROMPTS 字典覆盖 4 个 Rubric ======


def test_prompts_dict_covers_all_4_rubrics():
    """RUBRIC_PROMPTS 字典含 4 个 key，且 key 与 DEFAULT_RUBRICS 一致。"""
    from nexus.backend.rubrics.schemas import DEFAULT_RUBRICS

    expected = {r.name for r in DEFAULT_RUBRICS}
    assert set(RUBRIC_PROMPTS.keys()) == expected
    assert set(RUBRIC_PROMPTS.keys()) == {
        "faithfulness",
        "relevance",
        "safety",
        "tool_correctness",
    }


# ====== 启动期注入：apply_prompts_to_default_rubrics ======


def test_apply_prompts_injects_into_default_rubrics():
    """apply_prompts_to_default_rubrics 把 prompt 注入 DEFAULT_RUBRICS。"""
    apply_prompts_to_default_rubrics()
    from nexus.backend.rubrics.schemas import DEFAULT_RUBRICS

    for r in DEFAULT_RUBRICS:
        assert r.prompt, f"Rubric '{r.name}' prompt 仍为空"
        assert r.prompt == RUBRIC_PROMPTS[r.name], f"Rubric '{r.name}' prompt 不一致"


def test_apply_prompts_preserves_other_fields():
    """apply_prompts_to_default_rubrics 只替换 prompt 字段，其他字段保持不变。"""
    apply_prompts_to_default_rubrics()
    from nexus.backend.rubrics.schemas import DEFAULT_RUBRICS

    for r in DEFAULT_RUBRICS:
        assert 0.0 <= r.weight <= 1.0, f"weight 被改坏: {r.name}"
        assert 0.0 <= r.repair_threshold <= r.accept_threshold <= 1.0, f"阈值被改坏: {r.name}"


# ====== prompt 主体是中文 ======


def test_prompts_are_predominantly_chinese():
    """prompt 主体是中文（中文 char / total char 比例 > 0.3）。

    0.3 是下限：prompt 含 JSON 示例、字段名、占位符等英文，但骨架是中文。
    """
    for name, prompt in RUBRIC_PROMPTS.items():
        ratio = _chinese_ratio(prompt)
        assert ratio > 0.3, f"{name} 中文比例 {ratio:.2%} 偏低（混入太多英文/标点）"


# ====== 内容语义：每个 prompt 强调自身角色 ======


def test_each_prompt_declares_role():
    """每个 prompt 自身用"评分员"等中文身份定位，方便 Judge LLM 进入角色。"""
    for name, prompt in RUBRIC_PROMPTS.items():
        assert "评分员" in prompt, f"{name} 没声明评分员身份"
