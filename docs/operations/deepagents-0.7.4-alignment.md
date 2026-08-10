# DeepAgents 0.7.4 升级对齐报告

> **目的**:记录 Nexus 从 deepagents 0.6.12 升级到 0.7.4 的 API drift、修复点、
> 回归验证矩阵,作为后续 0.7.x / 0.8 升级的基线。
>
> **环境**:deepagents `0.7.4`、langchain `1.3.14`、langchain-core `1.5.3`、
> langsmith `0.10.15`(2026-08-05 安装实测)。
>
> **前置报告**:`docs/operations/deepagents-0.6.12-alignment.md`(已废弃,本文
> 件取代)。

## 1. 总览

| 维度 | 0.6.12 行为 | 0.7.4 行为 | Nexus 影响 | 修复点 |
| --- | --- | --- | --- | --- |
| `StoreBackend.__init__` | `namespace` optional | `namespace` 必填 keyword-only `Callable[[Runtime], tuple[str, ...]]` | `/memories/` 路由构造 `TypeError` | `_backend.py` 加 `_memory_namespace` factory |
| `FilesystemMiddleware` 写工具集 | `edit_file` / `write_file` / `str_replace_editor` | 增加 `delete` 工具(字面名,**不是** `delete_file`) | `PathAwareHITLMiddleware` 未识别 `delete` → HITL 静默跳过 → LLM 删源码不弹窗 | `FILE_TOOLS` 白名单加 `delete`,`WRITE_TOOL_PATTERNS` 兜底 `_file` 模式已自动覆盖 |
| `HarnessProfile` 字段集 | 7 字段 | 7 字段(未变) | 零 | 零 |
| `GeneralPurposeSubagentProfile` 字段集 | 3 字段 | 3 字段(未变) | 零 | 零 |
| `create_deep_agent()` 18 个参数 | 16 个 | 18 个(实际 `inspect.signature` 仍是 16,LangChain 1.x 加了 cache 但 deepagents 0.7.4 未引入新 kw) | 零 | 零 |
| `SubAgent` / `CompiledSubAgent` / `AsyncSubAgent` TypedDict | required 固定 | required 固定(未变) | 零 | 零 |
| `AsyncSubAgent.url` | optional | optional(未变) | 零 | 零 |
| `MemoryMiddleware` 自动加载 `AGENTS.md` | ✅ | ✅(未变) | 零 | 零 |
| `FilesystemMiddleware` × `FilesystemPermission` × execution backend 互斥 | ✅ | ✅(未变) | 零 | 零 |

**结论:Nexus 在 0.7.4 下兼容,3 处 drift 全部修复,无新增 drift。**

## 2. 三处 drift 的根因与修复

### 2.1 `StoreBackend.__init__` 强制要求 `namespace`

**根因**(deepagents 0.7.0 起):

```python
# deepagents 0.7.4 backends/store.py
class StoreBackend:
    def __init__(
        self,
        store: BaseStore,
        *,
        namespace: Callable[[Runtime], tuple[str, ...]],  # 0.6 optional → 0.7 required
    ): ...
```

`namespace` 是 keyword-only callable,签名 `Callable[[Runtime], tuple[str, ...]]`,
**0.7.0 起抛 `TypeError: missing 1 required keyword-only argument: 'namespace'`**。

**Nexus 修复**(`nexus/backend/agent/_backend.py:136-148`):

```python
if store is not None:
    # deepagents 0.7.0 起 StoreBackend 强制要求 namespace callable
    # (签名 Callable[[Runtime], tuple[str, ...]]),返回 tuple 给 store
    # key 加前缀隔离 — 不传会抛 TypeError: missing 'namespace'。
    # WHY 固定 ("memories",):Nexus 是单用户个人助理,/memories/
    # 路由下的所有 key 在同一 namespace 足以;thread 隔离由 langgraph
    # store 的内置 key 完成。Runtime 在 Nexus 这层不可达(仅 deepagents
    # 内部 graph runtime),所以 factory 忽略参数,直接返回固定 tuple。
    def _memory_namespace(_runtime: Any) -> tuple[str, ...]:
        return ("memories",)
    routes["/memories/"] = StoreBackend(namespace=_memory_namespace, store=store)
```

**为什么不按 thread_id 命名空间隔离**:

Nexus 是单用户个人助理,所有对话属于同一用户;`/memories/` 是 LLM 跨会话
持久记忆(如用户偏好),不放跨用户隔离。thread 隔离由 langgraph store 内置
key(`AsyncSqliteStore` 把 thread_id 编进 put/get)完成,不需要 namespace 再
分一层。Runtime 参数在 Nexus 这层不可达(仅 deepagents 内部 graph runtime),
所以 factory 忽略参数。

### 2.2 `delete` 工具未防护

**根因**(deepagents 0.7.0 起):

`FilesystemMiddleware._FS_TOOL_ORDER` 注册的工具名顺序:

```
("ls", "read_file", "write_file", "edit_file", "delete", "glob", "grep")
```

