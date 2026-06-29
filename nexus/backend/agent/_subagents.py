"""SubAgent 工厂:内置 subagent + env-gated AsyncSubAgent / CompiledSubAgent。

模块化拆分后,本模块集中承载:

- :func:`build_interrupt_on_for_agent` — 已废弃的空签名(保留向后兼容)
- :func:`create_subagents` — 主入口,组合内置 + env-gated 子代理
- :func:`_load_compiled_subagent_specs` — 从 env ``NEXUS_COMPILED_SUBAGENTS_JSON``
  读 JSON,转成 ``CompiledSubAgent`` 列表(用户可注入任意 Runnable)
- :func:`_load_async_subagent_specs` — 从 env ``NEXUS_ASYNC_SUBAGENTS_JSON``
  读 JSON,转成 ``AsyncSubAgent`` 列表(连远程 Agent Protocol 服务器)

WHY 单独成包:subagent 装配是 deepagents 框架最容易被外部 env 配置
污染的地方,集中一个文件便于:
  1. 把"必装"内置 subagent 与"可选" env-gated subagent 显式分层
  2. 单条坏配置只影响该 spec,不影响整个 create_agent
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

logger = __import__("logging").getLogger(__name__)


def build_interrupt_on_for_agent(project_root: Path) -> None:
    """(已废弃,2026-06-24 删除具体逻辑)。

    原实现手动构造 ``interrupt_on`` 的 ``when`` 谓词试图对"未在白名单的路径
    触发 HITL"。E2E 实测发现该实现与 deepagents 0.6.8 内部的
    ``_make_exact_when_predicate`` 语义错位 — 后者直接调 ``_check_fs_permission``,
    而手动版用 regex 白名单匹配,后者在 macOS symlink 等场景下漏判,导致
    "LLM 写项目源码未触发 HITL"。修复:把项目源码目录加入
    ``FilesystemPermission`` 的 ``mode="interrupt"`` rules,让 deepagents
    自动从 permissions 生成 ``interrupt_on``(语义最权威)。

    本函数保留为空签名(返回 ``None``)以兼容历史调用方;``create_agent``
    """
    return None


def _load_compiled_subagent_specs() -> list[Any]:
    """从 env 读取 CompiledSubAgent 配置(JSON),返回 :class:`CompiledSubAgent` 列表。

    WHY 不默认启用:CompiledSubAgent 接受任意 ``Runnable``,用户必须保证:
      - runnable 的 state schema 含 ``messages`` 键(框架硬要求)
      - ``runnable.invoke({...})`` 能跑通(无 import 错误 / 无依赖缺失)

    JSON 字段(对应 :class:`deepagents.CompiledSubAgent`):
      - ``name`` (必填):subagent 唯一标识
      - ``description`` (必填):主代理看到的描述
      - ``module_path`` (必填):Python 模块路径,如 ``nexus.backend.my_agent``
      - ``factory`` (必填):模块内的可调用名(返回 ``Runnable``)

    加载失败时记 warning + 跳过该条;不让单条坏配置炸整个 ``create_agent``。

    返回空列表 = 不附加 CompiledSubAgent,等价于只跑内置 SubAgent。
    """
    import importlib
    import json as _json
    import os as _os

    from deepagents.middleware.subagents import CompiledSubAgent

    raw = _os.environ.get("NEXUS_COMPILED_SUBAGENTS_JSON")
    if not raw:
        return []

    try:
        specs_raw = _json.loads(raw)
    except _json.JSONDecodeError as exc:
        logger.warning("NEXUS_COMPILED_SUBAGENTS_JSON 解析失败,已忽略: %s", exc)
        return []

    if not isinstance(specs_raw, list):
        logger.warning("NEXUS_COMPILED_SUBAGENTS_JSON 必须是 JSON 数组,实际 %s", type(specs_raw).__name__)
        return []

    result: list[Any] = []
    for entry in specs_raw:
        if not isinstance(entry, dict):
            logger.warning("CompiledSubAgent 配置项必须是 dict,跳过: %r", entry)
            continue
        required = {"name", "description", "module_path", "factory"}
        missing = required - set(entry.keys())
        if missing:
            logger.warning("CompiledSubAgent 缺字段 %s,跳过: %r", missing, entry)
            continue

        try:
            mod = importlib.import_module(str(entry["module_path"]))
            factory = getattr(mod, str(entry["factory"]))
            runnable = factory()
        except (ImportError, AttributeError, TypeError, ValueError) as exc:
            # ImportError:module 不存在;AttributeError:factory 名不存在;
            # TypeError:factory 调用方式错(比如需要参数);ValueError:用户 factory 自己抛
            logger.warning(
                "CompiledSubAgent 加载失败(%s.%s): %s",
                entry["module_path"],
                entry["factory"],
                exc,
            )
            continue

        spec: CompiledSubAgent = {  # type: ignore[typeddict-item]
            "name": str(entry["name"]),
            "description": str(entry["description"]),
            "runnable": runnable,
        }
        result.append(spec)
        logger.info("CompiledSubAgent 已加载: %s -> %s.%s", entry["name"], entry["module_path"], entry["factory"])

    return result


def _load_async_subagent_specs() -> list[Any]:
    """从 env 读取 AsyncSubAgent 配置(JSON),返回 :class:`AsyncSubAgent` 列表。

    WHY 不默认启用:AsyncSubAgent 走 LangGraph SDK 连远程 Agent Protocol
    服务器,需要 ``LANGGRAPH_API_KEY`` / 自托管 URL / headers 等额外配置。
    没这些就跑不起来。

    JSON 字段(对应 :class:`deepagents.AsyncSubAgent`):
      - ``name`` (必填):subagent 唯一标识
      - ``description`` (必填):主代理看到的描述
      - ``url`` (可选):Agent Protocol server URL;缺省走 LangGraph Platform
      - ``headers`` (可选 dict):自托管鉴权 headers

    返回空列表 = 不附加 AsyncSubAgent,等价于只跑 sync SubAgent。
    """
    import json as _json
    import os as _os

    raw = _os.environ.get("NEXUS_ASYNC_SUBAGENTS_JSON")
    if not raw:
        return []

    try:
        specs_raw = _json.loads(raw)
    except _json.JSONDecodeError as exc:
        logger.warning("NEXUS_ASYNC_SUBAGENTS_JSON 解析失败,已忽略: %s", exc)
        return []

    if not isinstance(specs_raw, list):
        logger.warning("NEXUS_ASYNC_SUBAGENTS_JSON 必须是 JSON 数组,实际 %s", type(specs_raw).__name__)
        return []

    from deepagents.middleware.async_subagents import AsyncSubAgent

    result: list[Any] = []
    for entry in specs_raw:
        if not isinstance(entry, dict):
            logger.warning("AsyncSubAgent 配置项必须是 dict,跳过: %r", entry)
            continue
        if "name" not in entry or "description" not in entry:
            logger.warning("AsyncSubAgent 缺 name/description,跳过: %r", entry)
            continue
        # TypedDict 接受任何 dict,字段缺失会在运行时炸 — 这里先做基本校验
        spec: AsyncSubAgent = {  # type: ignore[typeddict-item]
            "name": str(entry["name"]),
            "description": str(entry["description"]),
        }
        if "url" in entry:
            spec["url"] = str(entry["url"])
        if "headers" in entry and isinstance(entry["headers"], dict):
            spec["headers"] = {str(k): str(v) for k, v in entry["headers"].items()}
        result.append(spec)
    return result


def create_subagents(model=None):
    """创建子代理列表。

    每个 subagent 的"重试 + 超时"策略以**文字提示**形式嵌入 system prompt
    (而非 LLM 参数)——因为 subagent 内的工具调用本身有自己的超时机制,
    LLM 层的策略覆盖不到工具调用。约定如下:
      - ``code_writer``: 单次任务上限 300s,max_retries=0(工具失败应直接报告,
        盲目重写代码反而会引入新错误)。
      - ``researcher``: 单次任务上限 120s,max_retries=2(网络瞬时错误可安全
        重试;鉴权/上下文错误不应重试)。

    Args:
        model: 可选的 LLM 实例;如果不提供则使用 CONFIG 中的默认模型
            (CONFIG 也没 API key 时 ``model=None``,subagent 仅承载提示词
            和描述,由调用方决定是否注入模型)。

    Returns:
        :class:`SubAgent` 列表,包含 ``code_writer`` 与 ``researcher``。

        + 可选的 :class:`AsyncSubAgent` 配置(从环境变量 ``NEXUS_ASYNC_SUBAGENTS_JSON``
        读取,JSON 数组格式)。没配就不返回 — AsyncSubAgent 需要外部 Agent Protocol
        服务器,空配置不会误启用。
    """
    from ..config import CONFIG
    from ..tools import TOOLS
    from ._llm_factory import get_llm

    # 如果没有提供模型且 CONFIG 中也没有 API key,跳过工具
    use_tools = model is not None or CONFIG.get("minimax_api_key")

    code_writer_prompt = (
        "你是一个专业的 Python 代码助手,负责编写高质量、生产级别的代码。\n\n"
        "【重试策略】本 agent 内的工具调用最多 0 次重试,超时上限 300 秒。\n"
        "工具失败应直接报告,不要盲目重试或自行改写代码;"
        "代码错误请把上下文交回主流程让用户决策。"
    )

    researcher_prompt = (
        "你是一个专业的研究分析助手,负责搜索和分析信息。\n\n"
        "【重试策略】本 agent 内的工具调用最多 2 次重试,超时上限 120 秒。\n"
        "网络瞬时错误(超时、5xx、限流)可以安全重试;"
        "鉴权失败、参数错误、上下文超长等错误不要重试,应原样向上报告。"
    )

    from deepagents.middleware.subagents import SubAgent

    # subagent 工具集: 显式限定为 ask_user + get_current_date。
    # 文件操作(ls/read_file/write_file/edit_file/glob/grep)由 FilesystemMiddleware
    # 注入到主 agent,subagent 通过 SubAgentMiddleware 自动继承,不在这里重复。
    # 移除原 "execute" 死引用(tools.py 未注册该工具)。
    code_writer = SubAgent(
        name="code_writer",
        model=model or get_llm(model_name=CONFIG["model_name"]) if use_tools else None,
        tools=[t for t in TOOLS if t.name in {"ask_user", "get_current_date"}] if use_tools else [],
        system_prompt=code_writer_prompt,
        description="代码编写专家",
    )

    researcher = SubAgent(
        name="researcher",
        model=model or get_llm(model_name=CONFIG["model_name"]) if use_tools else None,
        tools=[t for t in TOOLS if t.name in ("web_search", "browse")] if use_tools else [],
        system_prompt=researcher_prompt,
        description="研究分析专家",
    )

    result: list[Any] = [code_writer, researcher]

    # ------------------------------------------------------------------
    # AsyncSubAgent 可选集成(env-gated)
    # ------------------------------------------------------------------
    # WHY env-gated:AsyncSubAgent 需要一个跑 Agent Protocol 的远程服务器
    # (LangGraph Platform 自托管或托管版)。没配服务器就启用会直接报错。
    # 配置方式:``NEXUS_ASYNC_SUBAGENTS_JSON='[{"name":"x","description":"...",
    # "url":"https://..."}]'``。
    async_specs = _load_async_subagent_specs()
    result.extend(async_specs)

    # ------------------------------------------------------------------
    # CompiledSubAgent 可选集成(env-gated)
    # ------------------------------------------------------------------
    # WHY env-gated:CompiledSubAgent 让用户塞任意 ``langchain_core.runnables.
    # Runnable`` 进来(预编译的子图 / LangChain ``create_agent`` 实例 / 自定义
    # graph)。需要保证 runnable 的 state schema 含 ``messages`` 键(框架要求,
    # 否则结果回不来)。配置不当 = 启动失败 / 运行时炸,默认不启用。
    # 配置方式:``NEXUS_COMPILED_SUBAGENTS_JSON='[{"name":"x","description":"...",
    # "module_path":"my_pkg.my_module","factory":"build_my_agent"}]'``。
    # ``factory`` 是 module 内的可调用,返回 ``Runnable`` 实例。
    compiled_specs = _load_compiled_subagent_specs()
    result.extend(compiled_specs)

    return result
