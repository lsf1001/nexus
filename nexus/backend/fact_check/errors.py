"""fact_check 自定义异常。"""


class VerifierError(Exception):
    """verifier 校验失败(非 conflict,纯错误)。

    与 ``VerificationResult.verdict == "conflict"`` 区分:verdict="conflict"
    是业务结果(声明有误),``VerifierError`` 是 verifier 自身故障(IO / 解析 /
    依赖不可用等),应当被 ``verify()`` 统一入口静默跳过,不阻断主流程。
    """
