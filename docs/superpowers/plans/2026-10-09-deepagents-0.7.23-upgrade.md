# DeepAgents 0.7.13 → 0.7.23 升级实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Nexus `.venv` 的 `deepagents` 从 0.7.13 升到 0.7.23(10 个补丁版本,跨 0.7.14–0.7.23),同步收紧 `pyproject.toml` 的 `langchain` / `langchain-core` / `langsmith` 下限,更新 `nexus/backend/requirements.txt` 锁版本号,更新基线锁测试的版本号,写 0.7.23 对齐报告。

**Architecture:** 单次补丁升级窗口。`create_deep_agent` 签名 / `_FS_TOOL_ORDER` / `_ALL_FS_TOOL_NAMES` / `tool.name == "delete"` / `SubAgent` TypedDict 经 10 个补丁版本确认**零 API drift**,Nexus 接口层零代码改动。10 个补丁版本的实质改动只有三处:
- 0.7.21 feat: `FilesystemMiddleware` 可在 backend 存 blob(默认关闭,新可选)
- 0.7.22 feat: skill tools 懒加载(Nexus skills 是自家 shell,不调 SDK `SkillsMiddleware`)
- 0.7.23 feat: `pinned_skills` + 每 subagent 独立 SkillsMiddleware(同上,零触碰)

仅触及:
1. `.venv` 运行时(装 `deepagents==0.7.23` + transitive `langchain>=1.4.3` / `langchain-core>=1.6.7` / `langsmith>=0.14.4`)
2. `pyproject.toml` 3 行下限收紧(对齐 deepagents 0.7.23 Requires-Dist)
3. `nexus/backend/requirements.txt` 1 行版本号
4. `tests/test_write_tools_helper.py` 1 个测试函数名 + 注释
5. `docs/operations/deepagents-0.7.23-alignment.md` 新建

**Tech Stack:** Python 3.11+, pytest 8+, pip, deepagents 0.7.23, langchain 1.4.3+, langchain-core 1.6.7+, langsmith 0.14.4+, ruff。

---

## 前置:Changelog 调研结论(2026-10-09)

> 详细逐版本分析见 `docs/operations/deepagents-0.7.23-alignment.md` §2。

