# DeepAgents 0.7.6 升级对齐报告

> **目的**:记录 Nexus 从 deepagents 0.7.4 升级到 0.7.6 的 API drift、修复点、
> 回归验证矩阵,作为后续 0.7.x / 0.8 升级的基线。
>
> **环境**:deepagents `0.7.6`(2026-08-13)、langchain `1.3.14`、
> langchain-core `1.5.4`、langchain-anthropic `1.5.6`、langsmith `0.10.15`
> (2026-08-14 实装实测)。
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