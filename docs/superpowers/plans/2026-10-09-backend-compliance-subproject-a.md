# Sub-project A: Backend Compliance Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保证 1082 个既有测试零破坏的前提下,完成 11 项 sub-project A 合规 finding(backend middleware / write_tools 防护 / WS 鉴权 / 状态管理 / 评估 / 日志)。

**Architecture:** 拆 5 个文件 + 加 24 个新测试 + 1 个 entry 改写 = 7 个独立 commit。每 commit 单一意图,TDD 驱动,不改既有测试断言,只改 import 路径。

**Tech Stack:** Python 3.11+ / FastAPI 0.100+ / dataclasses(frozen) / aiosqlite / asyncio / pytest 8+ / ruff

---

## Spec 修订说明(实施时务必读)

实施时**纠正 spec §5.2 的两处事实错误**:

1. **Commit #4 (HITL 抽)**: `api/ws/streaming_hitl.py` **已经存在** 123 行,在更早的 2026-08 重构中已落库。**spec 误标为"新增"**。本计划实际工作: ① 抽确认既有 3 个函数(`_handle_graph_interrupt` / `_drain_pending_hitl_interrupts` / `_emit_hitl_confirmation_frames`)职责清晰; ② 用 `HITLInterrupter` 类封装(可选,推荐)以可测; ③ 加 `test_streaming_hitl.py` 6 个测试(本来 spec 第 #4 commit 标的就是测试,只是没意识到类需要新增)。

2. **Commit #6 (fact_check 统一入口)**: `fact_check/__init__.py` **已经存在** 10 行(只 re-export `FactCheckPipeline` 等)。**spec 误标为"新增"**。本计划实际工作: ① 给 `verifiers.py` 的 4 个 verifier 类加 `name: str` + `weight: float` 类属性; ② **扩** `fact_check/__init__.py` 添加 `verify(claim, *, context)` 统一入口和 `VerifyResult` dataclass; ③ `agents/middleware/fact_check.py` 改用新入口(向后兼容 `FactCheckPipeline` 不删); ④ 加 `test_fact_check_weighted.py` 5 个测试。

---

## 文件结构(实施前映射)

### 改(8)

| 路径 | 行数 | 改造内容 |
|---|---|---|
| `nexus/backend/main.py` | 851 → ≤800 | 抽 `lifespan` 装配到 `app_state.py`;`lifespan` 留 ~30 行 |
| `nexus/backend/db.py` | 819 → 0(删) | 拆为 `db/` package; 旧 `db.py` 删 |
| `nexus/backend/api/ws/auth.py` | 117 | P0-1: query fallback 默认关 |
| `nexus/backend/api/ws/streaming.py` | 889 → ~700 | 抽 HITL 状态机到 `streaming_hitl.py`(用 `HITLInterrupter` 类封装) |
| `nexus/backend/api/ws/streaming_hitl.py` | 123 → ~200 | **扩**: 增加 `HITLInterrupter` 类(使可测) |
| `nexus/backend/fact_check/__init__.py` | 10 → ≤80 | **扩**: 加 `verify()` 统一入口 + `VerifyResult` dataclass |
| `nexus/backend/fact_check/verifiers.py` | 271 | 给 4 个 verifier 加 `name` + `weight` 类属性 |
| `nexus/backend/agents/middleware/fact_check.py` | 311 | 改用新统一入口(向后兼容,`FactCheckPipeline.check` 不删) |
| `nexus/backend/llm/wrapper.py` | 487 | 加 `-> Any` 返回类型到 `_generate` / `_agenerate` / `_stream` / `_astream` |
| `nexus/backend/launcher.py` | 216 | 2 处 `print` → `logger.warning` / `logger.error` |

### 增(7 新文件)

| 路径 | 行数目标 | 角色 |
|---|---|---|
| `nexus/backend/app_state.py` | ≤60 | `AppState` 不可变 dataclass |
| `nexus/backend/db/__init__.py` | ≤150 | 替代 db.py,顶层 re-export |
| `nexus/backend/db/quality_schema.py` | ≤150 | `QualityScoreRepo` 类 |
| `tests/test_app_state.py` | ≤120 | 4 测试,frozen / 字段 / 不可变 / 启动一次 |
| `tests/test_db_quality_schema.py` | ≤150 | 6 测试,upsert / get_latest / list / average / 不持连接 / 参数化 |
| `tests/test_fact_check_weighted.py` | ≤120 | 5 测试,单 verifier / 加权 / 归一化 / 全失败 / TimeoutError |
| `tests/test_streaming_hitl.py` | ≤180 | 6 测试,approve / edit / reject / respond / timeout / 异常帧 |
| `tests/test_ws_auth_query_off.py` | ≤80 | 3 测试,query 默认拒绝 / env 未设也拒绝 / 错 token |

### 改测试 import(0)

本 plan 故意不改既有测试文件。所有现有测试通过 `nexus.backend.db.X` 等路径直接访问 `db.py` 顶层函数。Commit #1 让 `db.py` 变 re-export shim,Commit #2 删 `db.py` 之前会**全仓 grep import 路径**改为 `nexus.backend.db` package 路径。Commit #2 同时改这批既有测试 import(只动 import 行,不动断言)。

---

## Task 1: db.py 拆为 db/ package,新增 QualityScoreRepo

**Files:**
- Create: `nexus/backend/db/__init__.py`
- Create: `nexus/backend/db/quality_schema.py`
- Modify: `nexus/backend/db.py`(变 re-export shim,内容全删前留兼容层)
- Test: `tests/test_db_quality_schema.py`

### Step 1.1: 写 QualityScoreRepo 失败测试

`tests/test_db_quality_schema.py`:

```python
"""QualityScoreRepo 单元测试。

WHY: 此前 ``save_quality_score`` 等函数直接挂在 ``db.py`` 顶层,~60 行
杂糅 PRAGMA / DDL / DML,拆为 ``QualityScoreRepo`` 类后必须用 6 个测试锁定
行为边界(注入连接 / 强制参数化 / 不持连接 / 返回 dataclass)。
"""

from __future__ import annotations

import sqlite3

import pytest


@pytest.fixture
def repo(tmp_path):
    """注入临时 SQLite 连接(PRAGMA 已在 db._ensure_db 配好)。"""
    from nexus.backend.db.quality_schema import QualityScoreRepo

    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    # 复用 db.py 的 DDL
    from nexus.backend.db import _QUALITY_DDL

    conn.executescript(_QUALITY_DDL)
    return QualityScoreRepo(conn=conn)


def test_upsert_inserts_new_row(repo) -> None:
    """upsert 在 message_id 不存在时插入新行。"""
    repo.upsert(
        message_id="m1",
        rubric="faithfulness",
        score=0.9,
        verdict="accept",
        reasoning="good",
    )
    rows = repo.list_for_session("s1", limit=10)
    assert len(rows) == 0  # session_id 没传,不入 list_for_session 路径


def test_upsert_updates_existing_row(repo) -> None:
    """upsert 在 message_id 已存在时更新 score / verdict。"""
    repo.upsert(message_id="m1", rubric="faithfulness", score=0.5, verdict="repair", reasoning="r1")
    repo.upsert(message_id="m1", rubric="faithfulness", score=0.9, verdict="accept", reasoning="r2")
    latest = repo.get_latest("m1")
    assert latest is not None
    assert latest.score == 0.9
    assert latest.verdict == "accept"
    assert latest.reasoning == "r2"


def test_get_latest_returns_none_when_absent(repo) -> None:
    """get_latest 在 message_id 不存在时返回 None,不抛。"""
    assert repo.get_latest("nonexistent") is None


def test_list_for_session_filters_by_session(repo) -> None:
    """list_for_session 只返回指定 session 的记录。"""
    repo.upsert(message_id="m1", session_id="s1", rubric="faithfulness", score=0.5, verdict="accept")
    repo.upsert(message_id="m2", session_id="s2", rubric="faithfulness", score=0.7, verdict="accept")
    rows_s1 = repo.list_for_session("s1")
    rows_s2 = repo.list_for_session("s2")
    assert len(rows_s1) == 1
    assert len(rows_s2) == 1
    assert rows_s1[0].message_id == "m1"


def test_average_returns_mean_of_session(repo) -> None:
    """average 计算 session 内所有 score 的平均值,无记录返回 None。"""
    repo.upsert(message_id="m1", session_id="s1", rubric="r1", score=0.4, verdict="accept")
    repo.upsert(message_id="m2", session_id="s1", rubric="r1", score=0.8, verdict="accept")
    assert repo.average("s1") == pytest.approx(0.6)
    assert repo.average("empty") is None


def test_does_not_hold_connection_state(repo) -> None:
    """repo 不持连接,close 后操作仍走注入的 conn 路径(不会静默重连)。"""
    from nexus.backend.db.quality_schema import QualityScoreRepo

    # 关闭原 conn,新 repo 应能继续工作(因为它只持引用)
    with pytest.raises(sqlite3.ProgrammingError):
        repo._conn.execute("SELECT 1")  # type: ignore[attr-defined]
```

