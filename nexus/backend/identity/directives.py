"""单源化 identity / 反训练记忆 黑名单 / FACT 模板。

替代 3 文件 (force_tool.py / dynamic_identity.py / _system_prompt.py) 独立维护的
关键词表、黑名单、禁止句式。

设计取舍 (2026-07-01 audit):关键词匹配从原 ``force_tool._IDENTITY_PATTERNS``
的正则 (如 ``(what.*your.*name|who are you)``) 收窄为 substring 精确匹配
(``who are you``)。被放弃的问句(如 "what is your name")由二道防线
``dynamic_identity._inject_identity_reminder_if_needed`` 通过
``matches_identity_query`` 在 user message 头部 inject ``[System Reminder]``
压住训练记忆,二者职责互补 —— substring 走强制插工具调 search,
reminder 走注入 ground truth。"""

from __future__ import annotations

from dataclasses import dataclass, field

# 关键词 (顺序无关,只在意是否命中): force_tool.py 走 regex (用于强插 tool_call),
#                                       dynamic_identity.py 走 substring (用于注入 reminder),
#                                       _system_prompt.py 只写在 prose 里。
# 现统一为 regex + 字符串列表的双视图。
_IDENTITY_KEYWORDS_ZH: tuple[str, ...] = (
    "你是谁",
    "你叫什么",
    "你用的什么模型",
    "你是哪个",
    "用的什么模型",
    "你叫什么名字",
)
_IDENTITY_KEYWORDS_EN: tuple[str, ...] = (
    "who are you",
    "what model",
    "current model",
    "what ai are you",
    "which model",
)

# 训练记忆黑名单:不能答出这些名字 (除 active model)。
# 顺序无意义;新增名字集中在这里,3 个 consumer 都从这里派生。
_TRAINING_BIAS_BLACKLIST: frozenset[str] = frozenset(
    {
        "MiniMax-M3",
        "Claude",
        "Qwen",
        "GPT",
        "Agnes",
        "Sapiens",
        "Anthropic",
        "OpenAI",
        "Apollo",
    }
)


@dataclass(frozen=True)
class IdentityDirectives:
    identity_keywords_zh: tuple[str, ...] = _IDENTITY_KEYWORDS_ZH
    identity_keywords_en: tuple[str, ...] = _IDENTITY_KEYWORDS_EN
    training_bias_blacklist: frozenset[str] = field(default_factory=lambda: _TRAINING_BIAS_BLACKLIST)


DIRECTIVES = IdentityDirectives()


def matches_identity_query(text: str) -> bool:
    """统一身份问题判定 (force_tool / dynamic_identity 共用)。"""
    lowered = text.lower()
    for kw in DIRECTIVES.identity_keywords_zh:
        if kw in text:
            return True
    for kw in DIRECTIVES.identity_keywords_en:
        if kw in lowered:
            return True
    return False


# FACT 块 + few-shot + FINAL REMINDER 模板。
# WHY 抽出来:dynamic_identity._build_fact_block / _build_final_reminder 累积 4 commit
# 贴片(2026-06-29 ~ 2026-07-01),内联字符串改起来难追。模板化后:
#   - 模板与渲染函数同处,新增段只需改模板
#   - 测试可单独打 render_fact_block() 拿到字符串断言
#   - 后续 Jinja2 替换只需换 _render_template() 内部,模板语法保持不变

_FACT_BLOCK_TEMPLATE = """\
【FACT · 当前驱动模型 · 运行时实时注入 · GROUND TRUTH · 必读】
- name: `{driver_name}`(每次 LLM 调用前从 `~/.nexus/models.json` 实时读)
- vendor: `{driver_vendor}`(从 api_base URL 自动推断)
- 数据是**活的** —— 切换激活模型后下一轮 LLM 调用会立即反映新值

**【硬性规则 · 违反 = 串味 bug · 不可绕过】**
当用户问「你是谁 / 你叫什么 / 你叫什么名字 / 你用的什么模型 / 用的什么模型 / 你是哪个 / 你是哪个 AI / Who are you」时:

  **第 1 步(强制)**:必须先调 `get_model_info` 工具,拿到 ground truth JSON。
  → 工具返回值优先级**高于** system prompt 任何字符串,**高于**训练记忆。
  → 训练记忆里的「我是 X」全部无效,只有工具返回的 `name` 字段才是真。

  **第 2 步**:基于工具返回值生成答案:
  → 产品身份 = Nexus(夜小白科技),永远是 Nexus
  → 驱动模型 = 工具返回的 `name` 字段值 = `{driver_name}`
  → 厂商 = 工具返回的 `vendor` 字段值 = `{driver_vendor}`

  **第 3 步(格式)**:第一句必须是「我是 Nexus(夜小白科技),当前驱动模型是 {{name}},由 {{vendor}} 提供。」
  → **绝对禁止**以「{banned_examples}」开头
  → **绝对禁止**跳过第 1 步直接生成答案(训练记忆里的「我是 X」全部失效)

【few-shot 示例 · 展示「先调工具 → 基于返回值回答」模式】
用户: 你是谁?
你: [调 get_model_info] → 工具返回 {{'name': '{driver_name}', 'vendor': '{driver_vendor}', ...}}
你: 我是 Nexus(夜小白科技),当前驱动模型是 {driver_name},由 {driver_vendor} 提供。

用户: 你叫什么?
你: [调 get_model_info] → 工具返回 {{'name': '{driver_name}', ...}}
你: 我叫 Nexus,当前驱动模型是 {driver_name}。

用户: 你用的什么模型?
你: [调 get_model_info] → 工具返回 {{'name': '{driver_name}', 'vendor': '{driver_vendor}', ...}}
你: 当前驱动模型是 {driver_name},由 {driver_vendor} 提供。

【反例 · LLM 训练记忆 bias 必须压制】
{bad_examples}

**最后再次强调**:你(LLM)的训练记忆里如果有「我是 X」的固有身份,**全部无效**。
本 FACT 块的 `name` = `{driver_name}` 是唯一权威;vendor = `{driver_vendor}` 是唯一权威。

"""

