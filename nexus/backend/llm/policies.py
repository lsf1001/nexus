"""LLM 韧性策略 dataclass 模块。

该模块把"重试 / 切换模型 / 超时"这三种韧性配置封装成不可变的 dataclass，
供上层的 LLM 调用包装器（Task 1.3 的 wrapper.py）使用。

设计目标：
  - 与具体 SDK / 业务调用解耦：这一层只描述策略，不调用 tenacity / langchain。
  - 不可变（``frozen=True``）：下游不应改共享配置，避免引入隐式状态。
  - 字段可自定义：默认值是合理的产品默认；用户/租户可按需覆盖。
  - 字段类型明确：避免使用可变对象作为默认参数（CLAUDE.md §11）。

抖动算法选择：
  采用"乘法抖动"（multiplicative jitter），公式为
  ``delay = base_delay * (2 ** attempt) * (1 + random.uniform(-jitter, +jitter))``，
  然后 clamp 到 ``[0, max_delay]``。

  理由：
    1. 与设计文档中"±jitter 比例"的描述完全一致，行为可预测。
    2. 乘法抖动在高 jitter 下不会让延迟直接塌缩为 0，也不会暴涨到失控。
    3. 实现简单，无依赖，便于测试用 ``random.seed`` 控住。
  备选方案（``full jitter``: ``random.uniform(0, base * 2**attempt)``）
  也常见，但会让"最大可能延迟"无法预知，不利于外部观测。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from nexus.backend.llm.errors import ClassifiedError, LLMErrorKind

__all__ = [
    "RetryPolicy",
    "FallbackPolicy",
    "TimeoutPolicy",
]


# 默认可重试的错误种类集合：与 errors._default_retryable 保持一致。
_DEFAULT_RETRYABLE_KINDS: frozenset[LLMErrorKind] = frozenset(
    {
        LLMErrorKind.RATE_LIMIT,
        LLMErrorKind.TIMEOUT,
        LLMErrorKind.CONTENT_FILTER,
        LLMErrorKind.UNKNOWN,
    }
)

# 默认允许 fallback 的错误种类集合。
# 注意：AUTH 也包含在内——主模型鉴权失败时换备用供应商是合理的降级路径。
# 但 BAD_REQUEST / CONTEXT_LENGTH 不会触发 fallback，重试/改 prompt 更合适。
_DEFAULT_FALLBACK_KINDS: frozenset[LLMErrorKind] = frozenset(
    {
        LLMErrorKind.RATE_LIMIT,
        LLMErrorKind.TIMEOUT,
        LLMErrorKind.UNKNOWN,
        LLMErrorKind.AUTH,
    }
)


@dataclass(frozen=True)
class RetryPolicy:
    """重试策略：指数退避 + 抖动。

    Attributes:
        max_attempts: 总尝试次数（含首次），``1`` 表示不重试。
        base_delay: 首次重试的基础延迟（秒），后续按 2 的幂放大。
        max_delay: 单次重试的最大延迟（秒），用于 clamp。
        jitter: 抖动比例，``0.0`` 表示无抖动，``0.2`` 表示 ±20%。
        retryable_kinds: 允许触发重试的错误种类集合。
    """

    max_attempts: int = 3
    base_delay: float = 0.1
    max_delay: float = 2.0
    jitter: float = 0.2
    retryable_kinds: frozenset[LLMErrorKind] = field(
        default=frozenset(_DEFAULT_RETRYABLE_KINDS),
    )

    def compute_delay(self, attempt: int) -> float:
        """计算第 ``attempt`` 次重试的延迟（秒）。

        ``attempt`` 从 ``0`` 开始：``attempt=0`` 对应"第一次失败后立即重试"。

        公式：``base_delay * (2 ** attempt) * (1 + jitter_noise)``，
        其中 ``jitter_noise`` 是 ``[-jitter, +jitter]`` 之间的均匀随机数。
        最终延迟被 clamp 到 ``[0, max_delay]``。

        Args:
            attempt: 重试次数（从 0 起）。负数按 0 处理（避免 ``2 ** -1`` 的怪异语义）。

        Returns:
            等待秒数，``>= 0`` 且 ``<= max_delay``。
        """
        if attempt < 0:
            attempt = 0
        base = self.base_delay * (2 ** attempt)
        # jitter == 0 时直接退化为确定值，便于测试断言。
        noise = random.uniform(-self.jitter, self.jitter) if self.jitter > 0 else 0.0
        delay = base * (1.0 + noise)
        if delay < 0.0:
            delay = 0.0
        if delay > self.max_delay:
            delay = self.max_delay
        return delay

    def should_retry(self, attempt: int, classified: ClassifiedError) -> bool:
        """判断在第 ``attempt`` 次失败后是否还应继续重试。

        判定条件（同时满足才返回 ``True``）：
          - 剩余额度足够：``attempt + 1 < max_attempts``。
            含义是"已经发起过 ``attempt + 1`` 次（含首次），
            还要再发一次才算重试，所以必须严格小于额度"。
          - 错误种类在 ``retryable_kinds`` 内。

        Args:
            attempt: 已经发起的尝试次数（0 表示刚首次失败）。
            classified: 已分类的错误对象。

        Returns:
            是否应当再重试一次。
        """
        return (
            attempt + 1 < self.max_attempts
            and classified.kind in self.retryable_kinds
        )


@dataclass(frozen=True)
class FallbackPolicy:
    """模型降级链策略：按顺序尝试多个 LLM。

    Attributes:
        chains: LLM 实例序列（如 ``(primary, secondary, tertiary)``），
            类型刻意写成 ``tuple[Any, ...]``，避免在这一层耦合 langchain。
        fallback_kinds: 允许触发 fallback 的错误种类集合。
    """

    chains: tuple[Any, ...] = ()
    fallback_kinds: frozenset[LLMErrorKind] = field(
        default=frozenset(_DEFAULT_FALLBACK_KINDS),
    )

    def should_fallback(self, classified: ClassifiedError) -> bool:
        """判断该错误是否应该触发 fallback。

        设计取舍：
          - AUTH 默认会触发 fallback（主供应商鉴权挂掉时换备用）。
          - BAD_REQUEST / CONTEXT_LENGTH 不会触发 fallback（应改 prompt）。
          - CONTENT_FILTER 不在默认集合内（换模型也不一定能过审，
            重试或许能等到内容策略波动，但更多应由上层决定）。

        Args:
            classified: 已分类的错误对象。

        Returns:
            是否应当切换到下一个 LLM。
        """
        return classified.kind in self.fallback_kinds

    def next_llm(self, current_index: int) -> tuple[int, Any | None]:
        """取下一个 LLM。

        Args:
            current_index: 当前已使用的 LLM 在 ``chains`` 中的索引。
                ``-1`` 表示还没开始，也视为"用 0 号"。

        Returns:
            ``(next_index, llm)`` 二元组。
              - 若还有下一个：``next_index = current_index + 1``，``llm`` 为该实例。
              - 若已耗尽：``next_index = len(chains)``，``llm`` 为 ``None``。
            调用方可通过 ``llm is None`` 判断链已走完。
        """
        next_index = current_index + 1
        if 0 <= next_index < len(self.chains):
            return next_index, self.chains[next_index]
        return next_index, None


@dataclass(frozen=True)
class TimeoutPolicy:
    """三档超时策略。

    Attributes:
        per_step: 单个推理步骤的超时（秒），
            如一次 ``ainvoke``、一次工具调用、单次流式 chunk 等待。
        per_call: 整次完整调用的总超时（秒），含多步推理。
        per_stream: 整个流式响应的总时长上限（秒）。
    """

    per_step: float = 30.0
    per_call: float = 120.0
    per_stream: float = 600.0
