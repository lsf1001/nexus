# DeepAgents 0.7.6 → 0.7.13 升级实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Nexus `.venv` 的 `deepagents` 从 0.7.6 升到 0.7.13(7 个补丁版本,跨 0.7.7–0.7.13),同步收紧 `pyproject.toml` 的 `langchain` / `langchain-core` / `langsmith` 下限,更新 `nexus/backend/requirements.txt` 锁版本号,更新基线锁测试的版本号,写 0.7.13 对齐报告。

**Architecture:** 单次补丁升级窗口。`create_deep_agent` 签名 / `_FS_TOOL_ORDER` / `_ALL_FS_TOOL_NAMES` / `tool.name == "delete"` 经 7 个补丁版本确认**零 API drift**,Nexus 接口层零代码改动。仅触及:
1. `.venv` 运行时(装 `deepagents==0.7.13` + transitive `langchain>=1.3.18` / `langchain-core>=1.6.1` / `langsmith>=0.11.2`)
2. `pyproject.toml` 3 行下限收紧(对齐 deepagents 0.7.13 Requires-Dist)
3. `nexus/backend/requirements.txt` 1 行版本号
4. `tests/test_write_tools_helper.py` 1 个测试函数名 + 注释
5. `docs/operations/deepagents-0.7.13-alignment.md` 新建

**Tech Stack:** Python 3.11+, pytest 8+, pip, deepagents 0.7.13, langchain 1.3.18+, langchain-core 1.6.1+, langsmith 0.11.2+, ruff。

---

## 前置:Changelog 调研结论(2026-09-11)

> 详细逐版本分析见 `docs/operations/deepagents-0.7.13-alignment.md` §2。