**实测 0.7.4 工具注册的 `tool.name == "delete"`**(不是 `delete_file`)。
LLM 现在能调 `delete` 删任意路径,而 `nexus/backend/permissions/write_tools.py`
的 `FILE_TOOLS` 精确白名单 + `WRITE_TOOL_PATTERNS` 兜底模式都不识别
字面 `"delete"` → `is_write_tool("delete")` 之前返回 `False` → HITL 静默
跳过 → LLM 删项目源码不再触发确认弹窗。

**Nexus 修复**(`nexus/backend/permissions/write_tools.py:29-40`):

```python
FILE_TOOLS: frozenset[str] = frozenset(
    {
        "edit_file",
        "write_file",
        "delete",                # ← 0.7.0 新增,文件/目录删除,核心写工具
        "create_file",
        "apply_patch",
        "patch_file",
        "str_replace_editor",
        "write_document",
    }
)
```

**双层防护**:

- `FILE_TOOLS` 精确白名单覆盖 0.7.4 当前字面名 `"delete"`
- `WRITE_TOOL_PATTERNS` 含 `"_file"` 子串,未来若 deepagents 改名
  `delete_file` 自动覆盖
- `READ_ONLY_TOOLS` 排除 `read_file` 等只读工具,即使含 `_file` 子串

**回归测试**(`tests/test_write_tools_helper.py:108-131`):

锁定三个事实,防止有人误删 `delete` 后 HITL 静默失效:

```python
assert is_write_tool("delete") is True            # 0.7.4 当前
assert is_write_tool("delete_file") is True       # 未来若改名
assert is_write_tool("remove_file") is True       # 子串兜底
```

### 2.3 `HarnessProfile.materialize_extra_middleware` 签名风险

**前置报告 §6 TODO 2** 预测:`extra_middleware` callable 签名 0.7 可能变。

**实测 0.7.4**:Nexus 未使用 `extra_middleware` 字段(只在 `HarnessProfile` 7
字段中用了 `system_prompt_suffix` 一个),**0.7.4 callable 签名变 / 不变都不
影响 Nexus**。如果未来想用,需重新对齐 `tests/test_deepagents_integration.py`
的 `test_harness_profile_field_set_matches_deepagents_0_7_4` 基线。

## 3. 配套依赖升级

| 包 | 0.6.12 时期 | 0.7.4 要求 | pyproject.toml |
| --- | --- | --- | --- |
| `deepagents` | `>=0.6.0` | `>=0.7.0,<0.8.0` | ✅ |
| `langchain` | 隐式依赖 | `>=1.3.14,<2.0.0` | ✅ 显式声明 |
| `langchain-core` | 隐式依赖 | `>=1.5.0,<2.0.0` | ✅ 显式声明 |
| `langsmith` | 隐式依赖 | `>=0.10.9` | ✅ 显式声明 |
| `langchain-openai` | `>=1.0.0` | `>=1.0.0` | ✅ 未变 |
| `langchain-community` | `>=0.0.20` | `>=0.0.20` | ✅ 未变 |

**WHY 显式声明 langchain / langchain-core / langsmith 下限**:0.7 在 venv
`pip install -e .` 时不会自动装到满足 `Requires-Dist` 的版本,会导致
import 时 `ModuleNotFoundError` 或 API 漂移。补三个下限 + 上限避免漂到 2.x。

## 4. 验证矩阵

```bash
# 安装验证
source .venv/bin/activate
python -c "import deepagents, langchain, langchain_core, langsmith; \
  print(f'{deepagents.__version__=} {langchain.__version__=} \
{langchain_core.__version__=} {langsmith.__version__=}')"
# 期望 deepagents=0.7.4 langchain=1.3.14 langchain-core=1.5.3 langsmith=0.10.15

# pytest 全量
pytest tests/ -q --tb=line
# 期望 1004 passed, 12 skipped, 0 failed(2026-08-05 实测)

# ruff check
ruff check nexus/ tests/
# 期望 All checks passed!

# 字段基线(0.6 → 0.7 字段集未变,基线仍生效)
pytest tests/test_deepagents_integration.py::TestProfiles -v
# 期望 4/4 PASS
```

## 5. 后续升级 TODO

| # | 项 | 文件 | 工作量 | 优先级 |
| --- | --- | --- | --- | --- |
| 1 | 真 LLM E2E 验 `delete` 工具触发 HITL 拦截(需 API key,本轮用 mock 验证了字段层) | `e2e/journey-*.spec.ts` | 2h | 中 |
| 2 | `HarnessProfile.general_purpose_subagent` 槽空了,评估是否接回自定 profile | `nexus/backend/profiles/tier_routing.py` | 1h | 低 |
| 3 | `delete_directory` 子串模式未来若 deepagents 新增目录删除工具,需补 `_dir` / `_directory` 子串 | `nexus/backend/permissions/write_tools.py` | 0.5h | 低 |

---

**总结**:0.6.12 → 0.7.4 升级仅触及 `StoreBackend.namespace`(必填)+ `delete`
工具(HITL 路由)两点;字段级 API drift 零。`HarnessProfile` / TypedDict /
`create_deep_agent` 签名 0.7 沿用 0.6,基线测试零修改通过。
