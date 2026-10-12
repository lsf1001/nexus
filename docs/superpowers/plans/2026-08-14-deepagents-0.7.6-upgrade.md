# DeepAgents 0.7.4 → 0.7.6 升级实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Nexus `.venv` 的 `deepagents` 从 0.7.4 升到 0.7.6,清理 `nexus/backend/requirements.txt` 的冗余行,加 `_FS_TOOL_ORDER` 基线锁测试,并写 0.7.6 对齐报告。

**Architecture:** 单次补丁升级窗口。pyproject 区间约束(`>=0.7.0,<0.8.0`)不动,只动已装版本 + 三个伴生文件。TDD:基线锁测试先写后跑(实际会直接通过,因为 0.7.6 实际行为符合预期——此测试是给未来 0.7.7/0.8 升级窗口用的回归断言)。

**Tech Stack:** Python 3.11+, pytest 8+, pip, deepagents 0.7.6, ruff。

---

## 文件变更表

| 文件 | 动作 | 责任 |
| --- | --- | --- |
| `.venv` (运行时) | 升 `deepagents 0.7.4 → 0.7.6` | Task 1 |
| `nexus/backend/requirements.txt` | 删 10 行 + 改 1 行 + 留 1 行 | Task 2 |
| `tests/test_write_tools_helper.py` | 文件末尾追加 1 个新测试函数 | Task 3 |
| `docs/operations/deepagents-0.7.6-alignment.md` | 新建 | Task 4 |

`pyproject.toml` 不动(版本区间已覆盖 0.7.6)。`nexus/backend/permissions/write_tools.py` 不动(`delete` 防护已在 0.7.4 那轮完成)。`PathAwareHITLMiddleware` / `QualityGateMiddleware` 不动。

---

## Task 1: 升级 .venv 的 deepagents 到 0.7.6

**Files:**
- Modify: `.venv` (运行时,不可 git 跟踪)

- [ ] **Step 1: 确认当前已装版本**

Run:
```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && python -c "import deepagents; print(deepagents.__version__)"
```
Expected: `0.7.4`

- [ ] **Step 2: 升级 deepagents**

Run:
```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && pip install --upgrade 'deepagents>=0.7.6,<0.8.0'
```
Expected: 终端显示 `Successfully installed deepagents-0.7.6`(可能附带 langsmith / wcmatch 等 transitive 包的升级提示)。

- [ ] **Step 3: 验证版本**

Run:
```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && python -c "import deepagents; print(deepagents.__version__)"
```
Expected: `0.7.6`

- [ ] **Step 4: 验证 import 不挂(防止 deepagents 内部 API drift)**

Run:
```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && python -c "from deepagents.middleware.filesystem import _FS_TOOL_ORDER, _ALL_FS_TOOL_NAMES; from deepagents import create_deep_agent; print('OK', _FS_TOOL_ORDER[:3])"
```
Expected: `OK ('ls', 'read_file', 'write_file')`

---

## Task 2: 收敛 nexus/backend/requirements.txt

**Files:**
- Modify: `nexus/backend/requirements.txt:1-11`(整文件重写为 2 行)

- [ ] **Step 1: 备份现状(以便 diff 校验)**

Run:
```bash
cd /Users/yxb/projects/nexus && cp nexus/backend/requirements.txt /tmp/requirements.txt.before
```

- [ ] **Step 2: 重写文件为 2 行**

将 `nexus/backend/requirements.txt` 完整内容替换为:

```
deepagents==0.7.6
setproctitle>=0.2.0
```

(用 Edit 工具,`old_string` 是原 11 行全文,`new_string` 是上面 2 行)

- [ ] **Step 3: 校验行数与内容**

Run:
```bash
cd /Users/yxb/projects/nexus && wc -l nexus/backend/requirements.txt && echo "---" && cat nexus/backend/requirements.txt
```
Expected:
```
       2 nexus/backend/requirements.txt
---
deepagents==0.7.6
setproctitle>=0.2.0
```

- [ ] **Step 4: 验证 setproctitle 仍可 import(防止误删)—— 但本任务不动 venv,仅验证现有 venv 有这个包**

Run:
```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && python -c "import setproctitle; print(setproctitle.__version__)"
```
Expected: 类似 `1.3.3` 的版本号(无 ImportError)。

- [ ] **Step 5: 暂不 commit(后续任务一起提交)**

Task 3 / Task 4 的变更一并 commit。

---

## Task 3: 加 _FS_TOOL_ORDER 基线锁测试(TDD)