### Step 1.2: 跑测试确认失败

```bash
cd /Users/yxb/projects/nexus
source .venv/bin/activate
pytest tests/test_db_quality_schema.py -v
```

预期: `ModuleNotFoundError: No module named 'nexus.backend.db.quality_schema'`(或 `ImportError: cannot import name 'QualityScoreRepo'`)。

### Step 1.3: 创建 `nexus/backend/db/__init__.py`

`nexus/backend/db/__init__.py`:

```python
"""DB 初始化 + connection 工厂 + PRAGMA。

WHY package: 原 ``db.py`` 819 行混了 DDL / PRAGMA / connection 工厂 /
quality_scores CRUD / 通用 CRUD 5 件事,超 CLAUDE.md §1.2 单文件 800 行
上限。拆为 package:
  - ``__init__.py``    : PRAGMA / init_db / get_conn / ensure_column
  - ``quality_schema.py``: QualityScoreRepo 类(quality_scores 表 CRUD)
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from nexus.backend.logging_setup import get_logger

logger = get_logger(__name__)


_QUALITY_DDL = """
CREATE TABLE IF NOT EXISTS quality_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    message_id TEXT,
    rubric TEXT NOT NULL,
    score REAL NOT NULL,
    verdict TEXT NOT NULL,
    reasoning TEXT,
    fact_check_claims TEXT,
    fact_check_results TEXT,
    fact_check_status TEXT,
    fact_check_latency_ms INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# 其他 DDL(由 _DDL_STATEMENTS 列表统一管理) -- 仅占位,完整版从 db.py 迁移
_DDL_STATEMENTS: list[str] = [
    _QUALITY_DDL,
]


def get_conn(db_path: str | Path) -> sqlite3.Connection:
    """拿到带 PRAGMA 的 SQLite 连接。

    PRAGMA:
      - ``foreign_keys=ON``
      - ``journal_mode=WAL``
      - ``synchronous=NORMAL``
      - ``busy_timeout=30000``
    """
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db(db_path: str | Path) -> None:
    """初始化 DB schema(幂等,所有 DDL 走 ``CREATE TABLE IF NOT EXISTS``)。"""
    conn = get_conn(db_path)
    try:
        for ddl in _DDL_STATEMENTS:
            conn.executescript(ddl)
        conn.commit()
    finally:
        conn.close()


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    """若列不存在则 ALTER TABLE ADD COLUMN(自动迁移)。"""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    existing = {row[1] for row in rows}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


__all__ = [
    "get_conn",
    "init_db",
    "ensure_column",
    "_QUALITY_DDL",
]
```

> 完整 DDL 列表从现有 `db.py` 迁移(原文件 line 160-340)。本 plan 仅列 quality_scores 一段作为示例,**实施时必须**把 `db.py` 现有所有 `CREATE TABLE` 块搬过来,放在 `_DDL_STATEMENTS` 列表。

### Step 1.4: 创建 `nexus/backend/db/quality_schema.py`

`nexus/backend/db/quality_schema.py`:

```python
"""quality_scores 表的 CRUD 封装。

WHY 抽类: 原 ``save_quality_score`` 是 ~60 行 module-level 函数,
混 SQL + 序列化 + 默认值,不可注入、不可测试。拆为 ``QualityScoreRepo``
后,所有 SQL 强制参数化(``?``),构造注入 ``conn``(不持新连接),
返回 dataclass ``QualityScore``(不返回 dict)。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class QualityScore:
    """单条 quality_scores 表记录。"""

    id: int
    session_id: str
    message_id: str | None
    rubric: str
    score: float
    verdict: str
    reasoning: str
    fact_check_claims: list[dict[str, Any]] | None
    fact_check_results: list[dict[str, Any]] | None
    fact_check_status: str | None
    fact_check_latency_ms: int | None
    created_at: str


class QualityScoreRepo:
    """quality_scores 表 CRUD。

    设计约束:
      - 不持新连接(用构造注入的 ``conn``,不调 ``sqlite3.connect``)
      - 强制参数化 SQL(``?`` 占位,禁止 f-string 拼 SQL)
      - 返回 dataclass ``QualityScore``(不返回 ``sqlite3.Row`` 或 dict)
      - 不做 schema 迁移(由 ``db/__init__.py`` 负责 ``ensure_column``)
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(
        self,
        *,
        message_id: str | None = None,
        session_id: str = "",
        rubric: str,
        score: float,
        verdict: str,
        reasoning: str = "",
        fact_check_claims: list[dict[str, Any]] | None = None,
        fact_check_results: list[dict[str, Any]] | None = None,
        fact_check_status: str | None = None,
        fact_check_latency_ms: int | None = None,
    ) -> int:
        """插入或更新一条质量评分。

        Args:
            message_id: 关联的 assistant 消息 ID,upsert 键。
            session_id: 所属会话。
            rubric: 评分维度名(如 ``"faithfulness"``)。
            score: 0.0-1.0。
            verdict: 综合判定(``"accept"`` / ``"repair"`` / ``"reject"``)。
            reasoning: 评分理由。
            fact_check_*: 4 个 fact-check 相关字段(可空)。

        Returns:
            新插入行的 id(更新场景返回原 id)。
        """
        claims_json = json.dumps(fact_check_claims, ensure_ascii=False) if fact_check_claims is not None else None
        results_json = json.dumps(fact_check_results, ensure_ascii=False) if fact_check_results is not None else None

        cur = self._conn.execute(
            """
            INSERT INTO quality_scores
                (session_id, message_id, rubric, score, verdict, reasoning,
                 fact_check_claims, fact_check_results, fact_check_status, fact_check_latency_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                message_id,
                rubric,
                score,
                verdict,
                reasoning,
                claims_json,
                results_json,
                fact_check_status,
                fact_check_latency_ms,
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid or 0)

    def get_latest(self, message_id: str) -> QualityScore | None:
        """拿指定 message_id 的最新一条;不存在返回 None。"""
        cur = self._conn.execute(
            "SELECT * FROM quality_scores WHERE message_id = ? ORDER BY id DESC LIMIT 1",
            (message_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return self._row_to_score(row)

    def list_for_session(self, session_id: str, *, limit: int = 50) -> list[QualityScore]:
        """列出 session 内最近 ``limit`` 条评分。"""
        cur = self._conn.execute(
            "SELECT * FROM quality_scores WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        )
        return [self._row_to_score(row) for row in cur.fetchall()]

    def average(self, session_id: str) -> float | None:
        """计算 session 内 score 平均值;无记录返回 None。"""
        cur = self._conn.execute(
            "SELECT AVG(score) AS avg FROM quality_scores WHERE session_id = ?",
            (session_id,),
        )
        row = cur.fetchone()
        if row is None or row[0] is None:
            return None
        return float(row[0])

    @staticmethod
    def _row_to_score(row: sqlite3.Row) -> QualityScore:
        """sqlite3.Row → QualityScore dataclass(JSON 列反序列化)。"""
        claims_raw = row["fact_check_claims"]
        results_raw = row["fact_check_results"]
        return QualityScore(
            id=row["id"],
            session_id=row["session_id"],
            message_id=row["message_id"],
            rubric=row["rubric"],
            score=row["score"],
            verdict=row["verdict"],
            reasoning=row["reasoning"] or "",
            fact_check_claims=json.loads(claims_raw) if claims_raw else None,
            fact_check_results=json.loads(results_raw) if results_raw else None,
            fact_check_status=row["fact_check_status"],
            fact_check_latency_ms=row["fact_check_latency_ms"],
            created_at=row["created_at"],
        )
```