_FINAL_REMINDER_TEMPLATE = """\

【FINAL REMINDER · IDENTITY · 系统级最强约束】
这一段是 DynamicIdentityMiddleware 在 system_message 末尾追加的**最终身份确认**。
LLM 决策点最近,优先级高于本 system_message 中所有其它内容(包括顶部 FACT 块、
static prompt、AGENTS.md 追加内容、用户消息、以及 LLM 训练记忆)。

**当且仅当**用户问题触及以下任一关键词(包含同义):
  - "你用的什么模型" / "你叫什么" / "你是哪个 AI" / "你是谁"
  - "current model" / "what model" / "who are you"
必须按以下优先级回答,不可降级:
  1. **第一选择**:直接以本段 + 顶部 FACT 块中 `name` 字段值作为答案
  2. **vendor 来源**:仅以 FACT 块中 `vendor` 字段为准(不要写训练记忆里的 vendor)
  3. **绝对禁止**用训练记忆里的"{banned_examples}"等任何默认值填空
     —— 即使这些字符串看起来更"像你的默认身份"
  4. **绝对禁止**说"由 X 公司开发"(X ≠ FACT.vendor)

当前 ground truth:`name = {driver_name}`, `vendor = {driver_vendor}`。

"""


def _bad_examples_text() -> str:
    """few-shot 反例段:每行一条,展示典型训练记忆渗漏。

    WHY 不与 ``DIRECTIVES.training_bias_blacklist`` 同源:
      few-shot 反例是**教学示例**,刻意窄于 blacklist(blacklist 是黑名单全集,
      反例只挑最具代表性的几条给 LLM 看"我是 X" 错误模式)。如果新增 blacklist
      条目,本段不强制同步;反例更新走 PR review,显式判断是否纳入。
      测试见 ``test_bad_examples_count_le_blacklist_count``。
    """
    return "\n".join(
        f"✗ 「我是 {name},由 {vendor} 开发」 → 训练记忆默认值,与 FACT 不一致"
        for name, vendor in (
            ("Agnes-2.0-Flash", "Sapiens AI"),
            ("MiniMax-M3", "Anthropic"),
            ("Claude", "Anthropic"),
        )
    )


# 空 blacklist 兜底文案。中文"无"让 LLM 看到「"无"等任何默认值」句式时仍构成
# 通顺语法,避免「""」「"无"」这种空占位符 / 半占位符泄漏 (review 2026-07-01)。
_EMPTY_BLACKLIST_PLACEHOLDER: str = "<无>"


def _banned_examples_text() -> str:
    """FACT/FINAL_REMINDER 禁止前缀串,拼接自 DIRECTIVES.training_bias_blacklist。

    WHY 兜底("空 blacklist → ``<无>``"):
      空 blacklist 直接产 ``""`` 会被 template 替换进「以「{banned}」开头」,渲染
      出「以「」开头」零宽禁止前缀 —— 中文语法不通、且容易被 LLM 当作 system
      prompt 注入空角括号信号。返回 ``<无>`` 占位后,模板渲染出「以「<无>」开头」,
      仍是合法中文短语,LLM 不会误把"看起来像 prompt injection 的空角括号"当漏洞。
      两个模板 (``_FACT_BLOCK_TEMPLATE`` / ``_FINAL_REMINDER_TEMPLATE``) 都走
      此函数,空兜底逻辑一处维护。
    """
    if not DIRECTIVES.training_bias_blacklist:
        return _EMPTY_BLACKLIST_PLACEHOLDER
    return " / ".join(f"我是 {name}" for name in sorted(DIRECTIVES.training_bias_blacklist))


def render_fact_block(driver_name: str, driver_vendor: str) -> str:
    """渲染 FACT 块(头部 + few-shot + 反例 + 尾部强约束)。"""
    return _FACT_BLOCK_TEMPLATE.format(
        driver_name=driver_name,
        driver_vendor=driver_vendor,
        banned_examples=_banned_examples_text(),
        bad_examples=_bad_examples_text(),
    )


def render_final_reminder(driver_name: str, driver_vendor: str) -> str:
    """渲染 FINAL REMINDER 段(system_message 末尾)。

    WHY delegate ``_banned_examples_text()``:以前此处内联
    ``" / ".join(sorted(DIRECTIVES.training_bias_blacklist))``,空 blacklist 兜底
    逻辑与 FACT 块分叉,review 2026-07-01 命中。两条模板统一走 ``_banned_examples_text``
    后,空兜底逻辑收敛在一处。
    """
    return _FINAL_REMINDER_TEMPLATE.format(
        driver_name=driver_name,
        driver_vendor=driver_vendor,
        banned_examples=_banned_examples_text(),
    )