| 版本 | 类型 | 关键改动 | Nexus 接口层影响 |
| --- | --- | --- | --- |
| 0.7.23 (10-07) | feat+fix | `pinned_skills` (#6810);每 subagent 独立 SkillsMiddleware (#6820) | **零**。Nexus 不调 SDK SkillsMiddleware(自家 `nexus/backend/tools.py:242 run_skill` 走 shell) |
| 0.7.22 (10-05) | feat+fix | skill tools 懒加载 (#6552);stale encoding fix (#6737) | **零**。同上 |
| 0.7.21 (09-30) | feat | `FilesystemMiddleware` 可在 backend 存 blob (#6550) | **零**。新功能默认关闭 |
| 0.7.20 (09-29) | fix | `StateBackend.upload_files` 二进制被错标 base64 | **零**。Nexus 用 `CompositeBackend`,不直接调 `StateBackend` |
| 0.7.19 (09-24) | chore(deps) | 依赖下限 bump only | **零**。transitive 升级 |
| 0.7.18 (09-23) | chore(deps) | 依赖下限 bump only | **零**。transitive 升级 |
| 0.7.17 (09-22) | chore(deps) | 依赖下限 bump only | **零**。transitive 升级 |
| 0.7.16 (09-21) | chore(deps) | 依赖下限 bump only | **零**。transitive 升级 |
| 0.7.15 (09-16) | chore(deps) | 依赖下限 bump only | **零**。transitive 升级 |
| 0.7.14 (09-14) | chore(deps) | 依赖下限 bump only | **零**。transitive 升级 |

**结论:Nexus 接口层 100% 兼容,0 行代码改动。** 仅有 transitive 依赖版本升级 + 内部 bugfix(SkillsMiddleware / StateBackend)。

---

## 文件变更表

| 文件 | 动作 | 责任 |
| --- | --- | --- |
| `.venv` (运行时) | 升 `deepagents 0.7.13 → 0.7.23` + 拉 langchain/langchain-core/langsmith 到新下限 | Task 1 |
| `pyproject.toml:36-38` | `langchain>=1.3.18 → >=1.4.3`,`langchain-core>=1.6.1 → >=1.6.7`,`langsmith>=0.11.2 → >=0.14.4` | Task 2 |
| `nexus/backend/requirements.txt` | `deepagents==0.7.13 → ==0.7.23` | Task 3 |
| `tests/test_write_tools_helper.py` | 测试函数改名 `test_fs_tool_order_baseline_0_7_13 → ..._0_7_23` + 注释里 0.7.13 改 0.7.23 | Task 4 |
| `docs/operations/deepagents-0.7.23-alignment.md` | 新建 | Task 5 |

**不动**:`nexus/backend/permissions/write_tools.py` / `PathAwareHITLMiddleware` / `QualityGateMiddleware` / 0.7.13 阶段的 HITL/文件工具/skills 相关代码(API drift 调研确认无影响;Nexus skills 走自家 `run_skill` shell,不调 SDK `SkillsMiddleware`)。

---

## Task 1: 升级 .venv 的 deepagents 到 0.7.23

**Files:**
- Modify: `.venv` (运行时,不可 git 跟踪)

- [ ] **Step 1: 确认当前已装版本(防止基于过期信息操作)**

Run:
```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && python -c "import deepagents, langchain, langchain_core, langsmith; print(f'deepagents={deepagents.__version__} langchain={langchain.__version__} langchain_core={langchain_core.__version__} langsmith={langsmith.__version__}')"
```
Expected: `deepagents=0.7.13 langchain=1.4.0 langchain_core=1.6.3 langsmith=0.12.5`(2026-10-09 实测)。

- [ ] **Step 2: 升级 deepagents(允许 transitive 升级 langchain/langsmith)**

Run:
```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && pip install --upgrade 'deepagents==0.7.23'
```
Expected: 终端显示 `Successfully installed deepagents-0.7.23`,并触发 langchain(1.4.0 → 1.4.3+)/langchain-core(1.6.3 → 1.6.7+)/langsmith(0.12.5 → 0.14.4+) 的升级提示。

> **WHY 不用区间约束**:本计划只动单点版本号,不动 pyproject 区间约束(已在 Task 2 显式声明了 0.7.23 所需下限)。

- [ ] **Step 3: 验证版本(确认 0.7.23 + transitive 全部到位)**

Run:
```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && python -c "import deepagents, langchain, langchain_core, langsmith; print(f'deepagents={deepagents.__version__} langchain={langchain.__version__} langchain_core={langchain_core.__version__} langsmith={langsmith.__version__}')"
```
Expected: `deepagents=0.7.23 langchain>=1.4.3 langchain_core>=1.6.7 langsmith>=0.14.4`(具体子版本看 pip 解析)。

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

如果失败:回滚到 0.7.13 `pip install --force-reinstall 'deepagents==0.7.13' langchain==1.4.0 langchain_core==1.6.3 langsmith==0.12.5`,补 `docs/operations/deepagents-0.7.23-alignment.md` §2。

---

## Task 2: 收紧 pyproject.toml 的 langchain/langchain-core/langsmith 下限

**Files:**
- Modify: `pyproject.toml:36-38`(3 行)

- [ ] **Step 1: 读 pyproject.toml 第 24-55 行,确认现状**

预期现状(2026-09-11 0.7.13 升级后):
```
"langchain>=1.3.18,<2.0.0",
"langchain-core>=1.6.1,<2.0.0",
"langsmith>=0.11.2",
```

- [ ] **Step 2: 三行版本下限收紧**

将上述三行改为:
```
"langchain>=1.4.3,<2.0.0",
"langchain-core>=1.6.7,<2.0.0",
"langsmith>=0.14.4",
```

(用 Edit 工具,`replace_all=False`,一次替换三个连续行的整段)

> **WHY 三个下限**:
> - `langchain` 1.3.18 → 1.4.3:deepagents 0.7.23 `Requires-Dist: langchain<2.0.0,>=1.4.3`
> - `langchain-core` 1.6.1 → 1.6.7:deepagents 0.7.23 `Requires-Dist: langchain-core<2.0.0,>=1.6.7`
> - `langsmith` 0.11.2 → 0.14.4:deepagents 0.7.23 `Requires-Dist: langsmith>=0.14.4`
>
> 不补 `langchain-anthropic` / `langchain-google-genai`:deepagents 0.7.23 把它们列为硬 Requires-Dist,但 `pip install deepagents==0.7.23` 会传递装上;Nexus 代码零引用(grep 验证),不显式声明避免膨胀依赖树。

- [ ] **Step 3: 验证 `pip install -e .` 解析无冲突(模拟干净环境)**

Run:
```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && pip install --dry-run -e . 2>&1 | tail -20
```
Expected: `Would install nexus-1.0.0` 且**无** `ERROR: ResolutionImpossible`,**无** 提示 `deepagents` 要降级 langchain 拉回 1.3.18。

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

如果失败:`pip install --force-reinstall 'deepagents==0.7.13' langchain==1.4.0 langchain_core==1.6.3 langsmith==0.12.5`,调查失败模块,补对齐报告 §3。

- [ ] **Step 5: 暂不 commit(后续任务一起提交)**

---

## Task 3: 收敛 nexus/backend/requirements.txt 锁版本号

**Files:**
- Modify: `nexus/backend/requirements.txt`(单行替换)

- [ ] **Step 1: 读现状(确认是 9-11 升级的产物)**

预期现状:
```
deepagents==0.7.13
setproctitle>=0.2.0
```

- [ ] **Step 2: 单行版本号更新**

将 `deepagents==0.7.13` 改为 `deepagents==0.7.23`(整文件唯一改动)。

> **WHY 单行**:9-11 计划已把 11 行收敛为 2 行,本计划延续"最小化 diff"原则,只动版本号。

- [ ] **Step 3: 校验**

Run:
```bash
cd /Users/yxb/projects/nexus && wc -l nexus/backend/requirements.txt && echo "---" && cat nexus/backend/requirements.txt
```
Expected:
```
       2 nexus/backend/requirements.txt
---
deepagents==0.7.23
setproctitle>=0.2.0
```

- [ ] **Step 4: 暂不 commit**

---

## Task 4: 更新基线锁测试(改版本号 + docstring)

**Files:**
- Modify: `tests/test_write_tools_helper.py`(追加的 `test_fs_tool_order_baseline_0_7_13` 函数改名)

- [ ] **Step 1: 读测试文件,定位待改函数**

读 `tests/test_write_tools_helper.py` 找到 9-11 计划追加的 `test_fs_tool_order_baseline_0_7_13` 函数体。

- [ ] **Step 2: 函数名 + docstring 改 0.7.23**

将:
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

改为:
```python
def test_fs_tool_order_baseline_0_7_23() -> None:
    """锁 deepagents FilesystemMiddleware._FS_TOOL_ORDER 在 0.7.23 的字面顺序。

    WHY: HITL / MemoryFilter / QualityGateMiddleware 拦截逻辑依赖字面工具名
    ('delete' / 'write_file' / ...)。若 0.7.24 / 0.8 改顺序或改名,
    is_write_tool() 仍能兜底(子串匹配),但 LLM 工具提示的展示顺序会变,
    触发 e2e flake。此断言作为 0.7.x 补丁升级窗口的基线锁;未来 0.7.24 / 0.8
    升级时按新字面值更新即可。

    跨 0.7.14 → 0.7.23 共 10 个补丁版本升级,本测试未做断言内容改动 —— 仅
    改名/改注释,以明示当前基线对应的版本号。10 补丁期间所有改动均与
    Nexus 接口层无交集(deps bump + SkillsMiddleware 新增 + StateBackend
    base64 修复,详见 docs/operations/deepagents-0.7.23-alignment.md §2)。
    """
```

**断言体本身保持不变**(`assert _FS_TOOL_ORDER == ("ls", "read_file", ..., "grep")`)。changelog 调研确认 0.7.14-0.7.23 期间 `_FS_TOOL_ORDER` 字面值未变。

- [ ] **Step 3: 跑新测试,确认 PASS**

Run:
```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && pytest tests/test_write_tools_helper.py::test_fs_tool_order_baseline_0_7_23 -v
```
Expected:
```
tests/test_write_tools_helper.py::test_fs_tool_order_baseline_0_7_23 PASSED
```

- [ ] **Step 4: 跑整文件,确认无回归**

Run:
```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && pytest tests/test_write_tools_helper.py -v
```
Expected: 全 PASS(原 15 个含改名后的 1 个)。

- [ ] **Step 5: 暂不 commit**

---

## Task 5: 写 docs/operations/deepagents-0.7.23-alignment.md

**Files:**
- Create: `docs/operations/deepagents-0.7.23-alignment.md`

- [ ] **Step 1: 用 Write 工具新建文件,内容如下**

```markdown
# DeepAgents 0.7.23 升级对齐报告

> **目的**:记录 Nexus 从 deepagents 0.7.13 跨 10 个补丁版本(0.7.14 → 0.7.23)升到
> 0.7.23 的 API drift、依赖变更、回归验证矩阵,作为后续 0.7.24 / 0.8 升级的
> 基线。
>
> **环境**:deepagents `0.7.23`(2026-10-07)、langchain `>=1.4.3`、
> langchain-core `>=1.6.7`、langsmith `>=0.14.4`(2026-10-09 实装,具体子版本
> 取决于 pip 解析)。
>
> **前置报告**:
> - [`docs/operations/deepagents-0.7.4-alignment.md`](./deepagents-0.7.4-alignment.md)(2026-08-10)
> - [`docs/operations/deepagents-0.7.6-alignment.md`](./deepagents-0.7.6-alignment.md)(2026-08-14)
> - [`docs/operations/deepagents-0.7.13-alignment.md`](./deepagents-0.7.13-alignment.md)(2026-09-11)
>
> 本文延续补丁升级报告惯例。

## 1. 总览

| 维度 | 0.7.13 行为 | 0.7.23 行为 | Nexus 影响 | 修复点 |
| --- | --- | --- | --- | --- |
| `FilesystemMiddleware._FS_TOOL_ORDER` | `("ls","read_file","write_file","edit_file","delete","glob","grep")` | **未变**(10 个补丁版本) | 零 | 基线锁测试改名 `_0_7_13 → _0_7_23`,断言体不动 |
| `_ALL_FS_TOOL_NAMES` | `{ls,read_file,write_file,edit_file,delete,glob,grep,execute}` | **未变** | 零 | 零 |
| `delete` 工具 `tool.name` | 字面 `"delete"` | 字面 `"delete"`(未变) | 零 | `FILE_TOOLS` 白名单继续覆盖 |
| `create_deep_agent` 签名 | `create_deep_agent(tools=..., middleware=..., ...)` | 未变 | 零 | 零 |
| `langchain.agents.middleware.AgentMiddleware` | 主路径 API | 未变(0.7.14-0.7.23 期间未触碰) | 零 | 零 |
| `langchain.agents.middleware.types` (`AgentState` / `ModelRequest` / `ModelResponse` / `ContextT` / `ResponseT`) | 主路径 API | 未变 | 零 | 零 |
| `langchain_core.{messages,tools,callbacks,language_models,outputs}` | 主路径 API | 未变 | 零 | 零 |
| `langchain-community` (DuckDuckGo / Wikipedia) | 主路径 API | 未变(0.7.14-0.7.23 未触碰 community 路径) | 零 | 零 |
| `langgraph-checkpoint-sqlite` | 区间 `>=2.0,<4.0` | 区间未变 | 零 | 零 |
| `SubAgent` TypedDict required keys | `{name, description}`(system_prompt 在 0.7.13 降为 optional) | 未变 | 零 | 零 |
| `pinned_skills` + 每 subagent 独立 SkillsMiddleware (#6810/#6820, 0.7.23) | SDK 内部 skills 路径 | 新增可选 | **零**(Nexus skills 走自家 `nexus/backend/tools.py:242 run_skill`,**不调** SDK `SkillsMiddleware`) | 零 |
| skill tools 懒加载 (#6552, 0.7.22) | SDK 内部 SkillsMiddleware | 新增 | 零(Nexus 不调 SDK SkillsMiddleware) | 零 |
| `FilesystemMiddleware` 在 backend 存 blob (#6550, 0.7.21) | SDK 内部 FilesystemMiddleware | 新增可选(默认关) | 零(Nexus 用 `CompositeBackend`) | 零 |
| `StateBackend.upload_files` 二进制被错标 base64 (0.7.20) | SDK 内部 StateBackend | 修复 | 零(Nexus 用 `CompositeBackend`,不直接调 StateBackend) | 零 |
| 0.7.14–0.7.19 (chore(deps) only) | 依赖下限 bump | langchain / langchain-core / langsmith / langchain-anthropic / langchain-google-genai 累积提下限 | 零(仅 transitive 升级,无 SDK 内部 API 变化) | pyproject.toml 收紧 3 行 |

**结论:Nexus 在 0.7.23 下兼容,10 个补丁版本的全部改动均与 Nexus 接口层(HITL /
MemoryFilter / QualityGateMiddleware / 文件工具白名单 / 中间件签名 / 自家 skills
shell 入口)无交集;无新增修复;`pyproject.toml` 仅收紧 3 个 langchain/langchain-core/
langsmith 下限(对齐 deepagents 0.7.23 Requires-Dist),无新硬依赖引入。**

## 2. 复核结论(delete 防护 / Nexus skills vs SDK SkillsMiddleware)

### 2.1 既有防护事实(沿用 0.7.4 / 0.7.6 / 0.7.13 三轮确认)

- `nexus/backend/permissions/write_tools.py:29-40` `FILE_TOOLS` 精确白名单含
  字面 `"delete"`,`_WRITE_TOOL_PATTERNS` 含 `"_file"` 子串兜底;
- `tests/test_write_tools_helper.py` 锁定 3 个断言
  (`is_write_tool("delete") is True` / `delete_file` / `remove_file`);
- 基线锁测试 `_FS_TOOL_ORDER` 在 0.7.23 继续通过(10 个补丁版本字面值未变)。

### 2.2 Nexus skills 路径与 SDK SkillsMiddleware 关系(0.7.22-0.7.23 新增)

通过 `grep -rn -E "skill|Skill|SKILL" nexus/backend/ --include="*.py"` 确认:

**Nexus 的 skills 是自家实现**,完全不调 SDK 的 `SkillsMiddleware`:
- 入口:`nexus/backend/tools.py:242 run_skill(skill_name, skill_args)` —— 走
  `shell_run(command=..., cwd=SKILLS_DIR/<name>, timeout=120)` 调用用户在
  `~/.nexus/skills/<name>/SKILL.md` 里登记的 entrypoint 脚本;
- 注册表:`nexus/backend/skills/` 目录,`REGISTRY` + `scan_skills_dir()` 自管;
- 审计:`_audit_append` 写白名单 + 沙箱 cwd 锁。

**SDK 0.7.22-0.7.23 的 skills 改动对 Nexus 完全无影响**:
- 0.7.22 `skill tools 懒加载 (#6552)` —— SDK 内部 SkillsMiddleware 优化
- 0.7.23 `pinned_skills` (#6810) —— SDK 新增参数,Nexus 不传
- 0.7.23 `每 subagent 独立 SkillsMiddleware (#6820)` —— SDK 内部 bugfix

**WHY 不需要做适配**:Nexus 与 SDK skills 路径**无 import 重叠**,跑 LLM 时给模型
看到的"可用 skill"是 `run_skill` 这个工具描述 + Nexus system prompt 里列的
`SKILLS_DIR/<name>` 目录,跟 SDK `SkillsMiddleware` 注册的 skill 是两条平行
通道。SDK 的 skills 是 deepagents-code / Talon 服务的概念,跟服务端 SDK
agent 的接口层没关系。

### 2.3 复核结论

- ✅ 字面 `"delete"` 仍是 FilesystemMiddleware 注册的工具名(10 个补丁版本未变);
- ✅ `FILE_TOOLS` 白名单继续覆盖;
- ✅ `_FS_TOOL_ORDER` 基线锁测试改名 `_0_7_23`,断言体不动;
- ✅ Nexus skills 走自家 `run_skill` shell 入口,与 SDK SkillsMiddleware 零重叠;
- ✅ `StateBackend.upload_files` base64 修复对 Nexus 零影响(`CompositeBackend`
  不直接调 `StateBackend`);
- ⚠️ 10 个补丁版本新增 SDK 内部能力(skill 懒加载 / `pinned_skills` / subagent
  SkillsMiddleware 隔离 / backend blob 存储)均默认关闭或隔离在 SDK 内部,
  **无需代码改动**。

## 3. 依赖表

| 包 | 0.7.13 时期 | 0.7.23 要求 | pyproject.toml 调整 |
| --- | --- | --- | --- |
| `deepagents` | `0.7.13` 实装 | `>=0.7.0,<0.8.0` | ✅ 区间未变 |
| `langchain` | `1.4.0` | `>=1.4.3,<2.0.0` | ✅ `>=1.3.18` → `>=1.4.3` |
| `langchain-core` | `1.6.3` | `>=1.6.7,<2.0.0` | ✅ `>=1.6.1` → `>=1.6.7` |
| `langsmith` | `0.12.5` | `>=0.14.4` | ✅ `>=0.11.2` → `>=0.14.4` |
| `langchain-anthropic` | 未声明 | `>=1.7.5`(硬 Requires-Dist) | ⚠️ **不显式声明**:`pip install deepagents==0.7.23` 传递装上;Nexus 代码零引用(grep 验证),不膨胀依赖树 |
| `langchain-google-genai` | 未声明 | `>=4.4.0`(硬 Requires-Dist) | ⚠️ **不显式声明**:同上 |
| `langchain-openai` | `>=1.0.0` | 未变 | ✅ 区间未变 |
| `langchain-community` | `>=0.0.20` | 未变 | ✅ 区间未变 |
| `langgraph-checkpoint-sqlite` | `>=2.0,<4.0` | 未变 | ✅ 区间未变 |

`nexus/backend/requirements.txt` 收敛后:
```
deepagents==0.7.23
setproctitle>=0.2.0
```

(单行版本号 0.7.13 → 0.7.23,文件结构沿用 0.7.4 阶段的 11 行 → 2 行收敛结果。)

**WHY 不显式声明 langchain-anthropic / langchain-google-genai**:changelog 调研
确认 Nexus 代码零引用这两个包,deepagents 0.7.23 把它们列为硬 Requires-Dist 是
SDK 内部多 provider 探测需要。pip 传递装上即可,显式声明会让 Nexus 依赖树膨胀
且带来版本约束传递冲突风险。

## 4. 验证矩阵

```bash
# 安装验证
source .venv/bin/activate
python -c "import deepagents, langchain, langchain_core, langsmith; print(deepagents.__version__, langchain.__version__, langchain_core.__version__, langsmith.__version__)"
# 期望 deepagents=0.7.23, langchain>=1.4.3, langchain_core>=1.6.7, langsmith>=0.14.4

# 基线锁测试(改名后)
pytest tests/test_write_tools_helper.py::test_fs_tool_order_baseline_0_7_23 -v
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
# test_fs_tool_order_baseline_0_7_23 已计入)

# lint
ruff check nexus/ tests/
# 期望 All checks passed!
```

## 5. 后续升级 TODO(延续 0.7.4 / 0.7.6 / 0.7.13-alignment §5)

| # | 项 | 文件 | 工作量 | 优先级 |
| --- | --- | --- | --- | --- |
| 1 | 真 LLM E2E 验 `delete` 工具触发 HITL 拦截 | `e2e/journey-delete-hitl.spec.ts` | 2h | 中 |
| 2 | `HarnessProfile.general_purpose_subagent` 槽空了,评估是否接回自定 profile | `nexus/backend/profiles/tier_routing.py` | 1h | 低 |
| 3 | `delete_directory` 子串模式未来若 deepagents 新增目录删除工具,需补 `_dir` / `_directory` 子串 | `nexus/backend/permissions/write_tools.py` | 0.5h | 低 |
| 4 | 评估 `langchain-anthropic` / `langchain-google-genai` 是否升级为显式声明(0.8 升级时需重新评估 deepagents 硬依赖策略) | `pyproject.toml` | 0.5h | 低 |
| 5 | 评估 0.7.21 `FilesystemMiddleware` 在 backend 存 blob 是否对 Nexus `_backend.py:121` CompositeBackend 装配路径有优化空间(可减少内存中转) | `nexus/backend/agent/_backend.py` | 1h | 低 |
| 6 | 评估 0.7.23 `pinned_skills` 概念能否反向影响 Nexus 自家 skills 系统(语义一致 / 显式固定某个 skill 优先加载) | `nexus/backend/skills/` | 2h | 低 |

---

**总结**:0.7.13 → 0.7.23 跨 10 个补丁版本升级,**Nexus 接口层 0 行代码改动**
(`create_deep_agent` / `_FS_TOOL_ORDER` / `_ALL_FS_TOOL_NAMES` / `tool.name` /
langchain.* 主路径 API / Nexus 自家 skills 路径全部稳定);触及 transitive 依赖
升级(`langchain` 1.4.0 → ≥1.4.3 / `langchain-core` 1.6.3 → ≥1.6.7 / `langsmith`
0.12.5 → ≥0.14.4),通过 pyproject.toml 下限收紧对齐 deepagents 0.7.23 Requires-Dist;
基线锁测试改名版本号、断言体零改动;Nexus 自家 skills(走 shell 入口)与 SDK 新增
的 `SkillsMiddleware` / `pinned_skills` 路径**完全无重叠**,10 补丁期间 SDK 内部
skills 改动对 Nexus 零影响(详见 §2.2)。
```

- [ ] **Step 2: 校验文件行数与章节数**

Run:
```bash
cd /Users/yxb/projects/nexus && wc -l docs/operations/deepagents-0.7.23-alignment.md && grep -c "^## " docs/operations/deepagents-0.7.23-alignment.md
```
Expected: 行数约 150-165 行;`## ` 章节数 = 5。

- [ ] **Step 3: 暂不 commit(连同 Task 1-4 一起提交)**

---

## Task 6: 提交全部变更 + 跑全套验证

**Files:**
- Stage: `pyproject.toml`, `nexus/backend/requirements.txt`, `tests/test_write_tools_helper.py`, `docs/operations/deepagents-0.7.23-alignment.md`

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
`test_fs_tool_order_baseline_0_7_23` 已计入)。

- [ ] **Step 4: 四文件 stage + 单一 commit**

Run:
```bash
cd /Users/yxb/projects/nexus && git add pyproject.toml nexus/backend/requirements.txt tests/test_write_tools_helper.py docs/operations/deepagents-0.7.23-alignment.md && git -c commit.gpgsign=false commit -m "chore(deps): 升 deepagents 0.7.13 → 0.7.23(10 补丁)+ pyproject 下限收紧

- pip: deepagents 0.7.13 → 0.7.23 (跨 0.7.14/0.7.15/0.7.16/0.7.17/0.7.18/0.7.19/0.7.20/0.7.21/0.7.22/0.7.23)
- pyproject: langchain>=1.3.18 → >=1.4.3, langchain-core>=1.6.1 → >=1.6.7,
  langsmith>=0.11.2 → >=0.14.4 (对齐 deepagents 0.7.23 Requires-Dist)
- requirements.txt: deepagents==0.7.13 → ==0.7.23
- tests: test_fs_tool_order_baseline_0_7_13 改名 _0_7_23, 断言体不变
  (10 补丁期间 _FS_TOOL_ORDER 字面值未变)
- docs: 写 0.7.23 对齐报告, 复核 Nexus 自家 skills (run_skill 走 shell)
  与 SDK SkillsMiddleware/pinned_skills 零重叠, 0.7.22-0.7.23 改动对 Nexus 无影响
- Nexus 接口层: 0 行代码改动 (create_deep_agent / _FS_TOOL_ORDER /
  langchain.* 主路径 API / Nexus 自家 skills 路径全部稳定)"
```
Expected: 一个 commit,4 files changed。

- [ ] **Step 5: 验证 commit 落库**

Run:
```bash
cd /Users/yxb/projects/nexus && git log --oneline -3
```
Expected: 顶部是本次升级 commit,上一行是 9-11 的 0.7.13 升级 commit(`75ecbd0`)。

---

## 失败回退

若 Step 2 / Step 3 任一失败:

1. Task 1 的升级可逆:`pip install --force-reinstall 'deepagents==0.7.13' langchain==1.4.0 langchain_core==1.6.3 langsmith==0.12.5`
2. Task 2-5 的文件改动可逆:`git checkout -- pyproject.toml nexus/backend/requirements.txt tests/test_write_tools_helper.py docs/operations/deepagents-0.7.23-alignment.md`
3. 检查新引入的 drift,补充 `docs/operations/deepagents-0.7.23-alignment.md` §1 总览表 + §2 复核结论。