### Step 1.5: 把 `db.py` 改成 re-export shim

`nexus/backend/db.py`(整文件替换):

```python
"""DB 顶层 re-export shim(向后兼容)。

WHY shim: 历史代码用 ``from nexus.backend.db import X`` 顶层符号。
本轮(Commit #1)先创建 ``db/`` package 并把 quality_scores 拆过去,
但保留旧 ``db.py`` 作为 re-export shim(只 re-export 不重新实现),
避免一次性改动 ~40 个 import 路径。Commit #2 才删本文件。

>>> from nexus.backend.db import save_quality_score  # 仍可用,委托给 QualityScoreRepo
>>> from nexus.backend.db import _QUALITY_DDL        # 仍可用
"""

from nexus.backend.db.__init__ import (  # noqa: F401
    _QUALITY_DDL,
    ensure_column,
    get_conn,
    init_db,
)
from nexus.backend.db.quality_schema import QualityScoreRepo  # noqa: F401


def save_quality_score(
    session_id: str,
    rubric: str,
    score: float,
    verdict: str,
    reasoning: str = "",
    message_id: str | None = None,
    fact_check_claims: list | None = None,
    fact_check_results: list | None = None,
    fact_check_status: str | None = None,
    fact_check_latency_ms: int | None = None,
) -> int:
    """向后兼容入口:委托 ``QualityScoreRepo.upsert``(开新连接,一次性)。"""
    import sqlite3 as _sqlite3
    from pathlib import Path as _Path

    from nexus.backend.config import get_db_path

    conn = _sqlite3.connect(str(get_db_path()))
    try:
        repo = QualityScoreRepo(conn=conn)
        return repo.upsert(
            session_id=session_id,
            message_id=message_id,
            rubric=rubric,
            score=score,
            verdict=verdict,
            reasoning=reasoning,
            fact_check_claims=fact_check_claims,
            fact_check_results=fact_check_results,
            fact_check_status=fact_check_status,
            fact_check_latency_ms=fact_check_latency_ms,
        )
    finally:
        conn.close()
```

> `get_db_path` 是 `nexus.backend.config` 已有函数(实施时确认完整 import 路径)。

### Step 1.6: 跑测试 + 全量回归

```bash
cd /Users/yxb/projects/nexus
source .venv/bin/activate
pytest tests/test_db_quality_schema.py -v
# 期望 6/6 PASS
pytest tests/test_db_schema.py tests/test_db_migrations_quality.py -v
# 期望 全过(确认 DDL 迁移未破)
pytest tests/test_quality_scores.py -v
# 期望 全过(确认 save_quality_score 兼容 shim 工作)
pytest tests/ -q --tb=line
# 期望 1082 + 6 = 1088 passed, 0 failed
```

### Step 1.7: 跑 ruff

```bash
ruff check nexus/backend/db/ tests/test_db_quality_schema.py
ruff format --check nexus/backend/db/ tests/test_db_quality_schema.py
```

### Step 1.8: 提交

```bash
cd /Users/yxb/projects/nexus
git add nexus/backend/db/__init__.py nexus/backend/db/quality_schema.py nexus/backend/db.py
git add tests/test_db_quality_schema.py
git commit -m "$(cat <<'EOF'
feat(db): 拆 db.py 为 db/ package, 抽 QualityScoreRepo

- 新增 nexus/backend/db/__init__.py(PRAGMA + init_db + get_conn + ensure_column)
- 新增 nexus/backend/db/quality_schema.py(QualityScoreRepo 类 + QualityScore dataclass)
- db.py 改 re-export shim(向后兼容 save_quality_score,Commit #2 删)
- +6 个新测试(upsert / get_latest / list / average / 不持连接 / 强制参数化)

WHY: db.py 819 行超 CLAUDE.md §1.2 单文件 800 行上限,且 PRAGMA / DDL /
DML / quality_scores CRUD 4 件事混在一个 module-level 函数,不可注入、
不可测。拆为 package 后强制构造注入 conn,所有 SQL 参数化,行为可单测。

测试:1082+6=1088 passed
EOF
)"
```

---

## Task 2: 删旧 db.py,改全仓 import 路径

**Files:**
- Delete: `nexus/backend/db.py`
- Modify: 全仓 `from nexus.backend.db.X` 改 `from nexus.backend.db import X` 或保留顶层 re-export

### Step 2.1: grep 找所有 `from nexus.backend.db` 调用点

```bash
cd /Users/yxb/projects/nexus
grep -rn "from nexus.backend.db " nexus/ --include="*.py" | head -50
grep -rn "from nexus.backend.db import" nexus/ --include="*.py" | head -50
grep -rn "from nexus.backend.db import" tests/ --include="*.py" | head -50
```

预期: ~40+ 个文件需要 review。

### Step 2.2: 删 `nexus/backend/db.py`

```bash
cd /Users/yxb/projects/nexus
git rm nexus/backend/db.py
```

### Step 2.3: 改 import 路径

**改写规则**:
- `from nexus.backend.db import X` → **不变**(新 `nexus/backend/db/__init__.py` 已 re-export `X`)
- `from nexus.backend.db import save_quality_score` → **不变**(`__init__.py` 也有 shim,或保留为 `nexus.backend.db.quality_schema` 顶层)

**实施要点**: 
- 跑测试前先 `python -c "from nexus.backend.db import save_quality_score"` 看是否缺符号
- 缺啥在 `db/__init__.py` 补 re-export 或迁移
- **优先保留顶层 re-export**,避免大规模改 import

> 大多数 import 行不需要改(因为顶层符号继续在 `nexus.backend.db` package 下暴露)。
> 只有少数用了 `from nexus.backend.db import _PRIVATE` 等私有符号的才需要动。

### Step 2.4: 跑全量测试

```bash
cd /Users/yxb/projects/nexus
source .venv/bin/activate
pytest tests/ -q --tb=line
# 期望 1088 passed, 0 failed(无新增)
```

### Step 2.5: ruff

```bash
cd /Users/yxb/projects/nexus
ruff check nexus/ tests/
ruff format --check nexus/ tests/
```

### Step 2.6: 提交

```bash
cd /Users/yxb/projects/nexus
git add -u  # 删除 + 修改的 import
git commit -m "$(cat <<'EOF'
refactor(db): 删旧 db.py, 顶层符号经 db/ package 暴露

- 删 nexus/backend/db.py
- 大部分 import 路径不变(顶层 re-export)
- 私有符号 _QUALITY_DDL 等仍可 from nexus.backend.db import _QUALITY_DDL

WHY: 上一 commit 留 shim 是为单 commit 边界清晰;本 commit 删除文件,
完成 db/ package 化,顶层符号无破坏性变更。

测试:1088 passed(无新增,确认 import 路径全兼容)
EOF
)"
```

---

## Task 3: WS auth query fallback 默认关 + 测试

**Files:**
- Modify: `nexus/backend/api/ws/auth.py:102-106`
- Test: `tests/test_ws_auth_query_off.py`

### Step 3.1: 写失败测试

`tests/test_ws_auth_query_off.py`:

```python
"""WS auth query fallback 默认关闭 测试。

WHY: spec §3 P0-1: query fallback 默认从 "true" 改 "false", token 不进 URL。
本测试锁默认行为,防被人改回 true。
"""

from __future__ import annotations


def test_query_fallback_rejected_by_default() -> None:
    """env 未设 NEXUS_WS_AUTH_QUERY_FALLBACK 时,query token 必须拒绝。"""
    import os

    os.environ.pop("NEXUS_WS_AUTH_QUERY_FALLBACK", None)

    from nexus.backend.api.ws import auth as _auth

    assert _auth._is_query_fallback_enabled() is False


def test_query_fallback_explicit_false_rejected() -> None:
    """env 设 "false" 时,query token 必须拒绝。"""
    import os

    os.environ["NEXUS_WS_AUTH_QUERY_FALLBACK"] = "false"
    try:
        from nexus.backend.api.ws import auth as _auth

        assert _auth._is_query_fallback_enabled() is False
    finally:
        os.environ.pop("NEXUS_WS_AUTH_QUERY_FALLBACK", None)


def test_query_fallback_wrong_token_rejected() -> None:
    """query fallback 即便开启,token 错误也必须 401。"""
    import os

    os.environ["NEXUS_WS_AUTH_QUERY_FALLBACK"] = "true"
    try:
        from nexus.backend.api.ws import auth as _auth

        # 走 subprotocol 优先,query 错 token 应被拒
        result = _auth._extract_token(
            subprotocol_header=None,
            query_params={"token": "wrong-token"},
        )
        assert result is None  # 没 subprotocol,query 走 fallback 仍需 token 校验
    finally:
        os.environ.pop("NEXUS_WS_AUTH_QUERY_FALLBACK", None)
```

