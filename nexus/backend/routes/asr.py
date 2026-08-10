"""Round 4 Task 4.3:语音转写 endpoint。

WHY 单独 router:asr 是 IO-heavy 第三方 API 路径,不属于 sessions / attachments
等业务 router,放独立文件好隔离 + 便于未来换 ASR 引擎(阿里云 / 腾讯云)。

设计:
- 优先调 OpenAI Whisper API(``OPENAI_API_KEY`` env 存在时)
- 无 key 走 mock fallback,返回固定 ``"语音输入(mock)"`` 文本
  - WHY mock 而不是 503:前端录音是高频操作,无 key 时仍要能跑通 E2E
    和 demo 流程;mock 文本明显,前端可在 UI 上提示"未配置 ASR"
- 25MB 上限跟 OpenAI Whisper 配额对齐,超出直接 413
- 整段转写抽成模块级函数,测试可 monkeypatch 注入 fake,避免 mock SDK 细节
"""

from __future__ import annotations

import io
import logging
import os
from collections.abc import Callable

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from ..api.ws import require_token

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/asr",
    tags=["asr"],
    dependencies=[Depends(require_token)],
)

# WHY 25MB:跟 OpenAI Whisper API 官方限额对齐,超过会被 OpenAI 直接拒,
# 后端先挡可以省一次往返 + 避免大文件把内存吃满
MAX_AUDIO_BYTES = 25 * 1024 * 1024

MOCK_TEXT = "语音输入(mock)"

# 模块级函数引用,测试 monkeypatch 时直接 setattr 替换
_call_whisper_fn: Callable[[bytes, str], str] | None = None


def _call_whisper(audio_bytes: bytes, mime: str) -> str:
    """调 OpenAI Whisper API,返回转写文本。

    WHY 抽成函数:让 test 通过 setattr 替换实现,不去 mock openai.OpenAI 构造。
    这样测试不依赖 OpenAI SDK 内部实现细节,只校验路由调度逻辑。

    Args:
        audio_bytes: 原始音频字节(webm / mp3 / wav 都行,SDK 自动识别)
        mime: MIME type,目前 SDK 不强制要求,留作未来按 mime 选模型扩展用

    Returns:
        转写出的文本(原始,未 strip)

    Raises:
        HTTPException 502: ASR 调用失败(网络 / 限流 / 配额等)
    """
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="openai 库未安装") from exc

    client = OpenAI()
    try:
        resp = client.audio.transcriptions.create(
            model="whisper-1",
            file=(io.BytesIO(audio_bytes), "audio.webm"),
        )
    except Exception as exc:
        # 捕获所有 SDK 异常(网络/认证/限流/无效音频等)统一映射 502
        logger.warning("Whisper 调用失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"ASR 调用失败: {exc}") from exc
    return resp.text


@router.post("")
async def transcribe(audio: UploadFile = File(...)) -> dict:
    """接收 multipart 音频 → 转写 → 返纯文本。

    调度优先级:
    1. 测试注入的 ``_call_whisper_fn``(存在则无视 env,直接调注入函数)
    2. ``OPENAI_API_KEY`` env 存在 → 调真 Whisper API
    3. fallback → mock 文本

    WHY bytes 直接读:webm blob 一般几 KB ~ 几 MB,内存一次性吃下没问题;
    超过 25MB 已经在前面拦掉。流式处理会引入异步复杂度而收益小。
    """
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="empty audio payload")
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"audio too large (>{MAX_AUDIO_BYTES // 1024 // 1024}MB)",
        )
    mime = audio.content_type or "audio/webm"

    # 1. 注入函数(测试用)
    if _call_whisper_fn is not None:
        try:
            text = _call_whisper_fn(audio_bytes, mime)
        except Exception as exc:
            logger.warning("注入 ASR 函数失败: %s", exc, exc_info=True)
            raise HTTPException(status_code=502, detail=f"ASR 调用失败: {exc}") from exc
        return {"text": text.strip()}

    # 2. 真 Whisper(有 key)
    if os.environ.get("OPENAI_API_KEY"):
        return {"text": _call_whisper(audio_bytes, mime).strip()}

    # 3. mock fallback
    return {"text": MOCK_TEXT}
