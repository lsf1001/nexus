"""事实校验硬约束 —— 注入到 ``dynamic_identity_middleware`` 的 system prompt 中间。

WHY 存在 (Task 16, 2026-07-11):
  LLM 已经持有 4 个工具 (``today`` / ``weekday_of`` / ``next_n_days`` /
  ``verify_claims``,由 T15 接入),并且 ``fact_check`` middleware 已经 fail-closed
  拦截不合格的事实输出(T9/T10)。但**两层都是被动防御**:LLM 输出后才
  fail-closed,既浪费一次往返又可能让用户先看到坏答案再被拦。

  本模块给 system prompt 注入**主动防御**显式约束,让 LLM 在生成 token
  前主动调工具,典型场景:
    - 「明天是哪天」→ 先调 ``today``,再算偏移,**严禁**心算 mod 7。
    - 「100 USD 等多少 CNY」→ 先调 ``verify_claims``,失败时改口不确定。
    - 「45 + 67 是多少」→ 必须能 ``verify_claims`` 通过。

设计取舍:
  - **Python 常量 + 模板渲染函数**而非裸字符串拼接,与
    ``identity.directives.render_fact_block`` 同款模式。
  - 工具名直接出现在约束里,LLM 一眼能识别要调谁。
  - 中文为主(产品调性),工具名保持 ASCII 以便 LLM 严格匹配
    tool registry 的 function name。
  - **不**注入 ``banned_examples`` 之类的反例(那样会让 LLM 思路被污染,
    反例从 prompt 进入不一定能压住训练记忆 bias)—— 只给正向硬约束。

注入位置:
  ``dynamic_identity_middleware`` 在三明治结构
  ``FACT 块 + static prompt + FINAL REMINDER`` 中插入本约束:

    FACT_BLOCK  (top, 模型身份)
      ↓
    FACT_CHECK_CONSTRAINT  (middle-top, 事实校验工具强约束,本模块)
      ↓
    static_prompt (middle, Nexus 静态产品规则)
      ↓
    FINAL_REMINDER (bottom, 身份自报硬约束)

  这样 LLM 决策轨迹里:看到 FACT 块知道「我是 Nexus + 当前驱动模型」 →
  看到 FACT_CHECK_CONSTRAINT 知道「先调工具再写输出」 → 再看 static
  prompt 兜底产品规则 → FINAL REMINDER 兜底身份自报。
"""

from __future__ import annotations

# 模板字符串 —— 全部硬编码中文 prose,无 .format() 占位符(约束不依赖运行时变量)。
# WHY 无占位符:本约束跨会话跨用户一致,无任何 per-call 动态成分;若未来需注入
# 用户级 AGENTS.md 的扩展段,改用 {home_agents_extras} 占位符 + render 时再 format。
FACT_CHECK_CONSTRAINT: str = """\
【FACT_CHECK_CONSTRAINT · 事实校验硬约束 · 必读】

以下四类事实性输出**必须**在写入回复前调用工具验证,工具未调用直接写的输出
会被 ``FactCheckMiddleware`` fail-closed 拦截(已实测,2026-07-11)：

1. **日期 / 星期**：任何「明天 / 后天 / 下周一 / 2026-07-15 是星期几」必须
   先调 ``today()`` 拿当前日期(Asia/Shanghai),再调 ``weekday_of(date_str)``
   算目标日期的星期。**严禁**心算 mod 7 估算星期。

2. **相对日期列表**：「接下来 N 天有哪几天」必须调 ``next_n_days(start_date, n)``,
   拿 JSON 列表后再生成回答,**严禁**逐日心算。

3. **数学计算**:任何加减乘除 / 百分比 / 复利表达式(如「45 + 67」「12% * 850」)
   在写入回复前必须被 ``verify_claims(text)`` 校验通过(返回 ok:true)才发出。

4. **汇率 / 单位换算**：「100 USD = 700 CNY」「5 公斤等于多少磅」必须先调
   ``verify_claims(text)`` 校验;工具返回失败/不确定时,改口为「汇率 / 换算
   我不确定,请查实时牌价」,**严禁**猜一个看似合理的数字。

【工具清单 · 调用方式 · 失败兜底】

- ``today()`` → 返回 ``"YYYY-MM-DD"``(Asia/Shanghai 时区)
- ``weekday_of(date_str: str)`` → 把 ``YYYY-MM-DD`` 转中文星期(一/二/.../日)
- ``next_n_days(start_date: str, n: int)`` → 返回接下来 N 天 JSON 列表
- ``verify_claims(text: str)`` → 扫文本中事实声明,返回 ``{ok: bool, ...}``

【兜底原则 · 永远比「快」重要】

合规优先于速度。工具调用比心算多一次 token 不影响正确性;心算错了被 fail-closed
拦下反而浪费一整轮对话。**宁可多调一次工具,绝不凭印象写数字 / 星期 / 日期。**
"""


def render_fact_check_constraint() -> str:
    """返回 FACT_CHECK_CONSTRAINT 完整字符串。

    与 ``identity.directives.render_fact_block`` 的同名函数保持 API 形
    式一致 —— 三明治结构里每个层都是「render_*() → str」,便于
    ``dynamic_identity_middleware`` 顺序拼接,且测试可独立断言每段内容。
    """
    return FACT_CHECK_CONSTRAINT