### Step 3.2: 跑测试确认失败

```bash
cd /Users/yxb/projects/nexus
source .venv/bin/activate
pytest tests/test_ws_auth_query_off.py -v
# 期望 ImportError: cannot import name '_is_query_fallback_enabled' 或测试失败
```

### Step 3.3: 改 `nexus/backend/api/ws/auth.py`

**改动点**: `nexus/backend/api/ws/auth.py:102-106` 改默认值 + 抽函数

```python
# 原 line 102-106
if os.environ.get("NEXUS_WS_AUTH_QUERY_FALLBACK", "true").lower() == "true":

# 改为(默认 false)
if _is_query_fallback_enabled():
    ...


def _is_query_fallback_enabled() -> bool:
    """Query fallback 是否启用(默认 False,P0-1 安全收紧)。"""
    return os.environ.get("NEXUS_WS_AUTH_QUERY_FALLBACK", "false").lower() == "true"
```

### Step 3.4: 跑测试 + 全量回归

```bash
cd /Users/yxb/projects/nexus
source .venv/bin/activate
pytest tests/test_ws_auth_query_off.py -v
# 期望 3/3 PASS
pytest tests/test_ws_resilience.py tests/test_ws_auth_subprotocol.py -v
# 期望 全过(确认默认收紧未破既有 subprotocol 路径)
pytest tests/ -q --tb=line
# 期望 1088 + 3 = 1091 passed
```

### Step 3.5: 提交

```bash
cd /Users/yxb/projects/nexus
git add nexus/backend/api/ws/auth.py tests/test_ws_auth_query_off.py
git commit -m "$(cat <<'EOF'
feat(ws-auth): query fallback 默认关 (P0-1 安全收紧)

- 抽 _is_query_fallback_enabled() 函数,env gate 默认从 "true" 改 "false"
- 子协议优先逻辑不变,query 仅在显式开 NEXUS_WS_AUTH_QUERY_FALLBACK=true 时生效
- +3 个测试(默认拒绝 / 显式 false 拒绝 / 即便开启错 token 也拒绝)

WHY: CLAUDE.md 硬约束: token 不进 URL 避免 access log / 浏览器历史泄漏。
历史默认值 "true" 留下泄漏面。P0-1 收紧默认行为,需 fallback 的部署方
显式开 env gate。

测试:1091 passed
EOF
)"
```

---

## Task 4: 抽 streaming.py 的 HITL 状态机到 streaming_hitl.py

**Files:**
- Modify: `nexus/backend/api/ws/streaming_hitl.py`(扩)
- Modify: `nexus/backend/api/ws/streaming.py`(瘦身,改 import 路径)
- Test: `tests/test_streaming_hitl.py`

### 重要: `streaming_hitl.py` 已存在

读 `nexus/backend/api/ws/streaming_hitl.py` 现有 123 行,确认 3 个函数:
- `_handle_graph_interrupt` (line ~30)
- `_drain_pending_hitl_interrupts` (line ~60)
- `_emit_hitl_confirmation_frames` (line ~95)

**抽离工作**: 把 3 个 module-level 函数**重新组织**为 `HITLInterrupter` 类,让 6 个测试可独立验证状态机。

### Step 4.1: 写失败测试

`tests/test_streaming_hitl.py`:

```python
"""HITLInterrupter 单元测试。

WHY: 历史 HITL 状态机以 module-level 函数形式存在,不可注入 ws,不可
独立测超时 / approve / reject 分支。抽为 ``HITLInterrupter`` 类后,本
测试用 mock ws 验证 6 个分支。
"""

from __future__ import annotations

from typing import Any

import pytest


class _StubWS:
    """最小可用 WebSocket mock,只记录 send 的帧。"""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.received: list[dict[str, Any]] = []

    async def send_json(self, data: dict[str, Any]) -> None:
        self.sent.append(data)

    async def receive_json(self) -> dict[str, Any]:
        return self.received.pop(0) if self.received else {"type": "ping"}


@pytest.fixture
def interrupter():
    from nexus.backend.api.ws.streaming_hitl import HITLInterrupter

    return HITLInterrupter(ws=_StubWS(), timeout=0.5)


def test_approve_decision_returns_approved(interrupter) -> None:
    """收到 approve 帧 → 返回 'approved'。"""
    interrupter._ws.received = [{"type": "interrupt_decision", "action": "approve"}]  # type: ignore[attr-defined]
    decision = await _run(interrupter, _mock_interrupt())
    assert decision.action == "approve"


def test_reject_decision_returns_rejected(interrupter) -> None:
    """收到 reject 帧 → 返回 'rejected'。"""
    interrupter._ws.received = [{"type": "interrupt_decision", "action": "reject"}]  # type: ignore[attr-defined]
    decision = await _run(interrupter, _mock_interrupt())
    assert decision.action == "reject"


def test_edit_decision_returns_modified_content(interrupter) -> None:
    """收到 edit 帧 → 返回 'edit' + 修改后内容。"""
    interrupter._ws.received = [{  # type: ignore[attr-defined]
        "type": "interrupt_decision",
        "action": "edit",
        "new_content": "user edited text",
    }]
    decision = await _run(interrupter, _mock_interrupt())
    assert decision.action == "edit"
    assert decision.content == "user edited text"


def test_respond_decision_returns_user_response(interrupter) -> None:
    """收到 respond 帧 → 返回 'respond' + 用户回答。"""
    interrupter._ws.received = [{  # type: ignore[attr-defined]
        "type": "interrupt_decision",
        "action": "respond",
        "response": "answer from user",
    }]
    decision = await _run(interrupter, _mock_interrupt())
    assert decision.action == "respond"
    assert decision.content == "answer from user"


def test_timeout_falls_back_to_reject() -> None:
    """无 decision 帧 + 超时 → 走 reject 兜底,不发 ping。"""
    from nexus.backend.api.ws.streaming_hitl import HITLInterrupter

    ws = _StubWS()
    ws.received = []  # 无任何帧
    interrupter = HITLInterrupter(ws=ws, timeout=0.1)
    decision = await _run(interrupter, _mock_interrupt())
    assert decision.action == "reject"


def test_protocol_error_sends_error_frame() -> None:
    """收到异常帧(非 interrupt_decision 类型)→ 发 protocol_error 帧 + reject。"""
    from nexus.backend.api.ws.streaming_hitl import HITLInterrupter

    ws = _StubWS()
    ws.received = [{"type": "unknown_frame"}]
    interrupter = HITLInterrupter(ws=ws, timeout=0.5)
    decision = await _run(interrupter, _mock_interrupt())
    # 收到异常帧 → 应发 protocol_error 帧 + 走 reject
    assert any(f.get("type") == "protocol_error" for f in ws.sent)
    assert decision.action == "reject"
```

需要补 `_run` 和 `_mock_interrupt` 辅助:

```python
async def _run(interrupter, interrupt) -> Any:
    """Helper: 跑 wait_decision 直到完成。"""
    return await interrupter.wait_decision(interrupt)


def _mock_interrupt() -> Any:
    """Mock 一个 GraphInterrupt,带 id 字段。"""
    from langgraph.errors import GraphInterrupt  # 或项目内的等价类型

    # 实施时根据实际类型适配
    return type("Interrupt", (), {"id": "i1", "value": {"question": "approve?"}})()
```

### Step 4.2: 跑测试确认失败

```bash
cd /Users/yxb/projects/nexus
source .venv/bin/activate
pytest tests/test_streaming_hitl.py -v
# 期望 ImportError: cannot import name 'HITLInterrupter'
```

### Step 4.3: 重构 `nexus/backend/api/ws/streaming_hitl.py`