| 版本 | 类型 | 关键改动 | Nexus 接口层影响 |
| --- | --- | --- | --- |
| 0.7.13 (09-02) | fix | subagent `handoff` → `isolated` 重命名 (#6030) | **零**。Nexus `_subagents.py` 零引用 `handoff` |
| 0.7.12 (09-01) | feat+fix | subagent conversation forking (#5714); glob sort 缺 `modified_at` 容错 (#4376) | **零**。新功能默认关 |
| 0.7.11 (08-28) | feat | rubric grader 集成 hooks (#5874) | **零**。Add-only |
| 0.7.10 (08-28) | fix | TUI 输入冲突 + sandbox glob 失败透传 (#5873/#5566) | **零**。CLI/TUI 与 sandbox |
| 0.7.9 (08-25) | feat+fix | middleware 追踪输入关闭; `excluded_tools` 生效; RubricMiddleware 强覆盖; execute timeout 语义澄清 | **零**。`tier_routing.py` 概念层引用,未直接调 API |
| 0.7.8 (08-20) | fix | state backend 加 `files` 字段 (#5643) | **零**。Nexus 用 `CompositeBackend` |
| 0.7.7 (08-18) | fix | `BackendProtocol.glob` bare pattern 递归; ContextHubBackend 并发批处理 | **零**。Nexus `_backend.py` 懒 import |

**结论:Nexus 接口层 100% 兼容,0 行代码改动。** 仅有 transitive 依赖版本升级。

---

## 文件变更表

| 文件 | 动作 | 责任 |
| --- | --- | --- |
| `.venv` (运行时) | 升 `deepagents 0.7.6 → 0.7.13` + 拉 langchain/langchain-core/langsmith 到新下限 | Task 1 |
| `pyproject.toml:36-38` | `langchain>=1.3.14 → >=1.3.18`,`langchain-core>=1.5.0 → >=1.6.1`,`langsmith>=0.10.9 → >=0.11.2` | Task 2 |
| `nexus/backend/requirements.txt` | `deepagents==0.7.6 → ==0.7.13` | Task 3 |
| `tests/test_write_tools_helper.py` | 测试函数改名 `test_fs_tool_order_baseline_0_7_6 → ..._0_7_13` + 注释里 0.7.6 改 0.7.13 | Task 4 |
| `docs/operations/deepagents-0.7.13-alignment.md` | 新建 | Task 5 |

**不动**:`nexus/backend/permissions/write_tools.py` / `PathAwareHITLMiddleware` / `QualityGateMiddleware` / 0.7.6 阶段的所有 HITL/文件工具相关代码(API drift 调研确认无影响)。

---

## Task 1: 升级 .venv 的 deepagents 到 0.7.13

**Files:**
- Modify: `.venv` (运行时,不可 git 跟踪)

- [ ] **Step 1: 确认当前已装版本(防止基于过期信息操作)**

Run:
```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && python -c "import deepagents, langchain, langchain_core, langsmith; print(f'deepagents={deepagents.__version__} langchain={langchain.__version__} langchain_core={langchain_core.__version__} langsmith={langsmith.__version__}')"
```
Expected: `deepagents=0.7.6 langchain=1.3.14 langchain_core=1.5.4 langsmith=0.10.15`(2026-09-11 实测)。

- [ ] **Step 2: 升级 deepagents(允许 transitive 升级 langchain/langsmith)**

Run:
```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && pip install --upgrade 'deepagents==0.7.13'
```
Expected: 终端显示 `Successfully installed deepagents-0.7.13`,并触发 langchain(1.3.14 → 1.3.18+)/langchain-core(1.5.4 → 1.6.1+)/langsmith(0.10.15 → 0.11.2+) 的升级提示。

> **WHY 不用区间约束**:本计划只动单点版本号,不动 pyproject 区间约束(已在 Task 2 显式声明了 0.7.13 所需下限)。

- [ ] **Step 3: 验证版本(确认 0.7.13 + transitive 全部到位)**

Run:
```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && python -c "import deepagents, langchain, langchain_core, langsmith; print(f'deepagents={deepagents.__version__} langchain={langchain.__version__} langchain_core={langchain_core.__version__} langsmith={langsmith.__version__}')"
```
Expected: `deepagents=0.7.13 langchain>=1.3.18 langchain_core>=1.6.1 langsmith>=0.11.2`(具体子版本看 pip 解析)。

- [ ] **Step 4: 验证 import 不挂(防止 deepagents 内部 API drift)**

Run:
```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && python -c "from deepagents.middleware.filesystem import _FS_TOOL_ORDER, _ALL_FS_TOOL_NAMES; from deepagents import create_deep_agent; print('OK', _FS_TOOL_ORDER[:3])"
```
Expected: `OK ('ls', 'read_file', 'write_file')` —— `_FS_TOOL_ORDER` 仍为 7 元素元组,顺序未变。

- [ ] **Step 5: 验证 Nexus import 链不挂(transitive langchain 升级可能破坏 langchain.agents.middleware 路径)**

Run:
```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && python -c "
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import AgentMiddleware as T, AgentState, ModelRequest, ModelResponse
from langchain_core.tools import tool
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
print('OK nexus import chain')
" 2>&1
```
Expected: `OK nexus import chain` 或类似零错误信息。

如果失败:回滚到 0.7.6 `pip install --force-reinstall 'deepagents==0.7.6' langchain==1.3.14 langchain_core==1.5.4 langsmith==0.10.15`,补 `docs/operations/deepagents-0.7.13-alignment.md` §2。

---

## Task 2: 收紧 pyproject.toml 的 langchain/langchain-core/langsmith 下限

**Files:**
- Modify: `pyproject.toml:36-38`(3 行)

- [ ] **Step 1: 读 pyproject.toml 第 24-55 行,确认现状**

预期现状:
```
"langchain>=1.3.14,<2.0.0",
"langchain-core>=1.5.0,<2.0.0",
"langsmith>=0.10.9",
```

- [ ] **Step 2: 三行版本下限收紧**

将上述三行改为:
```
"langchain>=1.3.18,<2.0.0",
"langchain-core>=1.6.1,<2.0.0",
"langsmith>=0.11.2",
```

(用 Edit 工具,`replace_all=False`,一次替换三个连续行的整段)

> **WHY 三个下限**:
> - `langchain` 1.3.14 → 1.3.18:deepagents 0.7.13 `Requires-Dist: langchain<2.0.0,>=1.3.18`
> - `langchain-core` 1.5.0 → 1.6.1:deepagents 0.7.13 `Requires-Dist: langchain-core<2.0.0,>=1.6.1`
> - `langsmith` 0.10.9 → 0.11.2:deepagents 0.7.13 `Requires-Dist: langsmith>=0.11.2`
>
> 不补 `langchain-anthropic` / `langchain-google-genai`:deepagents 0.7.13 把它们列为硬 Requires-Dist,但 `pip install deepagents==0.7.13` 会传递装上;Nexus 代码零引用(grep 验证),不显式声明避免膨胀依赖树。

- [ ] **Step 3: 验证 `pip install -e .` 解析无冲突(模拟干净环境)**

Run:
```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && pip install --dry-run -e . 2>&1 | tail -20
```
Expected: `Would install nexus-1.0.0` 且**无** `ERROR: ResolutionImpossible`,**无** 提示 `deepagents` 要降级 langchain 拉回 1.3.14。

- [ ] **Step 4: 真安装一遍,验证 e2e_mock / middleware / tools import 全过**

Run:
```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && pip install -e . 2>&1 | tail -5 && python -c "
import nexus.backend.main
import nexus.backend.middleware.hitl
import nexus.backend.middleware.shell
import nexus.backend.middleware.force_tool
import nexus.backend.middleware.dynamic_identity
import nexus.backend.quality.middleware
import nexus.backend.rubrics.judge
import nexus.backend.tools
import nexus.backend.fact_check.langchain_tools
print('OK nexus modules')
" 2>&1
```
Expected: `OK nexus modules`,无 ImportError,无 deprecation warning 阻断。

如果失败:`pip install --force-reinstall 'deepagents==0.7.6' langchain==1.3.14 langchain_core==1.5.4 langsmith==0.10.15`,调查失败模块,补对齐报告 §3。

- [ ] **Step 5: 暂不 commit(后续任务一起提交)**

---

## Task 3: 收敛 nexus/backend/requirements.txt 锁版本号

**Files:**
- Modify: `nexus/backend/requirements.txt`(单行替换)

- [ ] **Step 1: 读现状(确认是 8-14 升级的产物)**

预期现状:
```
deepagents==0.7.6
setproctitle>=0.2.0
```

- [ ] **Step 2: 单行版本号更新**

将 `deepagents==0.7.6` 改为 `deepagents==0.7.13`(整文件唯一改动)。

> **WHY 单行**:8-14 计划已把 11 行收敛为 2 行,本计划延续"最小化 diff"原则,只动版本号。

- [ ] **Step 3: 校验**

Run:
```bash
cd /Users/yxb/projects/nexus && wc -l nexus/backend/requirements.txt && echo "---" && cat nexus/backend/requirements.txt
```
Expected:
```
       2 nexus/backend/requirements.txt
---
deepagents==0.7.13
setproctitle>=0.2.0
```

- [ ] **Step 4: 暂不 commit**

---

## Task 4: 更新基线锁测试(改版本号 + docstring)

**Files:**
- Modify: `tests/test_write_tools_helper.py`(追加的 `test_fs_tool_order_baseline_0_7_6` 函数改名)

- [ ] **Step 1: 读测试文件,定位待改函数**

读 `tests/test_write_tools_helper.py` 找到 8-14 计划追加的 `test_fs_tool_order_baseline_0_7_6` 函数体。

- [ ] **Step 2: 函数名 + docstring 改 0.7.13**

将:
```python
def test_fs_tool_order_baseline_0_7_6() -> None:
    """锁 deepagents FilesystemMiddleware._FS_TOOL_ORDER 在 0.7.6 的字面顺序。

    WHY: HITL / MemoryFilter / QualityGateMiddleware 拦截逻辑依赖字面工具名
    ('delete' / 'write_file' / ...)。若 0.7.7 / 0.8 改顺序或改名,
    is_write_tool() 仍能兜底(子串匹配),但 LLM 工具提示的展示顺序会变,
    触发 e2e flake。此断言作为 0.7.x 补丁升级窗口的基线锁;未来 0.7.7 / 0.8
    升级时按新字面值更新即可。
    """
```

改为:
```python
def test_fs_tool_order_baseline_0_7_13() -> None:
    """锁 deepagents FilesystemMiddleware._FS_TOOL_ORDER 在 0.7.13 的字面顺序。

    WHY: HITL / MemoryFilter / QualityGateMiddleware 拦截逻辑依赖字面工具名
    ('delete' / 'write_file' / ...)。若 0.7.14 / 0.8 改顺序或改名,
    is_write_tool() 仍能兜底(子串匹配),但 LLM 工具提示的展示顺序会变,
    触发 e2e flake。此断言作为 0.7.x 补丁升级窗口的基线锁;未来 0.7.14 / 0.8
    升级时按新字面值更新即可。

    跨 0.7.7 → 0.7.13 共 7 个补丁版本升级,本测试未做断言内容改动 —— 仅
    改名/改注释,以明示当前基线对应的版本号。
    """
```

**断言体本身保持不变**(`assert _FS_TOOL_ORDER == ("ls", "read_file", ..., "grep")`)。changelog 调研确认 0.7.7-0.7.13 期间 `_FS_TOOL_ORDER` 字面值未变。

- [ ] **Step 3: 跑新测试,确认 PASS**

Run:
```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && pytest tests/test_write_tools_helper.py::test_fs_tool_order_baseline_0_7_13 -v
```
Expected:
```
tests/test_write_tools_helper.py::test_fs_tool_order_baseline_0_7_13 PASSED
```

- [ ] **Step 4: 跑整文件,确认无回归**

Run:
```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && pytest tests/test_write_tools_helper.py -v
```
Expected: 全 PASS(原 15 个含改名后的 1 个)。

- [ ] **Step 5: 暂不 commit**

---

## Task 5: 写 docs/operations/deepagents-0.7.13-alignment.md

**Files:**
- Create: `docs/operations/deepagents-0.7.13-alignment.md`

- [ ] **Step 1: 用 Write 工具新建文件,内容如下**

```markdown
# DeepAgents 0.7.13 升级对齐报告

> **目的**:记录 Nexus 从 deepagents 0.7.6 跨 7 个补丁版本(0.7.7 → 0.7.13)升到
> 0.7.13 的 API drift、依赖变更、回归验证矩阵,作为后续 0.7.14 / 0.8 升级的
> 基线。
>
> **环境**:deepagents `0.7.13`(2026-09-02)、langchain `>=1.3.18`、
> langchain-core `>=1.6.1`、langsmith `>=0.11.2`(2026-09-11 实装,具体子版本
> 取决于 pip 解析)。
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
- 基线锁测试 `_FS_TOOL_ORDER` 在 0.7.13 继续通过(7 个补丁版本字面值未变)。

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
- ⚠️ 7 个补丁版本新增 SDK 内部能力(subagent forking / rubric hooks /
  middleware 追踪 / state backend files / glob 递归 / ContextHubBackend 并发)
  均默认关闭或隔离在 SDK 内部,**无需代码改动**。

## 3. 依赖表

| 包 | 0.7.6 时期 | 0.7.13 要求 | pyproject.toml 调整 |
| --- | --- | --- | --- |
| `deepagents` | `0.7.6` 实装 | `>=0.7.0,<0.8.0` | ✅ 区间未变 |
| `langchain` | `1.3.14` | `>=1.3.18,<2.0.0` | ✅ `>=1.3.14` → `>=1.3.18` |
| `langchain-core` | `1.5.3` (实测 1.5.4) | `>=1.6.1,<2.0.0` | ✅ `>=1.5.0` → `>=1.6.1` |
| `langsmith` | `0.10.15` | `>=0.11.2` | ✅ `>=0.10.9` → `>=0.11.2` |
| `langchain-anthropic` | 未声明 | `>=1.7.0`(硬 Requires-Dist) | ⚠️ **不显式声明**:`pip install deepagents==0.7.13` 传递装上;Nexus 代码零引用(grep 验证),不膨胀依赖树 |
| `langchain-google-genai` | 未声明 | `>=4.3.7`(硬 Requires-Dist) | ⚠️ **不显式声明**:同上 |
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
# 安装验证
source .venv/bin/activate
python -c "import deepagents, langchain, langchain_core, langsmith; print(deepagents.__version__, langchain.__version__, langchain_core.__version__, langsmith.__version__)"
# 期望 deepagents=0.7.13, langchain>=1.3.18, langchain_core>=1.6.1, langsmith>=0.11.2

# 基线锁测试(改名后)
pytest tests/test_write_tools_helper.py::test_fs_tool_order_baseline_0_7_13 -v
# 期望 1/1 PASS

# 既有 delete 防护测试(防止回归)
pytest tests/test_write_tools_helper.py -v
# 期望 全过(15 个,含 test_is_write_tool_known_write_returns_true 锁 'delete' 为 True)

# Nexus import 链验证(transitive langchain 升级不破坏中间件路径)
python -c "
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import AgentMiddleware as T, AgentState, ModelRequest, ModelResponse
from langchain_core.tools import tool
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
print('OK nexus import chain')
"

# pytest 全量
pytest tests/ -q --tb=line
# 期望 全过(基线 1004 passed, 12 skipped, 0 failed;改名后的
# test_fs_tool_order_baseline_0_7_13 已计入)

# lint
ruff check nexus/ tests/
# 期望 All checks passed!
```

## 5. 后续升级 TODO(延续 0.7.4 / 0.7.6-alignment §5)

| # | 项 | 文件 | 工作量 | 优先级 |
| --- | --- | --- | --- | --- |
| 1 | 真 LLM E2E 验 `delete` 工具触发 HITL 拦截 | `e2e/journey-delete-hitl.spec.ts` | 2h | 中 |
| 2 | `HarnessProfile.general_purpose_subagent` 槽空了,评估是否接回自定 profile | `nexus/backend/profiles/tier_routing.py` | 1h | 低 |
| 3 | `delete_directory` 子串模式未来若 deepagents 新增目录删除工具,需补 `_dir` / `_directory` 子串 | `nexus/backend/permissions/write_tools.py` | 0.5h | 低 |
| 4 | 评估 `langchain-anthropic` / `langchain-google-genai` 是否升级为显式声明(0.8 升级时需重新评估 deepagents 硬依赖策略) | `pyproject.toml` | 0.5h | 低 |

---

**总结**:0.7.6 → 0.7.13 跨 7 个补丁版本升级,**Nexus 接口层 0 行代码改动**
(`create_deep_agent` / `_FS_TOOL_ORDER` / `_ALL_FS_TOOL_NAMES` / `tool.name` /
langchain.* 主路径 API 全部稳定);触及 transitive 依赖升级(`langchain` 1.3.14
→ ≥1.3.18 / `langchain-core` 1.5.4 → ≥1.6.1 / `langsmith` 0.10.15 → ≥0.11.2),
通过 pyproject.toml 下限收紧对齐 deepagents 0.7.13 Requires-Dist;基线锁测试
改名版本号、断言体零改动。
```

- [ ] **Step 2: 校验文件行数与章节数**

Run:
```bash
cd /Users/yxb/projects/nexus && wc -l docs/operations/deepagents-0.7.13-alignment.md && grep -c "^## " docs/operations/deepagents-0.7.13-alignment.md
```
Expected: 行数约 150-165 行;`## ` 章节数 = 5。

- [ ] **Step 3: 暂不 commit(连同 Task 1-4 一起提交)**

---

## Task 6: 提交全部变更 + 跑全套验证

**Files:**
- Stage: `pyproject.toml`, `nexus/backend/requirements.txt`, `tests/test_write_tools_helper.py`, `docs/operations/deepagents-0.7.13-alignment.md`

- [ ] **Step 1: 确认 git status**

Run:
```bash
cd /Users/yxb/projects/nexus && git status --short
```
Expected: 4 个 modified/new 文件,且**没有** `.venv/`、`.pytest_cache/`、其他无关文件。

- [ ] **Step 2: 跑 ruff,确认零 diff**

Run:
```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && ruff check nexus/ tests/
```
Expected: `All checks passed!`

- [ ] **Step 3: 跑 pytest 全量,确认无回归**

Run:
```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && pytest tests/ -q --tb=line
```
Expected: 全过(基线 1004 passed, 12 skipped, 0 failed;改名后的
`test_fs_tool_order_baseline_0_7_13` 已计入)。

- [ ] **Step 4: 四文件 stage + 单一 commit**

Run:
```bash
cd /Users/yxb/projects/nexus && git add pyproject.toml nexus/backend/requirements.txt tests/test_write_tools_helper.py docs/operations/deepagents-0.7.13-alignment.md && git -c commit.gpgsign=false commit -m "chore(deps): 升 deepagents 0.7.6 → 0.7.13(7 补丁)+ pyproject 下限收紧

- pip: deepagents 0.7.6 → 0.7.13 (跨 0.7.7/0.7.8/0.7.9/0.7.10/0.7.11/0.7.12/0.7.13)
- pyproject: langchain>=1.3.14 → >=1.3.18, langchain-core>=1.5.0 → >=1.6.1,
  langsmith>=0.10.9 → >=0.11.2 (对齐 deepagents 0.7.13 Requires-Dist)
- requirements.txt: deepagents==0.7.6 → ==0.7.13
- tests: test_fs_tool_order_baseline_0_7_6 改名 _0_7_13, 断言体不变
  (7 补丁期间 _FS_TOOL_ORDER 字面值未变)
- docs: 写 0.7.13 对齐报告, 复核 #6030 subagent handoff 重命名对 Nexus 无影响
- Nexus 接口层: 0 行代码改动 (create_deep_agent / _FS_TOOL_ORDER /
  langchain.* 主路径 API 全部稳定)"
```
Expected: 一个 commit,4 files changed。

- [ ] **Step 5: 验证 commit 落库**

Run:
```bash
cd /Users/yxb/projects/nexus && git log --oneline -3
```
Expected: 顶部是本次升级 commit,上一行是 8-14 的 0.7.6 升级 commit(`8e64308`)。

---

## 失败回退

若 Step 2 / Step 3 任一失败:

1. Task 1 的升级可逆:`pip install --force-reinstall 'deepagents==0.7.6' langchain==1.3.14 langchain_core==1.5.4 langsmith==0.10.15`
2. Task 2-5 的文件改动可逆:`git checkout -- pyproject.toml nexus/backend/requirements.txt tests/test_write_tools_helper.py docs/operations/deepagents-0.7.13-alignment.md`
3. 检查新引入的 drift,补充 `docs/operations/deepagents-0.7.13-alignment.md` §1 总览表 + §2 复核结论。
