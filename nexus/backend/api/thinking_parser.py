"""流式 <thinking> 标签识别状态机。

WHY 单独抽出:WS 流式必须实时识别标签(标签可能跨 chunk 分片),
抽成纯逻辑类便于单元测试覆盖所有边界,不留暗坑。

设计要点:
- 状态机:response ↔ thinking,初始 response
- 累积缓冲区:上次 chunk 末尾可能带半截标签(<thin / </think),
  必须 hold 到下次 chunk 合并才能判断
- 归一化:`<think>` ↔ `<thinking>` 同义,统一识别成 <thinking>
- flush():流末兜底,未闭合的 thinking 块作为 thinking 帧发出,
  未识别的部分标签作为 chunk 发出(避免丢字)
"""

from __future__ import annotations

from typing import Literal

_Kind = Literal["chunk", "thinking"]
_Emission = tuple[_Kind, str]


class ThinkingParser:
    """把 LLM 流式 content 实时切分成 chunk / thinking 帧。

    用法::

        parser = ThinkingParser()
        for content_chunk in llm_stream:
            for kind, text in parser.feed(content_chunk):
                await ws.send_json({"type": kind, "content": text, ...})
        for kind, text in parser.flush():
            await ws.send_json({"type": kind, "content": text, ...})
    """

    _OPEN = "<thinking>"
    _CLOSE = "</thinking>"
    _ALT_OPEN = "<think>"
    _ALT_CLOSE = "</think>"
    _MIN_OPEN_LEN = min(len(_OPEN), len(_ALT_OPEN))
    _MIN_CLOSE_LEN = min(len(_CLOSE), len(_ALT_CLOSE))

    def __init__(self) -> None:
        self._state: _Kind = "chunk"
        self._hold: str = ""
        self._thinking_acc: str = ""

    def feed(self, content: str) -> list[_Emission]:
        if not content:
            return []
        emissions: list[_Emission] = []
        text = self._hold + content
        self._hold = ""

        while text:
            if self._state == "chunk":
                self._consume_in_response(text, emissions)
                if self._hold:
                    return emissions
                return emissions
            else:
                self._consume_in_thinking(text, emissions)
                if self._hold:
                    return emissions
                return emissions

        return emissions

    def flush(self) -> list[_Emission]:
        emissions: list[_Emission] = []
        if self._hold:
            emissions.append(("chunk", self._hold))
            self._hold = ""
        if self._thinking_acc:
            emissions.append(("thinking", self._thinking_acc))
            self._thinking_acc = ""
        return emissions

    def _consume_in_response(self, text: str, emissions: list[_Emission]) -> None:
        idx = self._find_open_tag(text)
        if idx == -1:
            # WHY 优先看 close 标签:chunk 状态下 close 标签没有匹配的 open,
            # 应当跳过(close 标签是 thinking 状态的退出点,文本无意义)。
            close_idx = self._find_close_tag(text)
            if close_idx != -1:
                after_close = self._advance_close(text, close_idx)
                rest = text[after_close:]
                if rest:
                    self._consume_in_response(rest, emissions)
                return
            partial = self._longest_partial_open(text)
            partial_close = self._longest_partial_close(text)
            # WHY 短 partial 整段 hold:<thin(5字符)永远凑不够
            # <thinking>(9字符),前面的普通字符不能先 emit,
            # 否则下一 chunk 拼出 "</thinking>" 时会丢字。
            if partial and len(partial) < self._MIN_OPEN_LEN:
                self._hold = text
            elif partial_close and len(partial_close) < self._MIN_CLOSE_LEN:
                self._hold = text
            else:
                chosen = self._pick_partial(partial, partial_close)
                if chosen:
                    head = text[: -len(chosen)]
                    if head:
                        emissions.append(("chunk", head))
                    self._hold = chosen
                else:
                    emissions.append(("chunk", text))
            return

        if idx > 0:
            emissions.append(("chunk", text[:idx]))
        after_open = self._advance_open(text, idx)
        self._state = "thinking"
        rest = text[after_open:]
        if rest:
            self._consume_in_thinking(rest, emissions)

    def _consume_in_thinking(self, text: str, emissions: list[_Emission]) -> None:
        idx = self._find_close_tag(text)
        if idx == -1:
            partial = self._longest_partial_close(text)
            if partial:
                self._thinking_acc += text[: -len(partial)]
                if self._thinking_acc:
                    emissions.append(("thinking", self._thinking_acc))
                    self._thinking_acc = ""
                # WHY 切回 chunk + hold partial:close partial 暗示
                # "已离开 thinking 状态",即使后续 partial 拼不出完整 close,
                # 至少前段 thinking 已交付,close partial 在 chunk 状态
                # 不消耗,flush 时兜底 emit 为 chunk。
                self._state = "chunk"
                self._hold = partial
            else:
                self._thinking_acc += text
            return

        self._thinking_acc += text[:idx]
        if self._thinking_acc:
            emissions.append(("thinking", self._thinking_acc))
            self._thinking_acc = ""
        after_close = self._advance_close(text, idx)
        self._state = "chunk"
        rest = text[after_close:]
        if rest:
            self._consume_in_response(rest, emissions)

    def _find_open_tag(self, text: str) -> int:
        candidates: list[int] = []
        i1 = text.find(self._OPEN)
        if i1 != -1:
            candidates.append(i1)
        i2 = text.find(self._ALT_OPEN)
        if i2 != -1:
            candidates.append(i2)
        return min(candidates) if candidates else -1

    def _find_close_tag(self, text: str) -> int:
        candidates: list[int] = []
        i1 = text.find(self._CLOSE)
        if i1 != -1:
            candidates.append(i1)
        i2 = text.find(self._ALT_CLOSE)
        if i2 != -1:
            candidates.append(i2)
        return min(candidates) if candidates else -1

    def _advance_open(self, text: str, idx: int) -> int:
        if text[idx : idx + len(self._ALT_OPEN)] == self._ALT_OPEN:
            return idx + len(self._ALT_OPEN)
        return idx + len(self._OPEN)

    def _advance_close(self, text: str, idx: int) -> int:
        if text[idx : idx + len(self._ALT_CLOSE)] == self._ALT_CLOSE:
            return idx + len(self._ALT_CLOSE)
        return idx + len(self._CLOSE)

    def _longest_partial_open(self, text: str) -> str:
        """返回 text 末尾可能继续成完整 open 标签的 partial。

        open 标签以 `<t` 开头;close 标签以 `</` 开头。如果末尾的 `<`
        实际上是 close 标签起点,这里不识别(交给 _longest_partial_close)。
        """
        candidate = text.rfind("<")
        if candidate == -1:
            return ""
        suffix = text[candidate:]
        if suffix.startswith("</"):
            return ""
        if self._OPEN.startswith(suffix) or self._ALT_OPEN.startswith(suffix):
            return suffix
        return ""

    def _longest_partial_close(self, text: str) -> str:
        """返回 text 末尾可能继续成完整 close 标签的 partial。

        close 标签以 `</` 开头;open 标签以 `<t` 开头,这里不识别。
        """
        candidate = text.rfind("<")
        if candidate == -1:
            return ""
        suffix = text[candidate:]
        if not suffix.startswith("</"):
            return ""
        if self._CLOSE.startswith(suffix) or self._ALT_CLOSE.startswith(suffix):
            return suffix
        return ""

    def _pick_partial(self, open: str, close: str) -> str:
        """从 open / close partial 中选更靠右的那个(更长的 hold)。"""
        if not open and not close:
            return ""
        if not open:
            return close
        if not close:
            return open
        return open if len(open) >= len(close) else close