**Files:**
- Modify: `tests/test_write_tools_helper.py`(在文件末尾追加)

- [ ] **Step 1: 读文件末尾,确认追加位置**

Read `tests/test_write_tools_helper.py` 最后 25 行,确认是 `test_hitl_middleware_invokes_helper_for_interrupt` 的 `mw._should_interrupt(tool_call)` 这一行收尾。

- [ ] **Step 2: 在文件末尾追加新测试函数**

Edit `tests/test_write_tools_helper.py`,把 `old_string` 设为文件最后一个 `def test_...` 函数体的最后一行(以 `mw._should_interrupt(tool_call)` 结尾的整段代码),`new_string` 在该段代码之后**追加**(不是替换):

```python


def test_fs_tool_order_baseline_0_7_6() -> None:
    """锁 deepagents FilesystemMiddleware._FS_TOOL_ORDER 在 0.7.6 的字面顺序。

    WHY: HITL / MemoryFilter / QualityGateMiddleware 拦截逻辑依赖字面工具名
    ('delete' / 'write_file' / ...)。若 0.7.7 / 0.8 改顺序或改名,
    is_write_tool() 仍能兜底(子串匹配),但 LLM 工具提示的展示顺序会变,
    触发 e2e flake。此断言作为 0.7.x 补丁升级窗口的基线锁;未来 0.7.7 / 0.8
    升级时按新字面值更新即可。
    """
    from deepagents.middleware.filesystem import _FS_TOOL_ORDER, _ALL_FS_TOOL_NAMES

    assert _FS_TOOL_ORDER == (
        "ls", "read_file", "write_file", "edit_file", "delete", "glob", "grep",
    )
    assert "delete" in _ALL_FS_TOOL_NAMES
    assert "execute" in _ALL_FS_TOOL_NAMES
```

> **TDD 注**:本测试在 0.7.6 实际行为下应当直接 PASS(因为 0.7.6 的
> `_FS_TOOL_ORDER` 确实是这个 tuple)。这一步不是先红再绿,而是
> **写一个对当前版本正确的回归断言**,作为未来 0.7.7 / 0.8 升级窗口的
> 锚点。

- [ ] **Step 3: 跑新测试,确认 PASS**

Run:
```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && pytest tests/test_write_tools_helper.py::test_fs_tool_order_baseline_0_7_6 -v
```
Expected:
```
tests/test_write_tools_helper.py::test_fs_tool_order_baseline_0_7_6 PASSED
```

- [ ] **Step 4: 跑 test_write_tools_helper.py 整文件,确认无回归**

Run:
```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate && pytest tests/test_write_tools_helper.py -v
```
Expected: 全 PASS(原 14 个 + 新加的 1 个 = 15 个)。

- [ ] **Step 5: 暂不 commit(后续任务一起提交)**

---

## Task 4: 写 docs/operations/deepagents-0.7.6-alignment.md

**Files:**
- Create: `docs/operations/deepagents-0.7.6-alignment.md`

- [ ] **Step 1: 用 Write 工具新建文件,内容如下**