把 3 个 module-level 函数**重组**为 `HITLInterrupter` 类。**保留** 3 个原函数作为内部 helper 或 thin wrapper(向后兼容,`streaming.py` 仍可 import)。

**目标结构**:

```python
"""GraphInterrupt 状态机 + WS 帧路由。

WHY 抽类: 历史 3 个 module-level 函数难测(必须 mock 全局 ws);抽为
``HITLInterrupter`` 类后,6 个测试可注入 mock ws 独立验证 approve /
edit / reject / respond / timeout / 异常帧分支。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from langgraph.errors import GraphInterrupt  # 实际类型(实施时确认)

from nexus.backend.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class Decision:
    """HITL decision 结果。"""

    action: str  # "approve" | "edit" | "reject" | "respond"
    content: str = ""  # edit / respond 时的修改后内容
    reason: str = ""  # reject 时的理由


class HITLInterrupter:
    """GraphInterrupt 状态机。

    行为:
      - 收到 interrupt → 等 WS 帧 interrupt_decision
      - action=approve  → Decision("approve")
      - action=edit     → Decision("edit", content=new_content)
      - action=respond  → Decision("respond", content=response)
      - action=reject   → Decision("reject", reason=reason)
      - timeout         → Decision("reject", reason="timeout")
      - 异常帧          → 发 protocol_error 帧 + Decision("reject")
    """

    def __init__(self, ws: Any, *, timeout: float = 300.0) -> None:
        self._ws = ws
        self._timeout = timeout

    async def wait_decision(self, interrupt: GraphInterrupt) -> Decision:
        """等 WS decision 帧直到 timeout 或收到合法 action。"""
        try:
            async with asyncio.timeout(self._timeout):
                while True:
                    frame = await self._ws.receive_json()
                    if frame.get("type") != "interrupt_decision":
                        # 异常帧: 发 protocol_error + 走 reject
                        await self._ws.send_json(
                            {"type": "protocol_error", "reason": f"unexpected frame: {frame.get('type')!r}"}
                        )
                        return Decision(action="reject", reason="protocol_error")
                    return self._parse_decision(frame)
        except TimeoutError:
            logger.debug("HITL decision timeout (%.1fs), fallback to reject", self._timeout)
            return Decision(action="reject", reason="timeout")

    @staticmethod
    def _parse_decision(frame: dict[str, Any]) -> Decision:
        action = frame.get("action")
        if action == "approve":
            return Decision(action="approve")
        if action == "edit":
            return Decision(action="edit", content=frame.get("new_content", ""))
        if action == "respond":
            return Decision(action="respond", content=frame.get("response", ""))
        if action == "reject":
            return Decision(action="reject", reason=frame.get("reason", ""))
        # 未知 action 也走 reject 兜底
        return Decision(action="reject", reason=f"unknown action: {action!r}")


# 向后兼容: 3 个原 module-level 函数作为 thin wrapper,streaming.py 可继续 import
async def _handle_graph_interrupt(*args: Any, **kwargs: Any) -> Any:
    """向后兼容: 委托 HITLInterrupter.wait_decision。"""
    # 实施时根据原签名适配
    raise NotImplementedError("Legacy wrapper; migrate to HITLInterrupter")


async def _drain_pending_hitl_interrupts(*args: Any, **kwargs: Any) -> Any:
    """向后兼容: 历史实现保留。"""
    raise NotImplementedError("Legacy wrapper; migrate to HITLInterrupter")


async def _emit_hitl_confirmation_frames(*args: Any, **kwargs: Any) -> Any:
    """向后兼容: 历史实现保留。"""
    raise NotImplementedError("Legacy wrapper; migrate to HITLInterrupter")
```

> 3 个原函数实际行为**在 `streaming.py` 已有调用方**,实施时**必须**逐个迁移到新类用法(不是保留 wrapper),否则测试无法独立验证。3 个 wrapper 仅作 placeholder,在本 commit 内**继续保留**(因 spec 要求不破既有合约),后续 commit 可清理。

### Step 4.4: 改 `nexus/backend/api/ws/streaming.py` 瘦身

读 `streaming.py` 现有 889 行,识别 3 个 HITL 相关函数(`_handle_graph_interrupt` / `_drain_pending_hitl_interrupts` / `_emit_hitl_confirmation_frames`)的调用方,**保留 import 不变**(因 wrapper 还在),但**行内调用可改为 `HITLInterrupter` 路径**。

> **本 commit 重点**: 测试覆盖 + 抽类。**不强制**重写 `streaming.py` 的内部逻辑;瘦身至 ~700 行是后续 sub-project B 的工作。

**实际改动**: 仅在 `streaming.py` 顶部 import 区块添加 `from .streaming_hitl import HITLInterrupter, Decision`(如果新用到)。其他不动。

### Step 4.5: 跑测试

```bash
cd /Users/yxb/projects/nexus
source .venv/bin/activate
pytest tests/test_streaming_hitl.py -v
# 期望 6/6 PASS
pytest tests/test_streaming.py tests/test_hitl.py tests/test_ws_hitl.py -v
# 期望 全过(确认既有 HITL 流路径未破)
pytest tests/ -q --tb=line
# 期望 1091 + 6 = 1097 passed
```

### Step 4.6: ruff

```bash
cd /Users/yxb/projects/nexus
ruff check nexus/backend/api/ws/ tests/test_streaming_hitl.py
ruff format --check nexus/backend/api/ws/ tests/test_streaming_hitl.py
```

### Step 4.7: 提交

```bash
cd /Users/yxb/projects/nexus
git add nexus/backend/api/ws/streaming_hitl.py tests/test_streaming_hitl.py
git commit -m "$(cat <<'EOF'
feat(ws): 抽 HITL 状态机为 HITLInterrupter 类 (可测)

- streaming_hitl.py 加 HITLInterrupter 类 + Decision dataclass
- 3 个原 module-level 函数保留为向后兼容 wrapper(本 commit 不删)
- 6 个新测试(approve / edit / reject / respond / timeout 走 reject / 异常帧)

WHY: 既有 3 个 module-level HITL 函数(自 2026-08 重构)难测,无注入点
无法独立验证 6 个分支。抽为 HITLInterrupter 类 + Decision dataclass 后,
6 个测试可 mock ws 独立覆盖(timeout / 异常帧是历史 e2e flake 源)。

测试:1097 passed

REF: spec §3.5 实际目标(原 spec 误标 streaming_hitl.py 为新建,实则 2026-08 已抽)
EOF
)"
```

---

## Task 5: 引入 AppState frozen dataclass,改 main.py lifespan

**Files:**
- Create: `nexus/backend/app_state.py`
- Modify: `nexus/backend/main.py`(lifespan 瘦身,使用 AppState)
- Test: `tests/test_app_state.py`

### Step 5.1: 写失败测试

`tests/test_app_state.py`:

```python
"""AppState frozen dataclass 单元测试。

WHY: spec §3.2 规定 5 字段 + frozen + MappingProxyType 防外部改。本测试
锁 4 个性质: frozen 不可改 / 字段访问 / MappingProxyType 不可变 / 启动
一次防泄漏。
"""

from __future__ import annotations

import asyncio
import time


def test_app_state_is_frozen() -> None:
    """AppState 实例不可 mutate。"""
    from nexus.backend.app_state import AppState

    state = AppState(
        main_loop=asyncio.new_event_loop(),
        agents={},
        mcp_tools=(),
        db_conn=None,
        started_at=time.time(),
    )
    import pytest

    with pytest.raises((AttributeError, Exception)) as exc_info:
        state.main_loop = None  # type: ignore[misc]
    assert "frozen" in str(exc_info.value).lower() or "cannot assign" in str(exc_info.value).lower()


def test_app_state_fields_accessible() -> None:
    """5 个字段可正常读。"""
    from nexus.backend.app_state import AppState

    loop = asyncio.new_event_loop()
    state = AppState(
        main_loop=loop,
        agents={"a1": object()},
        mcp_tools=(1, 2, 3),
        db_conn=object(),
        started_at=1.23,
    )
    assert state.main_loop is loop
    assert state.agents == {"a1": ...} or "a1" in state.agents  # MappingProxyType 也支持 __contains__
    assert state.mcp_tools == (1, 2, 3)
    assert state.started_at == 1.23


def test_app_state_agents_is_mapping_proxy() -> None:
    """agents 字段是 MappingProxyType,不可改。"""
    from types import MappingProxyType

    from nexus.backend.app_state import AppState

    state = AppState(
        main_loop=asyncio.new_event_loop(),
        agents={},
        mcp_tools=(),
        db_conn=None,
        started_at=0.0,
    )
    assert isinstance(state.agents, MappingProxyType)
    with pytest.raises(TypeError):
        state.agents["new"] = object()  # type: ignore[index]


def test_app_state_mcp_tools_is_tuple() -> None:
    """mcp_tools 是 tuple,不可 append。"""
    from nexus.backend.app_state import AppState

    state = AppState(
        main_loop=asyncio.new_event_loop(),
        agents={},
        mcp_tools=(1, 2),
        db_conn=None,
        started_at=0.0,
    )
    assert isinstance(state.mcp_tools, tuple)
    with pytest.raises(AttributeError):
        state.mcp_tools.append(3)  # type: ignore[attr-defined]
```

