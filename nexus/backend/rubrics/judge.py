"""Rubric 评分判官：用独立 LLM 并发按多个维度对一次响应打分。

本模块是 Phase 2 (Rubrics) 的核心执行层——给定"用户问题 + 助手回复
+ 工具调用列表"，调用一个独立 LLM（建议用 :class:`ResilientRunnable`
包装以保留超时/重试/降级），并发地按每个 Rubric 维度评分，返回
:class:`list[Score]`。

设计要点：
  - **并发**：用 :func:`asyncio.gather` 并发调用所有 rubric，避免 N×延迟。
  - **隔离失败**：单个 rubric 评分失败（含 LLM 异常 / 超时 / JSON 解析失败）
    走该位置的 fallback :class:`Score`，不污染其他 rubric。
  - **JSON 严格解析 + 重试**：rubric prompt 强制 LLM 输出 ``{"score", "reasoning", "evidence"}``
    严格 JSON；解析失败时把"上次原文本 + 纠错指令"喂回去重试，最多
    ``max_parse_retries`` 次。
  - **RubricJudgeError**：当所有 rubric 都失败时抛出，让上层
    pipeline 决定如何降级（Phase 2.5 处理），不污染主流程。
  - **自动注入 prompt**：构造时若调用方未传 rubrics，会使用
    :data:`schemas.DEFAULT_RUBRICS` 并自动调
    :func:`prompts.apply_prompts_to_default_rubrics`，确保 prompt 字段非空。
  - **不可变**：rubrics 在构造期转成 tuple，stats 用 frozenset 风格的 dict 累加。
  - **类型注解**：所有公开方法、参数、返回均标注类型。
  - **无 LangChain 业务耦合**：只依赖 ``BaseChatModel`` 接口（``ainvoke``）
    和 Pydantic ``AIMessage`` 形态（``.content`` 字段）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Sequence
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from . import schemas
from .prompts import apply_prompts_to_default_rubrics
from .schemas import Rubric, Score

__all__ = ["RubricJudgeError", "RubricJudge"]


logger = logging.getLogger(__name__)


# ==================== 异常 ====================


class RubricJudgeError(Exception):
    """所有 rubric 评分都失败时抛出。

    由上层 QualityPipeline 决定降级策略（如跳过自评直接放行，或
    写入 quality_scores 表但 verdict = unknown）。不污染主流程。
    """


# ==================== 主类 ====================


class RubricJudge:
    """并发按多 Rubric 维度对一次响应评分的判官。

    Attributes:
        llm: 评分用 LLM，应是 :class:`BaseChatModel` 子类；推荐用
            :class:`~nexus.backend.llm.wrapper.ResilientRunnable` 包装
            以获得超时 + 重试 + 降级。
        rubrics: 待评估的 rubric 列表（构造时转 tuple，运行时不可变）。
        max_parse_retries: JSON 解析失败时的最大重试次数（不含首次）。
        per_rubric_timeout: 单个 rubric 调用的超时秒数；超时归为该
            rubric 失败（fallback Score），不抛 :class:`RubricJudgeError`。
    """

    _REASONING_MAX_CHARS = 500
    _EVIDENCE_MAX_ITEMS = 5

    def __init__(
        self,
        llm: BaseChatModel,
        rubrics: Sequence[Rubric] | None = None,
        max_parse_retries: int = 1,
        per_rubric_timeout: float = 30.0,
    ) -> None:
        """初始化 RubricJudge。

        Args:
            llm: 评分用 LLM（``BaseChatModel`` 子类）。
            rubrics: 评分维度列表；``None`` 时用 ``DEFAULT_RUBRICS``，
                并自动调用 :func:`apply_prompts_to_default_rubrics` 注入 prompt。
            max_parse_retries: JSON 解析失败的最大重试次数（不含首次），
                必须 ``>= 0``。
            per_rubric_timeout: 单 rubric 调用的超时秒数，必须 ``> 0``。

        Raises:
            ValueError: 参数非法（rubrics 为空 / 重试次数为负 / 超时非正）。
        """
        if max_parse_retries < 0:
            raise ValueError(f"max_parse_retries 必须 >= 0，当前 {max_parse_retries}")
        if per_rubric_timeout <= 0:
            raise ValueError(f"per_rubric_timeout 必须 > 0，当前 {per_rubric_timeout}")

        self._llm = llm
        if rubrics is None:
            # 缺省场景：把 prompt 注入 DEFAULT_RUBRICS，再拿当前快照
            apply_prompts_to_default_rubrics()
            self._rubrics: tuple[Rubric, ...] = tuple(schemas.DEFAULT_RUBRICS)
        else:
            self._rubrics = tuple(rubrics)

        if not self._rubrics:
            raise ValueError("RubricJudge.rubrics 不能为空")

        self._max_parse_retries = max_parse_retries
        self._per_rubric_timeout = per_rubric_timeout

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    async def judge(
        self,
        question: str,
        response: str,
        tool_calls: Sequence[dict] | None = None,
    ) -> list[Score]:
        """并发对一次响应按所有 rubric 评分。

        Args:
            question: 用户原始问题。
            response: 助手回复（已剥离 ``<thinking>`` 标签）。
            tool_calls: 工具调用列表 ``[{"name", "args", "result"}, ...]``，
                传 ``None`` 表示无工具调用。

        Returns:
            与 ``self._rubrics`` 一一对应的 :class:`Score` 列表；每个位置
            的 score 在 ``[0, 1]`` 区间，失败时是 fallback Score（score=0.0，
            reasoning 含失败原因）。

        Raises:
            RubricJudgeError: 所有 rubric 都失败时抛出。
        """
        tasks = [self._evaluate_one(rubric, question, response, tool_calls) for rubric in self._rubrics]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        scores: list[Score] = []
        for rubric, outcome in zip(self._rubrics, results, strict=True):
            if isinstance(outcome, BaseException):
                logger.warning("rubric %s 评估异常: %s", rubric.name, outcome)
                scores.append(_fallback_score(rubric.name, outcome))
            else:
                scores.append(outcome)

        if all(s.score == 0.0 and "fallback" in s.reasoning for s in scores):
            raise RubricJudgeError(f"所有 {len(scores)} 个 rubric 评分均失败")
        return scores

    # ------------------------------------------------------------------
    # 内部：单 rubric 评分
    # ------------------------------------------------------------------

    async def _evaluate_one(
        self,
        rubric: Rubric,
        question: str,
        response: str,
        tool_calls: Sequence[dict] | None,
    ) -> Score:
        """对单个 rubric 评分：JSON 解析失败时重试，异常/超时时走 fallback。"""
        last_error: Exception | None = None
        for attempt in range(self._max_parse_retries + 1):
            try:
                messages = _build_messages(rubric, question, response, tool_calls, retry_feedback=last_error)
                raw = await asyncio.wait_for(
                    self._llm.ainvoke(messages),
                    timeout=self._per_rubric_timeout,
                )
                content = _extract_content(raw)
                score = _parse_score(rubric.name, content)
                return score
            except TimeoutError as exc:
                # 超时不重试（重试也大概率超时），直接 fallback
                logger.warning("rubric %s 超时: %s", rubric.name, exc)
                return _fallback_score(rubric.name, exc)
            except (ValueError, json.JSONDecodeError) as exc:
                # 解析错误：记录错误供下次重试作为反馈
                last_error = exc
                logger.info(
                    "rubric %s JSON 解析失败 (attempt %d/%d): %s",
                    rubric.name,
                    attempt + 1,
                    self._max_parse_retries + 1,
                    exc,
                )
            except Exception as exc:  # noqa: BLE001 — 边界统一收口
                # 任何其他异常（LLM 故障 / 网络 / ClassifiedError 等）→ fallback
                logger.warning("rubric %s 评估异常: %s", rubric.name, exc)
                return _fallback_score(rubric.name, exc)

        # 重试耗尽仍解析失败 → fallback
        return _fallback_score(
            rubric.name,
            last_error or ValueError("JSON 解析失败"),
        )

    # ------------------------------------------------------------------
    # 只读属性
    # ------------------------------------------------------------------

    @property
    def rubrics(self) -> tuple[Rubric, ...]:
        """当前 rubric 列表（不可变拷贝）。"""
        return self._rubrics

    @property
    def llm(self) -> BaseChatModel:
        """评分用 LLM。"""
        return self._llm


# ==================== 模块级辅助函数 ====================


def _build_messages(
    rubric: Rubric,
    question: str,
    response: str,
    tool_calls: Sequence[dict] | None,
    retry_feedback: Exception | None,
) -> list:
    """构造 LLM 调用消息列表：system=rubric.prompt，user=待评估文本。

    重试时把上次的错误拼到 user 消息末尾，让 LLM 知道上次输错了。
    """
    tool_section = _format_tool_calls(tool_calls)
    user_body = (
        f"【待评估对话】\n"
        f"用户问题：{question}\n"
        f"助手回复：{response}\n"
        f"工具调用：{tool_section}\n\n"
        f"请输出严格 JSON（无其他文字）：\n"
        f'{{"score": 0.0-1.0, "reasoning": "中文 50-150 字", '
        f'"evidence": ["片段1", "片段2"]}}'
    )
    if retry_feedback is not None:
        user_body += f"\n\n【上次解析失败】\n错误：{retry_feedback}\n请只输出一个合法 JSON 对象，不要任何解释或前后缀。"
    return [
        SystemMessage(content=rubric.prompt),
        HumanMessage(content=user_body),
    ]


def _format_tool_calls(tool_calls: Sequence[dict] | None) -> str:
    """把工具调用列表格式化为可读文本。空列表或 None 返回 '无'。"""
    if not tool_calls:
        return "无"
    lines: list[str] = []
    for idx, call in enumerate(tool_calls, start=1):
        name = call.get("name", "未知工具")
        args = call.get("args", {})
        result = call.get("result", "")
        args_str = json.dumps(args, ensure_ascii=False) if args else "{}"
        result_str = str(result)[:200] if result else ""
        lines.append(f"{idx}. {name}({args_str}) → {result_str}")
    return "\n".join(lines)


def _extract_content(raw: Any) -> str:
    """从 LLM 返回中抽取文本内容（兼容 AIMessage / dict / str）。"""
    if isinstance(raw, AIMessage):
        return str(raw.content or "")
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        # LangChain 早期版本返回 dict，常见 key 有 "content" / "text"
        return str(raw.get("content") or raw.get("text") or "")
    # 兜底：尝试常见属性
    content = getattr(raw, "content", None)
    if content is not None:
        return str(content)
    return str(raw)


def _parse_score(rubric_name: str, content: str) -> Score:
    """解析 LLM 输出的严格 JSON，构造 :class:`Score`。

    解析失败抛 :class:`ValueError`（让外层重试逻辑接住）。
    """
    text = _strip_to_json(content)
    if not text:
        raise ValueError(f"未找到 JSON 对象：{content[:200]!r}")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"JSON 顶层不是 object：{type(data).__name__}")

    raw_score = data.get("score", 0.0)
    try:
        score = float(raw_score)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"score 字段无法转 float：{raw_score!r}") from exc
    # clamp 到 [0, 1]
    score = max(0.0, min(1.0, score))

    reasoning_raw = str(data.get("reasoning") or "").strip()
    reasoning = reasoning_raw[: RubricJudge._REASONING_MAX_CHARS]

    evidence_raw = data.get("evidence") or []
    if not isinstance(evidence_raw, list):
        evidence_raw = [str(evidence_raw)]
    evidence = tuple(str(item)[:200] for item in evidence_raw[: RubricJudge._EVIDENCE_MAX_ITEMS])

    return Score(
        rubric_name=rubric_name,
        score=score,
        reasoning=reasoning or "(无解释)",
        evidence=evidence,
    )


# 匹配首个 JSON 对象（含嵌套 {}）
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _strip_to_json(content: str) -> str:
    r"""从 LLM 输出中抽取首个 JSON 对象。

    兼容 LLM 在 JSON 前后加解释文字、`` ```json ... ``` `` 围栏的情况。
    """
    text = content.strip()
    # 去掉 ```json ... ``` 围栏
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    match = _JSON_OBJECT_RE.search(text)
    return match.group(0) if match else text


def _fallback_score(rubric_name: str, exc: BaseException) -> Score:
    """当某个 rubric 评分失败时构造 fallback :class:`Score`。

    fallback 的 score 强制为 0.0，reasoning 含失败类型 + 异常信息，
        evidence 为空 tuple。
    """
    reason = f"[fallback] {type(exc).__name__}: {exc}"
    return Score(
        rubric_name=rubric_name,
        score=0.0,
        reasoning=reason[: RubricJudge._REASONING_MAX_CHARS],
        evidence=(),
    )