```markdown
# DeepAgents 0.7.6 升级对齐报告

> **目的**:记录 Nexus 从 deepagents 0.7.4 升级到 0.7.6 的 API drift、修复点、
> 回归验证矩阵,作为后续 0.7.x / 0.8 升级的基线。
>
> **环境**:deepagents `0.7.6`(2026-08-13)、langchain `1.3.14`、
> langchain-core `1.5.3`、langsmith `0.10.15`(2026-08-14 实装)。
>
> **前置报告**:`docs/operations/deepagents-0.7.4-alignment.md`(已存在,
> 本文为补丁升级延续)。

## 1. 总览

| 维度 | 0.7.4 行为 | 0.7.6 行为 | Nexus 影响 | 修复点 |
| --- | --- | --- | --- | --- |
| `FilesystemMiddleware._FS_TOOL_ORDER` | `("ls","read_file","write_file","edit_file","delete","glob","grep")` | **未变** | 零 | 新基线锁测试 `tests/test_write_tools_helper.py::test_fs_tool_order_baseline_0_7_6` |
| `delete` 工具 `tool.name` | 字面 `"delete"` | 字面 `"delete"`(未变) | 零 | `FILE_TOOLS` 白名单在 0.7.4 那轮已覆盖 |
| PR #5229 "exact-file delete target resolution first-match-wins" | SDK 内部路径解析:workspace allowlist 边界用例 first-match-winds | 改进 | **零**(SDK 内部权限校验,Nexus HITL 只看工具名) | 零 |
| PR #5300 "Expose the execute exit code in SDK artifacts" (0.7.4) | — | `execute` 工具返回 SDK artifacts 时附带 exit_code | 零(Nexus 不解析 SDK artifacts) | 零 |
| PR #5326 "Identify SDK provider classes that support files" (0.7.5) | SDK 内部 | SDK 内部 | 零 | 零 |
| PR #5470 "Offload conversation history to a distinct session ID when summarizing" (0.7.6) | summary 时所有对话历史归在同一 session | summary 时对话历史搬到 distinct session ID | 零(Nexus 用 MemoryMiddleware + 跨会话持久化,不走 summary 路径) | 零 |

**结论:Nexus 在 0.7.6 下兼容,3 处需关注的 drift 均确认无影响,无新增修复。**

## 2. 复核结论(delete 防护 / PR #5229)

### 2.1 既有防护事实

`docs/operations/deepagents-0.7.4-alignment.md` §2.2 已记录:

- `nexus/backend/permissions/write_tools.py:29-40` `FILE_TOOLS` 精确白名单
  含字面 `"delete"`;
- `_WRITE_TOOL_PATTERNS` 含 `"_file"` 子串兜底(未来改名 `delete_file`
  自动覆盖);
- `tests/test_write_tools_helper.py` 锁定三个断言
  (`is_write_tool("delete") is True` / `delete_file` / `remove_file`)。

### 2.2 PR #5229 影响范围(事实核查)

通过 `inspect.getsource` 直读 `deepagents/middleware/filesystem.py`
(0.7.6 实装于 `.venv`)确认:

- `_FS_TOOL_ORDER` 仍为 `("ls","read_file","write_file","edit_file",
  "delete","glob","grep")`;
- `_ALL_FS_TOOL_NAMES` 为 `frozenset(_FS_TOOL_ORDER) | {"execute"}`;
- `delete` 工具注册的 `tool.name == "delete"`。

**PR #5229 影响范围**:deepagents SDK 内部对 `delete` 命令的目标路径
进行权限校验时的 first-match-winds 解析策略(#5113 issue:workspace
allowlist 边界用例)。**与 Nexus HITL/MemoryFilter/QualityGateMiddleware
三层拦截路径无交集**——三层只看工具名(`is_write_tool("delete")` 返回
`True` 才会进 HITL 流程),不看 SDK 内部路径解析逻辑。

### 2.3 复核结论

- ✅ 字面 `"delete"` 仍是 FilesystemMiddleware 注册的工具名;
- ✅ `FILE_TOOLS` 白名单已覆盖;
- ✅ 新增 `test_fs_tool_order_baseline_0_7_6` 基线锁测试,锁字面顺序;
- ⚠️ PR #5229 是 SDK 内部权限校验改进,**对 Nexus 是好事**(更严格
  的路径解析),无需任何代码改动。

## 3. 依赖表

| 包 | 0.7.4 时期 | 0.7.6 要求 | pyproject.toml |
| --- | --- | --- | --- |
| `deepagents` | `0.7.4` 实装 | `>=0.7.0,<0.8.0` | ✅ 区间未变 |
| `langchain` | `1.3.14` | `>=1.3.14,<2.0.0` | ✅ 显式声明 |
| `langchain-core` | `1.5.3` | `>=1.5.0,<2.0.0` | ✅ 显式声明 |
| `langsmith` | `0.10.15` | `>=0.10.9` | ✅ 显式声明 |

`nexus/backend/requirements.txt` 收敛后:

```
deepagents==0.7.6
setproctitle>=0.2.0
```

(其余 10 行与 pyproject.toml 重叠项已删,`setproctitle` 是 pyproject 未声明
的运行时小依赖,保留作 wheel 兜底)

**WHY 显式声明 langchain / langchain-core / langsmith 下限**:0.7 在 venv
`pip install -e .` 时不会自动装到满足 `Requires-Dist` 的版本,会导致
import 时 `ModuleNotFoundError` 或 API 漂移。补三个下限 + 上限避免漂到 2.x。

## 4. 验证矩阵

```bash
# 安装验证
source .venv/bin/activate
python -c "import deepagents; print(deepagents.__version__)"
# 期望 deepagents=0.7.6

# 新基线锁测试
pytest tests/test_write_tools_helper.py::test_fs_tool_order_baseline_0_7_6 -v
# 期望 1/1 PASS