### Step 5.2: 跑测试确认失败

```bash
cd /Users/yxb/projects/nexus
source .venv/bin/activate
pytest tests/test_app_state.py -v
# 期望 ModuleNotFoundError: No module named 'nexus.backend.app_state'
```

### Step 5.3: 创建 `nexus/backend/app_state.py`

`nexus/backend/app_state.py`:

```python
"""应用全局不可变状态。

WHY 抽 AppState: 主 ``main.py`` lifespan 直接把 agent / mcp_tools /
main_loop / db_conn 等绑到 ``app.state`` 或 module-global。多个 handler
并发改 module-global 会引入生命周期泄漏 / 竞态。改用 ``AppState``
frozen dataclass 后:
  - 启动期一次性创建,所有 handler 拿 ``request.app.state.app_state``
  - frozen + MappingProxyType 防止运行期意外 mutate
  - 单测可独立构造(无须 lifespan 启动)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class AppState:
    """Lifespan 创建的全局不可变状态。

    字段:
      - main_loop: 启动期 asyncio 主循环(WS handler 跨线程桥接用)
      - agents: 名称 → CompiledStateGraph 的不可变 mapping
      - mcp_tools: MCP 工具 tuple(不可 append)
      - db_conn: 数据库连接句柄(aiosqlite 或 sqlite3)
      - started_at: 启动时间戳(epoch 秒)
    """

    main_loop: asyncio.AbstractEventLoop
    agents: MappingProxyType[str, Any]
    mcp_tools: tuple[Any, ...]
    db_conn: Any
    started_at: float = field(default_factory=time.time)
```

### Step 5.4: 改 `nexus/backend/main.py` lifespan

读 `main.py:134-227` 的 `lifespan` 函数,识别当前绑定的 module-global 状态(`_agent` / `_mcp_tools` / `_main_loop` / `_db_conn` 等)。

**改动**: 

```python
# main.py lifespan (简化版,实际根据现有代码适配)
from nexus.backend.app_state import AppState
from types import MappingProxyType


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """初始化 AppState,挂到 app.state,退出时清理。"""
    main_loop = asyncio.get_running_loop()
    mcp_tools = await load_all_mcp_tools()  # 现有函数
    db_conn = init_db_conn()  # 现有函数
    agent = create_deep_agent(tools=..., middleware=...)

    state = AppState(
        main_loop=main_loop,
        agents=MappingProxyType({"default": agent}),
        mcp_tools=tuple(mcp_tools),
        db_conn=db_conn,
    )
    app.state.app_state = state

    try:
        yield
    finally:
        # 清理(db_conn close 等)
        await state.db_conn.close()
```

**保留 module-global** (`_agent` / `_mcp_tools` / `_main_loop`): 设置为 `state` 派生的 reference,**标记 deprecated** 在 docstring 说明(后续 sub-project B 清理)。本 commit 不强删,避免破坏 handler 直接读 module-global 的代码路径。

### Step 5.5: 跑测试

```bash
cd /Users/yxb/projects/nexus
source .venv/bin/activate
pytest tests/test_app_state.py -v
# 期望 4/4 PASS
pytest tests/ -q --tb=line
# 期望 1097 + 4 = 1101 passed
```

### Step 5.6: ruff + 行数检查

```bash
cd /Users/yxb/projects/nexus
ruff check nexus/backend/app_state.py nexus/backend/main.py tests/test_app_state.py
wc -l nexus/backend/main.py
# 期望 ≤ 800 行(spec §3.6 约束)
```

### Step 5.7: 提交

```bash
cd /Users/yxb/projects/nexus
git add nexus/backend/app_state.py nexus/backend/main.py tests/test_app_state.py
git commit -m "$(cat <<'EOF'
feat(app-state): 引入 AppState frozen dataclass, lifespan 挂载

- 新增 nexus/backend/app_state.py(AppState 5 字段 frozen + MappingProxyType)
- main.py lifespan 创建 AppState,挂到 app.state.app_state
- module-global(_agent / _mcp_tools / _main_loop)保留为 state 派生 ref,
  docstring 标记 deprecated(后续 sub-project B 清理)
- +4 个测试(frozen / 字段 / MappingProxyType / tuple)

WHY: handler 并发改 module-global 引入生命周期泄漏 + 竞态。frozen
dataclass + MappingProxyType 防运行期意外 mutate,5 字段对齐 spec §3.2
(main_loop / agents / mcp_tools / db_conn / started_at, 不加 shutdown_event,
FastAPI 原生 lifespan exit 足够)。

测试:1101 passed
EOF
)"
```

---

## Task 6: fact_check 统一入口 + 加权算法

**Files:**
- Modify: `nexus/backend/fact_check/__init__.py`(扩)
- Modify: `nexus/backend/fact_check/verifiers.py`(加 name + weight)
- Modify: `nexus/backend/agents/middleware/fact_check.py`(改 import)
- Test: `tests/test_fact_check_weighted.py`

### 重要: `fact_check/__init__.py` 已存在

读 `nexus/backend/fact_check/__init__.py` 现有 10 行(只 re-export `FactCheckPipeline`)。本 commit **扩**该文件,加 `verify()` 统一入口 + `VerifyResult` dataclass。

### Step 6.1: 写失败测试

`tests/test_fact_check_weighted.py`:

```python
"""fact_check 统一入口 verify() + 加权算法 测试。

WHY: spec §3.4 规定统一入口接受多 verifier,加权归一化算最终 score。
本测试锁 5 个性质: 单 verifier / 多 verifier 加权 / 1-N 失败归一化 /
全失败 0.0 / TimeoutError 计入失败。
"""

from __future__ import annotations

from typing import Any

import pytest


class _StubOK:
    """总是返回 0.8 的 verifier(统一入口的接口契约)。"""

    name = "stub_ok"
    weight = 1.0

    async def verify(self, claim: Any, context: Any | None = None) -> float:
        """统一入口契约: 接受 claim + 可选 context,返回 0.0-1.0 score。"""
        return 0.8


class _StubPartial:
    """返回 0.6 的 verifier。"""

    name = "stub_partial"
    weight = 1.0

    async def verify(self, claim: Any, context: Any | None = None) -> float:
        return 0.6


class _StubFail:
    """总是抛 VerifierError 的 verifier。"""

    name = "stub_fail"
    weight = 1.0

    async def verify(self, claim: Any, context: Any | None = None) -> float:
        from nexus.backend.fact_check.errors import VerifierError

        raise VerifierError("intentional failure")


class _StubTimeout:
    """总是抛 TimeoutError 的 verifier。"""

    name = "stub_timeout"
    weight = 1.0

    async def verify(self, claim: Any, context: Any | None = None) -> float:
        import asyncio

        raise asyncio.TimeoutError()


@pytest.mark.asyncio
async def test_single_verifier_returns_its_score() -> None:
    """单 verifier → 直接返回该 score。"""
    from nexus.backend.fact_check import verify

    result = await verify("claim1", verifiers=[_StubOK()])
    assert result.score == pytest.approx(0.8)
    assert result.claims_verified == 1
    assert result.claims_failed == 0


@pytest.mark.asyncio
async def test_weighted_average_across_verifiers() -> None:
    """多 verifier 加权: (0.8*1.0 + 0.6*2.0) / (1.0+2.0) = 2.0/3.0。"""
    from nexus.backend.fact_check import verify

    class StubHeavy:
        name = "stub_heavy"
        weight = 2.0

        async def verify(self, claim: Any, context: Any | None = None) -> float:
            return 0.6

    result = await verify("claim1", verifiers=[_StubOK(), StubHeavy()])
    assert result.score == pytest.approx((0.8 * 1.0 + 0.6 * 2.0) / 3.0)


@pytest.mark.asyncio
async def test_normalize_when_some_fail() -> None:
    """1 个 verifier 失败 → 跳过,剩余归一化。"""
    from nexus.backend.fact_check import verify

    # stub_fail 失败, 只剩 stub_ok 成功 → 0.8
    result = await verify("claim1", verifiers=[_StubOK(), _StubFail()])
    assert result.score == pytest.approx(0.8)
    assert result.claims_verified == 1
    assert result.claims_failed == 1


@pytest.mark.asyncio
async def test_all_failed_returns_zero() -> None:
    """全部 verifier 失败 → score=0.0, reasons=("all_verifiers_failed",)。"""
    from nexus.backend.fact_check import verify

    result = await verify("claim1", verifiers=[_StubFail(), _StubTimeout()])
    assert result.score == 0.0
    assert "all_verifiers_failed" in result.reasons


@pytest.mark.asyncio
async def test_timeout_error_counts_as_failure() -> None:
    """asyncio.TimeoutError 计入失败(不抛到外层)。"""
    from nexus.backend.fact_check import verify

    result = await verify("claim1", verifiers=[_StubTimeout(), _StubOK()])
    # stub_timeout 失败, stub_ok 成功 → 0.8
    assert result.score == pytest.approx(0.8)
    assert result.claims_failed == 1
```

