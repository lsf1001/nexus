from __future__ import annotations

from typing import Literal

"""回复风格常量 + system prompt 段模板。

WHY 单独 module 不放 agent/：
- 跟 _system_prompt.py 解耦；3 套文案集中维护
- pytest tests/test_styles.py 可独立覆盖，无需 mock deepagents
- 未来加新风格只改这里一处，不会跨多文件

风格段是「非默认风格」时附加到 system prompt 末尾的指令段，
引导 LLM 按目标风格生成。**注入方式**见 _system_prompt._build_system_prompt：
在 parts list 末尾按 style 参数 append。
"""

StyleOption = Literal["default", "concise", "professional"]
VALID_STYLES: tuple[StyleOption, ...] = ("default", "concise", "professional")

# 文案遵循 system prompt 既有语气（中文，「请」开头，明确禁止行为）
STYLE_DIRECTIVES: dict[StyleOption, str] = {
    "default": "",  # 空串，不附加
    "concise": (
        "【回复风格 · 简洁】\n"
        "本条回复必须采用简洁风格：\n"
        "- 直接给答案，不寒暄、不铺陈、不复述问题\n"
        "- 单段不超过 3 句；超过则用 1 行短列表\n"
        "- 砍掉所有「希望对你有帮助」/「如有疑问请告诉我」类收尾"
    ),
    "professional": (
        "【回复风格 · 专业】\n"
        "本条回复必须采用专业风格：\n"
        "- 用词严谨、精准，避免口语化词汇（「挺」、「蛮」、「差不多」）\n"
        "- 涉及事实给出依据（出处 / 公式 / 代码示例），不给空泛结论\n"
        "- 结构化输出优先：列表 + 小标题，避免大段散文\n"
        "- 末尾不加情感化收尾语"
    ),
}


def get_style_directive(style: str) -> str:
    """获取风格指令段。未知 style 或 'default' 返回空串。

    Args:
        style: 任意字符串；合法值是 'default' / 'concise' / 'professional'。

    Returns:
        对应风格的指令段；未知 / 'default' 返回空串。
    """
    return STYLE_DIRECTIVES.get(style, "")  # type: ignore[arg-type]