# 既有 delete 防护测试(防止回归)
pytest tests/test_write_tools_helper.py -v
# 期望 全过(15 个,含 test_is_write_tool_known_write_returns_true 锁 'delete' 为 True)

# pytest 全量
pytest tests/ -q --tb=line
# 期望 全过(基线 1004 passed, 12 skipped, 0 failed)

# lint
ruff check nexus/ tests/
# 期望 All checks passed!
```

## 5. 后续升级 TODO(延续 0.7.4-alignment §5)

| # | 项 | 文件 | 工作量 | 优先级 |
| --- | --- | --- | --- | --- |
| 1 | 真 LLM E2E 验 `delete` 工具触发 HITL 拦截 | `e2e/journey-delete-hitl.spec.ts` | 2h | 中 |
| 2 | `HarnessProfile.general_purpose_subagent` 槽空了,评估是否接回自定 profile | `nexus/backend/profiles/tier_routing.py` | 1h | 低 |
| 3 | `delete_directory` 子串模式未来若 deepagents 新增目录删除工具,需补 `_dir` / `_directory` 子串 | `nexus/backend/permissions/write_tools.py` | 0.5h | 低 |

---

**总结**:0.7.4 → 0.7.6 升级仅触及 SDK 内部(`delete` 路径解析 / `execute`
exit code / provider files 识别 / summary session offload),**全部与 Nexus
接口层无交集**;`_FS_TOOL_ORDER` 字面顺序未变,`delete` 防护在 0.7.4 那轮
已完成且通过 1004 个测试验证;`HarnessProfile` / TypedDict /
`create_deep_agent` 签名 0.7.6 沿用 0.7.4,基线测试零修改通过。
```

- [ ] **Step 2: 校验文件行数与章节数**

Run:
```bash
cd /Users/yxb/projects/nexus && wc -l docs/operations/deepagents-0.7.6-alignment.md && grep -c "^## " docs/operations/deepagents-0.7.6-alignment.md
```
Expected: 行数约 145-155 行(参考 0.7.4 文档 181 行);`## ` 章节数 = 5。

- [ ] **Step 3: 暂不 commit(连同 Task 2 / Task 3 一起提交)**

---

## Task 5: 提交全部变更 + 跑全套验证

**Files:**
- Stage: `nexus/backend/requirements.txt`, `tests/test_write_tools_helper.py`, `docs/operations/deepagents-0.7.6-alignment.md`

- [ ] **Step 1: 确认 git status**

Run:
```bash
cd /Users/yxb/projects/nexus && git status --short
```
Expected: 三个 modified/new 文件,且**没有** `.venv/`、`.pytest_cache/`、其他无关文件。

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
Expected: 全过(基线 1004 passed, 12 skipped, 0 failed;新增的 `test_fs_tool_order_baseline_0_7_6` 已计入)。

- [ ] **Step 4: 三文件 stage + 单一 commit**

Run:
```bash
cd /Users/yxb/projects/nexus && git add nexus/backend/requirements.txt tests/test_write_tools_helper.py docs/operations/deepagents-0.7.6-alignment.md && git -c commit.gpgsign=false commit -m "chore(deps): 升 deepagents 0.7.4 → 0.7.6 + requirements 收敛 + FS tool order 基线锁

- pip: deepagents 0.7.4 → 0.7.6 (两个补丁版本,皆 fix)
- requirements.txt: 删 10 行与 pyproject 重叠项,留 deepagents==0.7.6 + setproctitle
- tests: 加 test_fs_tool_order_baseline_0_7_6 锁字面工具顺序
- docs: 写 0.7.6 对齐报告,复核 PR #5229 对 Nexus 无影响"
```

Expected: 一个 commit,3 files changed。

- [ ] **Step 5: 验证 commit 落库**

Run:
```bash
cd /Users/yxb/projects/nexus && git log --oneline -3
```
Expected: 顶部是本次升级 commit,上一行是 spec 文档 commit(`6a20f7c`)。

---

## 失败回退

若 Step 2 / Step 3 任一失败:

1. Task 1 的升级可逆:`pip install --force-reinstall 'deepagents==0.7.4'`
2. Task 2 / Task 3 / Task 4 的文件改动可逆:`git checkout -- nexus/backend/requirements.txt tests/test_write_tools_helper.py docs/operations/deepagents-0.7.6-alignment.md`
3. 检查新引入的 drift,补充 `docs/operations/deepagents-0.7.6-alignment.md` §1 总览表。