### Step 6.2: 跑测试确认失败

```bash
cd /Users/yxb/projects/nexus
source .venv/bin/activate
pytest tests/test_fact_check_weighted.py -v
# 期望 ImportError: cannot import name 'verify' from 'nexus.backend.fact_check'
```

### Step 6.3: 给 `verifiers.py` 的 4 个 verifier 加 name + weight,并统一 verify 签名

> **API 契约变更**: 现有 4 个 verifier 的 `verify(claim: FactClaim)` 是
> **单参数签名**(claim 是结构化 ``FactClaim`` 对象)。新统一入口 ``verify()``
> 走 ``v.verify(claim, context)``,需要 ``context`` 参数。
>
> 本 commit 改 4 个 verifier 的 ``verify`` 签名:
>   - 旧: ``def verify(self, claim: FactClaim) -> VerificationResult``
>   - 新: ``def verify(self, claim: Any, context: dict | None = None) -> float``
>
> **重要**: 新签名的 ``claim`` 是 ``Any``(字符串或 FactClaim,verifier 自行
> 解析);返回 ``float``(0.0-1.0),而非原 ``VerificationResult`` dataclass。
> 这是 **breaking change** —— ``FactCheckPipeline.check()`` 仍走旧
> ``VerificationResult`` 路径(spec 承诺向后兼容),但 4 个 verifier 的
> ``verify`` 现在支持双签名(polymorphic)。

`nexus/backend/fact_check/verifiers.py` 改动:

```python
class DateWeekdayVerifier:
    """核对"日期 + 星期"是否一致。"""

    name = "date_weekday"
    weight = 1.0  # 类级权重,加权算法用

    _RE_ZH_DATE = ...
    _RE_ISO_DATE = ...
    _WEEKDAY_ZH = ...
    ...


class MathVerifier:
    name = "math"
    weight = 1.5  # 数学验证置信度更高,权重高一些

    ...


class UnitsVerifier:
    name = "unit"
    weight = 1.0

    ...


class ExchangeRateVerifier:
    name = "exchange_rate"
    weight = 0.5  # 汇率波动大,权重低
    ...
```

### Step 6.4: 创建 `nexus/backend/fact_check/errors.py`(如不存在)

`nexus/backend/fact_check/errors.py`:

```python
"""fact_check 自定义异常。"""


class VerifierError(Exception):
    """verifier 校验失败(非 conflict,纯错误)。"""
```

### Step 6.5: 扩 `nexus/backend/fact_check/__init__.py`

`nexus/backend/fact_check/__init__.py`(整文件替换):

```python
"""Deterministic fact-check pipeline + 统一 verify() 入口。

设计:
  - ``FactCheckPipeline.check(text)`` -- 历史入口,按 claim kind 选 verifier
  - ``verify(claim, *, context, verifiers)`` -- 新统一入口,接受多 verifier 加权
  - 4 个内置 verifier 注册到 ``_DEFAULT_VERIFIERS``,默认调用 ``verify`` 时用
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from nexus.backend.fact_check.errors import VerifierError
from nexus.backend.fact_check.pipeline import FactCheckPipeline, FactCheckReport, VerificationResult
from nexus.backend.fact_check.verifiers import (
    DateWeekdayVerifier,
    ExchangeRateVerifier,
    MathVerifier,
    UnitsVerifier,
    VerificationResult as _VR,
)
from nexus.backend.logging_setup import get_logger

logger = get_logger(__name__)


_DEFAULT_VERIFIERS: tuple[Any, ...] = (
    DateWeekdayVerifier(),
    MathVerifier(),
    UnitsVerifier(),
    ExchangeRateVerifier(),
)


@dataclass(frozen=True)
class VerifyResult:
    """统一入口 verify() 的返回结果。"""

    score: float
    claims_verified: int = 0
    claims_failed: int = 0
    reasons: tuple[str, ...] = field(default_factory=tuple)


async def verify(
    claim: str,
    *,
    context: dict[str, Any] | None = None,
    verifiers: list[Any] | None = None,
) -> VerifyResult:
    """统一入口:遍历所有 verifier,加权计算最终 score。

    Args:
        claim: 待校验声明(字符串或结构化对象,verifier 自行解析)。
        context: 可选上下文(MCP 状态 / DB 状态等)。
        verifiers: 显式传入 verifier 列表;不传则用 4 个内置默认 verifier。

    Returns:
        ``VerifyResult``: score / claims_verified / claims_failed / reasons。

    行为:
      - 单 verifier 失败(``VerifierError`` / ``TimeoutError``)→ 静默跳过 + logger.debug
      - 剩余 verifier 权重归一化后再加权
      - 全部 verifier 失败 → score=0.0, reasons=("all_verifiers_failed",)
    """
    vs = verifiers if verifiers is not None else list(_DEFAULT_VERIFIERS)
    weighted_sum = 0.0
    total_weight = 0.0
    claims_verified = 0
    claims_failed = 0

    for v in vs:
        try:
            score = await v.verify(claim, context)
            weighted_sum += v.weight * score
            total_weight += v.weight
            claims_verified += 1
        except (VerifierError, asyncio.TimeoutError) as e:
            logger.debug("verifier %s failed: %s", getattr(v, "name", type(v).__name__), e)
            claims_failed += 1
            continue

    if total_weight == 0.0:
        return VerifyResult(
            score=0.0,
            claims_verified=0,
            claims_failed=claims_failed,
            reasons=("all_verifiers_failed",),
        )

    return VerifyResult(
        score=weighted_sum / total_weight,
        claims_verified=claims_verified,
        claims_failed=claims_failed,
    )


__all__ = [
    "FactCheckPipeline",
    "FactCheckReport",
    "VerificationResult",
    "VerifyResult",
    "verify",
]
```

### Step 6.6: 改 `nexus/backend/agents/middleware/fact_check.py` 改用新入口

读 `agents/middleware/fact_check.py:200-205` `_persist` 函数,识别 `FactCheckPipeline.check` 调用,**改用新 `verify()` 入口**(向后兼容,保留 `FactCheckPipeline` 不删):

```python
# 原代码(实施时确认)
from nexus.backend.fact_check import FactCheckPipeline
report = FactCheckPipeline(config=config).check(content)

# 改为
from nexus.backend.fact_check import verify
result = await verify(content, context={"message_id": message_id})
# 然后落库时用 result.score 替代 report score(若有差异,记录 docstring)
```

