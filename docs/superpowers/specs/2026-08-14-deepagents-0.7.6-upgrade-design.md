# DeepAgents 0.7.4 → 0.7.6 升级设计

> **日期**：2026-08-14
> **作者**：Claude (brainstorming)
> **范围**：Nexus 仓库内 deepagents 依赖升级、依赖清单收敛、回归基线锁

## 1. 背景

Nexus 当前 `.venv` 实装 `deepagents 0.7.4`（2026-08-04 发布），PyPI 最新
版本为 `0.7.6`（2026-08-13）。落后两个补丁版本：

- **0.7.5** (2026-08-06): Identify SDK provider classes that support files (#5326)
- **0.7.6** (2026-08-13): Offload conversation history to a distinct session ID when summarizing (#5470)

两者都是 bug fix，无 breaking change 标注。

**前置基线**：`docs/operations/deepagents-0.7.4-alignment.md` 已记录 0.6.12
→ 0.7.4 升级的三处 drift（`StoreBackend.namespace` 强制 / `delete` 工具
防护 / `HarnessProfile.materialize_extra_middleware` 风险评估），全部已修。
本文是该基线在 0.7.4 → 0.7.6 补丁升级窗口的延续。

**已知未解决**：0.7.4 → 0.7.5 → 0.7.6 release notes 中 PR #5229
("Fixed exact-file delete target resolution in the SDK using
first-match-wins behavior") 的影响需复核——结论是 SDK 内部路径解析
逻辑变化，不触及 Nexus 拦截层（详见 §3）。

## 2. 升级本身

### 2.1 版本约束

`pyproject.toml` 第 31 行现有约束：

```toml
"deepagents>=0.7.0,<0.8.0"
```

**保持区间不动**，仅升级已装版本到 `0.7.6`。理由：

- `<0.8.0` 上限守住 0.8 升级窗口（0.8 是 LangChain 2.x 同发窗口，预期
  breaking）；
- `>=0.7.0` 下限在 0.7.4 那轮对齐中已通过测试基线锁定；
- 0.7.6 → 0.7.7（如果有）若仍是 fix，区间不需要再收紧。

### 2.2 升级命令

```bash
source .venv/bin/activate
pip install --upgrade 'deepagents>=0.7.6,<0.8.0'
python -c "import deepagents; print(deepagents.__version__)"
# 期望:0.7.6
```

### 2.3 配套依赖

0.7.6 PyPI 元数据要求（与 0.7.4 一致）：

| 包 | 要求 | pyproject 现状 |
| --- | --- | --- |
| `langchain` | `>=1.3.14,<2.0.0` | ✅ 已锁 |
| `langchain-core` | `>=1.5.0,<2.0.0` | ✅ 已锁 |
| `langsmith` | `>=0.10.9` | ✅ 已锁（下限） |
| `langchain-anthropic` | `<2.0.0,>=1.5.4` | ✅ 由 deepagents 传递 |

无传递依赖漂移风险。

## 3. `delete` 工具防护复核（PR #5229 影响评估）

### 3.1 既有防护事实

`docs/operations/deepagents-0.7.4-alignment.md` §2.2 已记录：

- `nexus/backend/permissions/write_tools.py:29-40` `FILE_TOOLS` 精确白名单
  含字面 `"delete"`；
- `_WRITE_TOOL_PATTERNS` 含 `"_file"` 子串兜底（未来改名 `delete_file`
  自动覆盖）；
- `tests/test_write_tools_helper.py:108-131` 锁定三个断言
  (`is_write_tool("delete") is True` / `delete_file` / `remove_file`)。

### 3.2 PR #5229 实际改动（事实核查）

通过 `inspect.getsource` 直读 `deepagents/middleware/filesystem.py`
（0.7.4 实装于 `.venv`）确认：

- `_FS_TOOL_ORDER` 仍为 `("ls", "read_file", "write_file", "edit_file",
  "delete", "glob", "grep")`（第 1324 行）；
- `_ALL_FS_TOOL_NAMES` 为 `frozenset(_FS_TOOL_ORDER) | {"execute"}`
  （第 1325 行）；
- `delete` 工具注册的 `tool.name == "delete"`（`_create_delete_tool`
  第 177 行），与 0.7.4 对齐报告 §2.2 描述一致。

**PR #5229 影响范围**：deepagents SDK 内部对 `delete` 命令的目标路径
进行权限校验时的 first-match-winds 解析策略（#5113 issue：workspace
allowlist 边界用例）。**与 Nexus HITL/MemoryFilter/QualityGateMiddleware
三层拦截路径无交集**——三层只看工具名（`is_write_tool("delete")` 返回
`True` 才会进 HITL 流程），不看 SDK 内部路径解析逻辑。

### 3.3 复核结论

- ✅ 字面 `"delete"` 仍是 FilesystemMiddleware 注册的工具名；
- ✅ `FILE_TOOLS` 白名单已覆盖；
- ✅ 测试基线已锁；
- ⚠️ PR #5229 是 SDK 内部权限校验改进，**对 Nexus 是好事**（更严格
  的路径解析），无需任何代码改动。

## 4. `requirements.txt` 收敛

### 4.1 当前状态

`nexus/backend/requirements.txt` 11 行，与 `pyproject.toml` 严重重叠，
且含一个 pyproject 未声明的运行时依赖 `setproctitle>=0.2.0`。

### 4.2 处置

| 原行 | 内容 | 处置 |
| --- | --- | --- |
| 1 | `fastapi>=0.100.0` | **删** |
| 2 | `uvicorn[standard]>=0.23.0` | **删** |
| 3 | `deepagents>=0.5.3` | **改 `==0.7.6`** |
| 4 | `langchain-openai>=1.0.0` | **删** |
| 5 | `langchain-community>=0.0.20` | **删** |
| 6 | `ddgs>=5.0.0` | **删** |
| 7 | `beautifulsoup4>=4.12.0` | **删** |
| 8 | `aiosqlite>=0.19.0` | **删** |
| 9 | `pydantic>=2.0.0` | **删** |
| 10 | `python-dotenv>=1.0.0` | **删** |
| 11 | `setproctitle>=0.2.0` | **保留** |

### 4.3 收敛后

`requirements.txt` 只剩两行：

```
deepagents==0.7.6
setproctitle>=0.2.0
```

### 4.4 设计理由

- **pyproject 是真理源**：构建/发布/编辑器走 `pip install -e .`；
- **requirements.txt 保留作 wheel 兜底**：CI / 部署脚本可以走
  `pip install -r requirements.txt` 这条快路径，不必每次全树构建；
- **`setproctitle` 留 requirements**：它是运行时小依赖（用于
  `nexus-gateway` 进程名 setproctitle），放 requirements 比 pyproject
  直观；不放 pyproject 避免它污染发布 wheel 的 dependencies 列表。

## 5. `_FS_TOOL_ORDER` 基线锁测试

### 5.1 加在哪里

`tests/test_write_tools_helper.py`（现有 8 个测试文件，保持一处真相）。

### 5.2 新增测试

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

### 5.3 不动什么

- `tests/test_deepagents_integration.py` 锁的是 `HarnessProfile` 字段
  基线（0.7.4 已稳定），**不动**；
- `nexus/backend/permissions/write_tools.py` 的 `FILE_TOOLS` 已在
  0.7.4 那轮加 `"delete"`，**不动**；
- `PathAwareHITLMiddleware` / `QualityGateMiddleware` 业务逻辑
  **不动**。

## 6. 对齐报告

写 `docs/operations/deepagents-0.7.6-alignment.md`，体例同
`docs/operations/deepagents-0.7.4-alignment.md`：

1. **总览表**：0.7.4 → 0.7.6 三条变更（offload conversation history /
   provider files support / exact-file delete target）逐条标注 Nexus 影响；
2. **复核结论**：§3 内容浓缩——`delete` 防护已在，PR #5229 不影响 Nexus；
3. **依赖表**：pyproject 区间约束不变；
4. **验证矩阵**：pytest / ruff / 新基线锁测试；
5. **后续 TODO**：从 0.7.4-alignment §5 搬过来未解项（真 LLM E2E 验证
   delete HITL / subagent profile 评估 / `delete_directory` 子串兜底），
   标注"延续到 0.7.6 仍未解"。

## 7. 验证矩阵

```bash
# 安装
source .venv/bin/activate
pip install --upgrade 'deepagents>=0.7.6,<0.8.0'
python -c "import deepagents; print(deepagents.__version__)"
# 期望:0.7.6

# 单元测试
pytest tests/ -q --tb=line
# 期望:全过(基线 1004 passed, 12 skipped, 0 failed)

# 新基线锁测试
pytest tests/test_write_tools_helper.py::test_fs_tool_order_baseline_0_7_6 -v
# 期望:1/1 PASS

# 既有 delete 防护测试(防止回归)
pytest tests/test_write_tools_helper.py -v
# 期望:全过(含 test_is_write_tool_known_write_returns_true 锁 'delete' 为 True)

# lint
ruff check nexus/ tests/
# 期望:All checks passed!
```

## 8. 失败回退

若升级后任一验证步骤失败：

1. `pip install --force-reinstall 'deepagents==0.7.4'` 回退；
2. 检查是否有新工具注册到 `_FS_TOOL_ORDER`；
3. 若 `MemoryMiddleware` / `FilesystemMiddleware` 出现新行为，更新
   `nexus/backend/permissions/write_tools.py` `FILE_TOOLS` ；
4. 在 `docs/operations/deepagents-0.7.6-alignment.md` §1 总览表追加
   drift 行。

## 9. 后续 TODO（延续 0.7.4-alignment §5）

| # | 项 | 文件 | 工作量 | 优先级 |
| --- | --- | --- | --- | --- |
| 1 | 真 LLM E2E 验 `delete` 工具触发 HITL 拦截 | `e2e/journey-delete-hitl.spec.ts` | 2h | 中 |
| 2 | `HarnessProfile.general_purpose_subagent` 槽空了,评估是否接回自定 profile | `nexus/backend/profiles/tier_routing.py` | 1h | 低 |
| 3 | `delete_directory` 子串模式未来若 deepagents 新增目录删除工具,需补 `_dir` / `_directory` 子串 | `nexus/backend/permissions/write_tools.py` | 0.5h | 低 |