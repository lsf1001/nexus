# DeepAgents 0.7.13 升级对齐报告

> **目的**:记录 Nexus 从 deepagents 0.7.6 跨 7 个补丁版本(0.7.7 → 0.7.13)升到
> 0.7.13 的 API drift、依赖变更、回归验证矩阵,作为后续 0.7.14 / 0.8 升级的
> 基线。
>
> **环境**:deepagents `0.7.13`(2026-09-02 实装,2026-09-11 pip 升级)、
> langchain `1.4.0`、langchain-core `1.6.3`、langsmith `0.12.5`。
>
> **前置报告**:
> - [`docs/operations/deepagents-0.7.4-alignment.md`](./deepagents-0.7.4-alignment.md)(2026-08-10)
> - [`docs/operations/deepagents-0.7.6-alignment.md`](./deepagents-0.7.6-alignment.md)(2026-08-14)
>
> 本文延续补丁升级报告惯例。

## 1. 总览

| 维度 | 0.7.6 行为 | 0.7.13 行为 | Nexus 影响 | 修复点 |
| --- | --- | --- | --- | --- |
| `FilesystemMiddleware._FS_TOOL_ORDER` | `("ls","read_file","write_file","edit_file","delete","glob","grep")` | **未变**(7 个补丁版本) | 零 | 基线锁测试改名 `_0_7_6 → _0_7_13`,断言体不动 |
| `_ALL_FS_TOOL_NAMES` | `{ls,read_file,write_file,edit_file,delete,glob,grep,execute}` | **未变** | 零 | 零 |
| `delete` 工具 `tool.name` | 字面 `"delete"` | 字面 `"delete"`(未变) | 零 | `FILE_TOOLS` 白名单继续覆盖 |
| `SubAgent` TypedDict `__required_keys__` | `{"name", "description", "system_prompt"}` | `{"name", "description"}`(`system_prompt` 7 补丁版本内降级为 optional) | 零(Nexus `create_subagents()` 仍显式传 system_prompt) | 基线锁测试改名 + 断言体更新 |
| `CompiledSubAgent` TypedDict `__required_keys__` | `{"name", "description", "runnable"}` | `{"name", "description", "runnable"}`(未变) | 零 | 零 |
| `AsyncSubAgent` TypedDict `__required_keys__` | `{"name", "description", "graph_id"}` | `{"name", "description", "graph_id"}`(未变) | 零 | 零 |
| `create_deep_agent` 签名 | `create_deep_agent(tools=..., middleware=..., ...)` | 未变 | 零 | 零 |
| `langchain.agents.middleware.AgentMiddleware` | 主路径 API | 未变(0.7.7-0.7.13 期间未触碰) | 零 | 零 |
| `langchain.agents.middleware.types` (`AgentState` / `ModelRequest` / `ModelResponse` / `ContextT` / `ResponseT`) | 主路径 API | 未变 | 零 | 零 |
| `langchain_core.{messages,tools,callbacks,language_models,outputs}` | 主路径 API | 未变 | 零 | 零 |
| `langchain-community` (DuckDuckGo / Wikipedia) | 主路径 API | 未变(0.7.7-0.7.13 未触碰 community 路径) | 零 | 零 |
| `langgraph-checkpoint-sqlite` | 区间 `>=2.0,<4.0` | 区间未变 | 零 | 零 |
| subagent `handoff` → `isolated` 重命名 (#6030, 0.7.13) | SDK 内部 subagent 调度路径字面值 | 改动 | **零**(`_subagents.py` grep 零命中 `handoff`) | 零 |
| subagent conversation forking (#5714, 0.7.12) | 默认关闭 | 新增可选 | 零(Nexus 未启用) | 零 |
| rubric grader hooks 集成 (#5874, 0.7.11) | SDK 内部 | 新增 | 零(注释提及,不直接 import) | 零 |
| TUI 输入冲突 + sandbox glob 失败透传 (#5873/#5566, 0.7.10) | CLI/TUI + sandbox 路径 | 修复 | 零(Nexus 服务端) | 零 |
| `excluded_tools` 生效 + RubricMiddleware 强覆盖 + execute timeout 语义 (0.7.9) | middleware 行为 | 调整 | 零(`tier_routing.py` 概念层引用,未直接调 API) | 零 |
| state backend `files` 字段 (#5643, 0.7.8) | SDK 内部 state backend | 新增 | 零(Nexus 用 `CompositeBackend`) | 零 |
| `BackendProtocol.glob` bare pattern 递归 + ContextHubBackend 并发批处理 (0.7.7) | SDK 内部 backend 协议 | 改进 | 零(Nexus `_backend.py` 懒 import) | 零 |

**结论:Nexus 在 0.7.13 下兼容,7 个补丁版本的全部改动均与 Nexus 接口层(HITL /
MemoryFilter / QualityGateMiddleware / 文件工具白名单 / 中间件签名)无交集;
无新增修复;`pyproject.toml` 仅收紧 3 个 langchain/langchain-core/langsmith
下限(对齐 deepagents 0.7.13 Requires-Dist),无新硬依赖引入。**

## 2. 复核结论(delete 防护 / subagent handoff 重命名)

### 2.1 既有防护事实(沿用 0.7.4 / 0.7.6 两轮确认)

- `nexus/backend/permissions/write_tools.py:29-40` `FILE_TOOLS` 精确白名单含
  字面 `"delete"`,`_WRITE_TOOL_PATTERNS` 含 `"_file"` 子串兜底;
- `tests/test_write_tools_helper.py` 锁定 3 个断言
  (`is_write_tool("delete") is True` / `delete_file` / `remove_file`);
- 基线锁测试 `_FS_TOOL_ORDER` 在 0.7.13 继续通过(7 个补丁版本字面值未变,
  改名 `_0_7_13` 断言体不动)。

### 2.2 subagent `handoff` → `isolated` 重命名(#6030, 0.7.13)

通过 `grep -r "handoff" nexus/backend/`(实测 0 命中)确认:Nexus 的
`nexus/backend/agent/_subagents.py` 涉及 `CompiledSubAgent` / `AsyncSubAgent`
/ `SubAgent`,**零引用** `handoff` 字面值。

**WHY 不影响**:这是 SDK 内部的 subagent 调度路径字面值,Nexus 中间件栈
(HITL / QualityGate / MemoryFilter)运行在 `create_deep_agent` 顶层,不下沉到
subagent 内部调度。Nexus 用 deepagents 顶层 agent,不依赖 subagent 命名。

### 2.3 复核结论

- ✅ 字面 `"delete"` 仍是 FilesystemMiddleware 注册的工具名(7 个补丁版本未变);
- ✅ `FILE_TOOLS` 白名单继续覆盖;
- ✅ `_FS_TOOL_ORDER` 基线锁测试改名 `_0_7_13`,断言体不动;
- ✅ subagent `handoff` 重命名对 Nexus 零影响(grep 验证);
- ✅ `SubAgent.system_prompt` 降级为 optional,Nexus 显式传 system_prompt 不受影响;
- ⚠️ 7 个补丁版本新增 SDK 内部能力(subagent forking / rubric hooks /
  middleware 追踪 / state backend files / glob 递归 / ContextHubBackend 并发)
  均默认关闭或隔离在 SDK 内部,**无需代码改动**;产品评估留待后续 RFC
  (见 §5 后续升级 TODO)。

## 3. 依赖表

| 包 | 0.7.6 时期 | 0.7.13 要求 | pyproject.toml 调整 |
| --- | --- | --- | --- |
| `deepagents` | `0.7.6` 实装 | `>=0.7.0,<0.8.0` | ✅ 区间未变 |
| `langchain` | `1.3.14` 实装 | `>=1.3.18,<2.0.0` | ✅ `>=1.3.14` → `>=1.3.18`(pip 实装升到 `1.4.0`) |
| `langchain-core` | `1.5.4` 实装 | `>=1.6.1,<2.0.0` | ✅ `>=1.5.0` → `>=1.6.1`(pip 实装升到 `1.6.3`) |
| `langsmith` | `0.10.15` 实装 | `>=0.11.2` | ✅ `>=0.10.9` → `>=0.11.2`(pip 实装升到 `0.12.5`) |
| `langchain-anthropic` | 未声明(`1.5.6` 实装,传递) | `>=1.7.0`(硬 Requires-Dist) | ⚠️ **不显式声明**:`pip install deepagents==0.7.13` 传递装上 `1.7.2`;Nexus 代码零引用(grep 验证),不膨胀依赖树 |
| `langchain-google-genai` | 未声明(`4.3.2` 实装,传递) | `>=4.3.7`(硬 Requires-Dist) | ⚠️ **不显式声明**:同上,传递装上 `4.4.0` |
| `langchain-openai` | `>=1.0.0` | 未变 | ✅ 区间未变 |
| `langchain-community` | `>=0.0.20` | 未变 | ✅ 区间未变 |
| `langgraph-checkpoint-sqlite` | `>=2.0,<4.0` | 未变 | ✅ 区间未变 |

`nexus/backend/requirements.txt` 收敛后:
```
deepagents==0.7.13
setproctitle>=0.2.0
```

(单行版本号 0.7.6 → 0.7.13,文件结构沿用 0.7.4 阶段的 11 行 → 2 行收敛结果。)

**WHY 不显式声明 langchain-anthropic / langchain-google-genai**:changelog 调研
确认 Nexus 代码零引用这两个包,deepagents 0.7.13 把它们列为硬 Requires-Dist 是
SDK 内部多 provider 探测需要。pip 传递装上即可,显式声明会让 Nexus 依赖树膨胀
且带来版本约束传递冲突风险。

## 4. 验证矩阵

```bash
# 安装验证(实测 2026-09-11)
source .venv/bin/activate
python -c "import deepagents, langchain, langchain_core, langsmith; print(deepagents.__version__, langchain.__version__, langchain_core.__version__, langsmith.__version__)"
# 实测:deepagents=0.7.13 langchain=1.4.0 langchain_core=1.6.3 langsmith=0.12.5

# 基线锁测试(改名后)
pytest tests/test_write_tools_helper.py::test_fs_tool_order_baseline_0_7_13 -v
# 实测:1/1 PASS

# 既有 delete 防护测试(防止回归)
pytest tests/test_write_tools_helper.py -v
# 实测:15/15 PASS(原 14 + 改名后的 1)

# Nexus import 链验证(transitive langchain 升级不破坏中间件路径)
python -c "
import nexus.backend.main
import nexus.backend.middleware.hitl
import nexus.backend.middleware.shell
import nexus.backend.middleware.force_tool
import nexus.backend.middleware.dynamic_identity
import nexus.backend.quality.middleware
import nexus.backend.rubrics.judge
import nexus.backend.tools
import nexus.backend.fact_check.langchain_tools
import nexus.backend.agent._agent_builder
import nexus.backend.agent._subagents
print('OK nexus modules')
"
# 实测:OK nexus modules(无 ImportError)

# pytest 全量
pytest tests/ -q --tb=line
# 期望:全过(基线 1004 passed, 12 skipped, 0 failed;改名后的
# test_fs_tool_order_baseline_0_7_13 已计入)

# lint
ruff check nexus/ tests/
# 期望:All checks passed!
```

## 5. 后续升级 TODO(延续 0.7.4 / 0.7.6-alignment §5)

| # | 项 | 文件 | 工作量 | 优先级 |
| --- | --- | --- | --- | --- |
| 1 | 真 LLM E2E 验 `delete` 工具触发 HITL 拦截 | `e2e/journey-delete-hitl.spec.ts` | 2h | 中 |
| 2 | `HarnessProfile.general_purpose_subagent` 槽空了,评估是否接回自定 profile | `nexus/backend/profiles/tier_routing.py` | 1h | 低 |
| 3 | `delete_directory` 子串模式未来若 deepagents 新增目录删除工具,需补 `_dir` / `_directory` 子串 | `nexus/backend/permissions/write_tools.py` | 0.5h | 低 |
| 4 | 评估 `langchain-anthropic` / `langchain-google-genai` 是否升级为显式声明(0.8 升级时需重新评估 deepagents 硬依赖策略) | `pyproject.toml` | 0.5h | 低 |
| 5 | 0.7.12 subagent conversation forking 评估 RFC —— 什么场景启用 forking 比禁用强 | `docs/designs/subagent-forking-rfc.md` | 4h | 低 |
| 6 | 0.7.13 isolated subagent 评估 —— 敏感数据场景(医疗/法律)的数据脱敏路径 | RFC + 原型 | 8h | 低 |

---

**总结**:0.7.6 → 0.7.13 跨 7 个补丁版本升级,**Nexus 接口层 0 行代码改动**
(`create_deep_agent` / `_FS_TOOL_ORDER` / `_ALL_FS_TOOL_NAMES` / `tool.name` /
langchain.* 主路径 API 全部稳定);触及 transitive 依赖升级(`langchain` 1.3.14
→ 1.4.0 / `langchain-core` 1.5.4 → 1.6.3 / `langsmith` 0.10.15 → 0.12.5,
`langchain-anthropic` 1.5.6 → 1.7.2 / `langchain-google-genai` 4.3.2 → 4.4.0),
通过 pyproject.toml 下限收紧对齐 deepagents 0.7.13 Requires-Dist;基线锁测试
改名版本号、`SubAgent` TypedDict 锁更新(`system_prompt` required → optional)。
唯一非零事项:1 个 `test_subagent_typeddict_required_keys_0_7_4 → _0_7_13`
基线锁改名 + 1 行断言调整(SDK 把 `system_prompt` 从 required 降级为
optional;Nexus `create_subagents()` 仍显式传 system_prompt,业务行为不变)。