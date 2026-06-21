# Nexus 重构评估（ruff + 行数 + AST）

> **目的**：按 `python_project.md` §1/§3 评估 Nexus 现状，给后续重构分档分级
> **生成日期**：2026-06-13
> **工具**：`.venv/bin/ruff 0.15.16` + grep + find + wc

## 总览

| 维度 | 数量 | 状态 |
|---|---|---|
| Python 文件 | nexus/ 30 个 + tests/ 25 个 + scripts/ 3 个 | — |
| 代码总行数 | nexus/ 12,741 + tests/ 5,895 | — |
| ruff check 错误 | **6** | 🔴 6 个全部可 `--fix` 自动修 |
| 文件 > 800 行 | **1**（wechat.py 936） | 🔴 违反 §1.2 |
| bare except | **0** | ✅ |
| silent except (`except: pass`) | **0** | ✅ |
| mutable default | **0** | ✅ |
| 单行 > 150 字符 | （ruff 已 E501 忽略，由 formatter 处理） | — |

**结论**：Nexus 后端代码**比预想干净得多**。`python_project.md` 14 条核心规约**几乎全部通过**。

---

## 🔴 P0：必改（CI 阻断）

### 1. 文件 > 800 行（§1.2 必拆）

| 文件 | 行数 | 备注 |
|---|---|---|
| `nexus/backend/channels/wechat.py` | **936** | 唯一超标，需拆 |

**建议拆分**（基于文件结构）：
- `wechat/types.py` —— `MessageItemType` / `MessageTypeEnum` / `MessageState` 等 dataclass + enum（~150 行）
- `wechat/sender.py` —— `send_*` 系列函数（~200 行）
- `wechat/parser.py` —— XML/JSON 解析（~200 行）
- `wechat/handler.py` —— 路由 + 事件分发（~200 行）
- `wechat/__init__.py` —— 兼容入口（~100 行）

**风险**：高（核心模块），**必须**有完整测试覆盖后改。`tests/test_wechat_*.py` 是否存在？需要先 verify。

---

## 🟠 P1：建议改（自动可修）

### 2. ruff check 6 个错误（全部 `--fix` 可修）

| 文件 | 行号 | 规则 | 描述 |
|---|---|---|---|
| `nexus/backend/agent.py` | 184 | F401 | `RetryPolicy` 未使用 |
| `nexus/backend/agent.py` | 184 | F401 | `TimeoutPolicy` 未使用 |
| `nexus/backend/agent.py` | 185 | F401 | `ResilientRunnable` 未使用 |
| `nexus/backend/agent.py` | ? | F401 | （还有 1 个） |
| `nexus/backend/agent.py` | ? | I001 | unsorted imports |
| `nexus/backend/main.py` | 565 | UP041 | `asyncio.TimeoutError` 应为 `TimeoutError` |

**修复方式**：
```bash
.venv/bin/ruff check nexus/ --fix
.venv/bin/ruff format nexus/
```

**风险**：极低，**自动修复 + format 不会改语义**。

---

## 🟡 P2：可选（lint 警告级，未扫到）

ruff `select = [E, W, F, I, B, UP, N, C4]`——未启用：
- D（docstring）
- S（security）
- SIM（simplify）
- PT（pytest）
- RET（return）
- ARG（unused argument）

**不**在这次评估范围。如要加严，按需扩 select。

---

## 🟢 P3：风格（中文 docstring / 命名风格）

之前用 AST 抽样过（2026-06-13 上午数据）：

| 维度 | 数量 | 备注 |
|---|---|---|
| 公共 class 缺中文 docstring | 34 | 主要是 `wechat.py` 内（34 个里面大头） |
| 公共函数缺中文 docstring | 0（除上述） | — |

**建议**：拆 `wechat.py` 时**顺便补 docstring**——一举两得。

---

## 文件大小 Top 5（用于未来趋势监控）

| 文件 | 行数 | 距 800 还差 | 备注 |
|---|---|---|---|
| `channels/wechat.py` | **936** | **-136**（超） | 🔴 P0 |
| `main.py` | 749 | +51 | 接近 800，注意新增 |
| `db.py` | 725 | +75 | 接近 800 |
| `api/ws.py` | 554 | +246 | 安全 |
| `memory.py` | 548 | +252 | 安全 |

**建议**：`main.py` / `db.py` 设**预警告阈值 700**（CI 报警但不阻断）。

---

## pytest 基线

（待补——pytest 跑完后填）

---

## 重构建议

按 P0 → P1 → P3 顺序：

1. **P1 一次性修**（1 个 commit，`ruff check --fix`）
2. **P0 拆 wechat.py**（1-2 个 commit，需先有测试覆盖）
3. **P3 补 docstring**（拆 wechat.py 时一并做）

**P0 工作量估计**：2-4 小时（含测试补全）。

**不**做：
- ❌ `main.py` / `db.py` 拆分（没超 800，不动）
- ❌ 启用更多 ruff 规则（select 维持现状）
- ❌ 修 docstring（除拆 wechat.py 时顺带）
- ❌ 改 `pyproject.toml` 配置