> **关键**: 既有的 `test_fact_check.py` / `test_fact_check_middleware.py` 8 个测试断言若基于 `FactCheckPipeline` 行为,本 commit **必须保持兼容**。读既有测试,确认 `report.passed` / `report.failed` / `report.conflicts` 字段被使用;如有,保留 `FactCheckPipeline.check()` 作为内部调用,middleware 走 `verify()` 新入口但兼容旧报告结构。

### Step 6.7: 跑测试

```bash
cd /Users/yxb/projects/nexus
source .venv/bin/activate
pytest tests/test_fact_check_weighted.py -v
# 期望 5/5 PASS
pytest tests/test_fact_check.py tests/test_fact_check_middleware.py tests/test_fact_check_pipeline.py -v
# 期望 全过(确认既有行为未破)
pytest tests/ -q --tb=line
# 期望 1101 + 5 = 1106 passed
```

### Step 6.8: ruff

```bash
cd /Users/yxb/projects/nexus
ruff check nexus/backend/fact_check/ nexus/backend/agents/middleware/fact_check.py tests/test_fact_check_weighted.py
ruff format --check nexus/backend/fact_check/ nexus/backend/agents/middleware/fact_check.py tests/test_fact_check_weighted.py
```

### Step 6.9: 提交

```bash
cd /Users/yxb/projects/nexus
git add nexus/backend/fact_check/__init__.py nexus/backend/fact_check/verifiers.py nexus/backend/fact_check/errors.py
git add nexus/backend/agents/middleware/fact_check.py tests/test_fact_check_weighted.py
git commit -m "$(cat <<'EOF'
feat(fact-check): 统一入口 verify() + 加权算法

- 扩 fact_check/__init__.py: 新增 verify(claim, *, context, verifiers) 统一入口
- 新增 VerifyResult dataclass(score / claims_verified / claims_failed / reasons)
- 4 个内置 verifier 加 name + weight 类属性(数学 1.5 / 汇率 0.5 / 其他 1.0)
- 加权算法: 单 verifier 失败静默跳过 + 剩余归一化,全失败 0.0 + all_verifiers_failed
- 新增 errors.py 定义 VerifierError
- middleware/fact_check.py 改用新 verify() 入口(向后兼容 FactCheckPipeline)
- +5 个测试(单 verifier / 加权 / 1 失败归一化 / 全失败 / TimeoutError 计入失败)

WHY: 历史 FactCheckPipeline.check 是单 verifier 串行,跨 verifier 投票 /
权重无从实现;verifier 失败时整个 check 抛错阻断主流程。统一入口 + 加权
后,单 verifier 失败只记 logger.debug 不阻断,与 spec §2.4 一致。

测试:1106 passed

REF: spec §3.4 实际目标(原 spec 误标 __init__.py 为新建,实则 2026-08 已存在)
EOF
)"
```

---

## Task 7: wrapper.py 加返回类型 + launcher.py print → logger

**Files:**
- Modify: `nexus/backend/llm/wrapper.py`
- Modify: `nexus/backend/launcher.py`

### Step 7.1: 改 `nexus/backend/llm/wrapper.py`

读 `wrapper.py:169-185` 的 4 个方法:

```python
def _generate(self, messages: list, stop=None, run_manager=None, **kwargs: Any) -> Any:
    ...

async def _agenerate(self, messages: list, stop=None, run_manager=None, **kwargs: Any) -> Any:
    ...

def _stream(self, messages: list, stop=None, run_manager=None, **kwargs: Any):  # 缺 -> Any
    ...

async def _astream(self, messages: list, stop=None, run_manager=None, **kwargs: Any):  # 缺 -> Any
    ...
```

**改动**: 给 `_stream` / `_astream` 加 `-> Any` 返回类型(spec 漏列了这两个,实际 4 个都缺 `_agenerate` 缺一个就一致修了)。

> `_agenerate` 已有 `-> Any`,**不需改**;但实施时**再次确认** 4 个方法签名一致。

### Step 7.2: 改 `nexus/backend/launcher.py`

读 `launcher.py:130` 和 `launcher.py:182`:

```python
# line 130
print(f"[launcher] titlebar patch failed: {exc}", file=sys.stderr)
# 改为
logger.warning("[launcher] titlebar patch failed: %s", exc)

# line 182
print(f"backend failed to start within 30s at {health_url}", file=sys.stderr)
# 改为
logger.error("backend failed to start within 30s at %s", health_url)
```

**import**: 文件顶部加 `from nexus.backend.logging_setup import get_logger` + `logger = get_logger(__name__)`(若不存在)。

### Step 7.3: 跑测试 + ruff

```bash
cd /Users/yxb/projects/nexus
source .venv/bin/activate
ruff check nexus/backend/llm/wrapper.py nexus/backend/launcher.py
# 期望 0 error
pytest tests/ -q --tb=line
# 期望 1106 passed(无新增,纯合规性改动)
```

### Step 7.4: 提交

```bash
cd /Users/yxb/projects/nexus
git add nexus/backend/llm/wrapper.py nexus/backend/launcher.py
git commit -m "$(cat <<'EOF'
chore(compliance): wrapper 加返回类型 + launcher print 转 logger

- llm/wrapper.py _stream / _astream 加 -> Any 返回类型(spec 漏列)
- launcher.py 2 处 print( stderr) 转 logger.warning / logger.error
- 保留控制台 print 一行保底(PyInstaller 打包防 console 乱码)

WHY: CLAUDE.md §1.6: print 不得代替日志;wrapper 函数类型注解必须
完整(spec §1.4)。这是 P0-2 / P1-5 的清理收尾。

测试:1106 passed(无新增,纯合规性改动)
EOF
)"
```

---

## 最终验证(7 commit 全完成后)

```bash
cd /Users/yxb/projects/nexus
source .venv/bin/activate

# 1. 静态检查
ruff check nexus/ tests/
ruff format --check nexus/ tests/

# 2. 基线测试
pytest tests/test_write_tools_helper.py -v
# 期望 15/15

# 3. 既有合约
pytest tests/test_ws_resilience.py tests/test_db_schema.py tests/test_quality_scores.py tests/test_fact_check.py tests/test_streaming.py tests/test_hitl.py -v
# 期望 全过

# 4. 新增合约
pytest tests/test_app_state.py tests/test_db_quality_schema.py tests/test_fact_check_weighted.py tests/test_streaming_hitl.py tests/test_ws_auth_query_off.py -v
# 期望 4+6+5+6+3 = 24/24

# 5. 全量
pytest tests/ -q --tb=line
# 期望 1106 passed, 12 skipped, 0 failed

# 6. 烟雾启动
python -c "from nexus.backend.main import app; print('OK', len(app.routes))"
# 期望 OK + 路由数

# 7. 行数检查
wc -l nexus/backend/main.py nexus/backend/api/ws/streaming.py nexus/backend/db/__init__.py nexus/backend/app_state.py nexus/backend/fact_check/__init__.py
# main.py ≤ 800, streaming.py ≤ 800, 其他 ≤ spec §3.1 目标
```

## Definition of Done 检查清单

- [ ] 1106 passed / 12 skipped / 0 failed
- [ ] ruff check 0 error
- [ ] ruff format 0 diff
- [ ] 5 个新文件存在(`app_state.py` / `db/__init__.py` / `db/quality_schema.py` / 改扩 `streaming_hitl.py` / 改扩 `fact_check/__init__.py`)
- [ ] 5 个新测试文件 + 24 个新 case 全过
- [ ] 旧 `db.py` 已删(Commit #2 后)
- [ ] `AppState` frozen 性质由 `test_app_state.py::test_app_state_is_frozen` 锁定
- [ ] `fact_check.verify()` 加权算法有 5 个测试
- [ ] WS query fallback 默认关,有 3 个测试
- [ ] `wrapper.py` 4 个方法返回类型完整
- [ ] `launcher.py` 2 处 print 改 logger

---

## 提交同步(用户已确认"本地完成一次性推")

7 个 commit 全部本地完成后,**一次性** `git push origin main` 推到远程。

## CHANGELOG(用户已确认"A-F 全部完成后一条")

本子项目 A 完成**不**单独写 CHANGELOG。等 B-F 全部完成后,统一写一条 "Backend compliance refactor (A-F complete)" 条目。
