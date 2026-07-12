# Plan:db.py wechat 查询索引化 + account_id 落库

## 目标

收回 2 个 P1 性能 + 数据债:

1. **`db.find_latest_session_by_user`** 全表扫 `messages.content LIKE '%user_id%'` — 生产规模 100k+ 行后单次查询 100-500ms。
2. **`db.list_sessions` Python 层 wechat 过滤 + 标题解析**脆弱(`title.split()[1]` 取 account_id),数据迁移后无法回放。

## 当前态

`nexus/backend/db.py`:

**Line 322-347 `find_latest_session_by_user`**:
```sql
SELECT s.id FROM messages m
JOIN sessions s ON m.session_id = s.id
WHERE s.channel = ?
  AND s.deleted_at IS NULL
  AND m.content LIKE ? ESCAPE '\\'
ORDER BY m.created_at DESC LIMIT 1
```
- `messages.content` 没有索引覆盖(只有 `idx_messages_session_id`)
- LIKE '%pattern%' 必然全表扫
- `m.content` 是用户消息正文,跟 user_id 没有直接关系 — 这是**用错列**!

**Line 350-381 `list_sessions`**:
```python
if s.get("channel") == "wechat":
    title = s.get("title", "")
    parts = title.split()
    if len(parts) >= 2:
        acc_id = parts[1]
    else:
        acc_id = "unknown"
```
- 从 title "微信 {account_id[:8]} {user_id[:8]}" 字符串解析 account_id
- 假设 title 格式稳定,任何改 title 模板的 commit 会破坏
- 仅按 account_id 分组,user_id 维度丢失(同一 account 下多个 user 会混淆)

## 拆解方案

### Phase 1:数据 schema 升级 — `sessions.account_id` + `sessions.wechat_user_id` 列

`_ensure_column` 自动迁移(走 CLAUDE.md "禁止直接写 ALTER TABLE" 约束,但通过 `_ensure_column` 是允许的):

```python
_ensure_column(conn, "sessions", "account_id", "TEXT")
_ensure_column(conn, "sessions", "wechat_user_id", "TEXT")
_ensure_column(conn, "sessions", "channel_meta", "TEXT")  # JSON for future extensions
```

新建索引:
```sql
CREATE INDEX IF NOT EXISTS idx_sessions_channel_account
  ON sessions(channel, account_id, updated_at DESC)
  WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_sessions_wechat_user
  ON sessions(wechat_user_id)
  WHERE deleted_at IS NULL AND wechat_user_id IS NOT NULL;
```

WHY 索引带 `WHERE deleted_at IS NULL`:partial index 把软删行排除在外,索引体积更小,查询计划走更窄的范围。

### Phase 2:`create_session` 接受 account_id / wechat_user_id

```python
def create_session(
    session_id: str,
    title: str | None = None,
    channel: str = "main",
    account_id: str | None = None,
    wechat_user_id: str | None = None,
    channel_meta: dict | None = None,
) -> dict:
    ...
    conn.execute(
        "INSERT OR IGNORE INTO sessions (id, title, created_at, updated_at, channel, account_id, wechat_user_id, channel_meta) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (session_id, title, now, now, channel, account_id, wechat_user_id,
         json.dumps(channel_meta) if channel_meta else None),
    )
```

调用方(`wechat_channel.py` / `gateway.py`)在创建 wechat 会话时填入 `account_id` + `wechat_user_id`,把数据放进正经的列,不再靠 title 字符串解析。

### Phase 3:`find_latest_session_by_user` 改用 wechat_user_id 列

```python
def find_latest_session_by_user(user_id: str, account_id: str | None = None, channel: str = "wechat") -> str | None:
    """按 account_id + wechat_user_id 精确查最近会话。
    
    WHY 显式 account_id:同一微信 user 可能跨多 account,必须 account 隔离。
    WHY 不再走 messages.content LIKE:之前是错用列 — user_id 在 sessions.wechat_user_id。
    """
    with get_db() as conn:
        if account_id:
            row = conn.execute(
                """
                SELECT id FROM sessions
                 WHERE channel = ?
                   AND account_id = ?
                   AND wechat_user_id = ?
                   AND deleted_at IS NULL
                 ORDER BY updated_at DESC LIMIT 1
                """,
                (channel, account_id, user_id),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT id FROM sessions
                 WHERE channel = ?
                   AND wechat_user_id = ?
                   AND deleted_at IS NULL
                 ORDER BY updated_at DESC LIMIT 1
                """,
                (channel, user_id),
            ).fetchone()
        return row["id"] if row else None
```

性能提升:
- 走 `idx_sessions_wechat_user` partial index,O(log n) 而不是 O(n)
- 100k 消息的库从 100-500ms → < 5ms

### Phase 4:`list_sessions` 用 SQL GROUP BY account_id

```python
def list_sessions(limit: int = 50) -> list[dict]:
    with get_db() as conn:
        # SQLite 没有 FIRST_VALUE / DISTINCT ON,用 correlated subquery
        rows = conn.execute(
            """
            SELECT s.*
              FROM sessions s
              LEFT JOIN sessions s2
                ON s.channel = s2.channel
               AND (s.channel != 'wechat' OR s.account_id = s2.account_id)
               AND s2.deleted_at IS NULL
               AND s2.updated_at > s.updated_at
             WHERE s.deleted_at IS NULL
               AND s2.id IS NULL
             ORDER BY s.updated_at DESC
             LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]
```

或者更清晰:把每个 channel 的最新一条查出来,合并:

```python
def list_sessions(limit: int = 50) -> list[dict]:
    with get_db() as conn:
        # 主会话(main channel):所有最新
        main_rows = conn.execute(
            """
            SELECT * FROM sessions
             WHERE channel = 'main' AND deleted_at IS NULL
             ORDER BY updated_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        # wechat:按 account_id GROUP BY,每组最新
        wechat_rows = conn.execute(
            """
            SELECT s.* FROM sessions s
             WHERE s.channel = 'wechat' AND s.deleted_at IS NULL
               AND NOT EXISTS (
                   SELECT 1 FROM sessions s2
                    WHERE s2.channel = 'wechat'
                      AND s2.account_id = s.account_id
                      AND s2.deleted_at IS NULL
                      AND s2.updated_at > s.updated_at
               )
             ORDER BY s.updated_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    # 合并 + sort by updated_at desc + 截断 limit
    merged = sorted(
        [dict(r) for r in main_rows] + [dict(r) for r in wechat_rows],
        key=lambda s: s["updated_at"],
        reverse=True,
    )[:limit]
    return merged
```

无 Python 层字符串解析,完全用 SQL 表达。

### Phase 5:`wechat_channel.py` 写库走新列

```python
# wechat_channel.py:启动时重建 user_id → session_id 映射
def _rebuild_user_session_map(self):
    accounts = self._list_accounts()
    for acc in accounts:
        sessions = db.list_sessions_by_account(acc.id, channel="wechat")
        # sessions 是 list[dict],包含 wechat_user_id
        for s in sessions:
            self._user_session_map[(acc.id, s["wechat_user_id"])] = s["id"]
```

`_handle_incoming_message`:
```python
session_id = self._user_session_map.get((account_id, user_id))
if not session_id:
    session_id = str(uuid.uuid4())
    db.create_session(
        session_id=session_id,
        title=f"微信 {account_id[:8]} {user_id[:8]}",
        channel="wechat",
        account_id=account_id,
        wechat_user_id=user_id,
    )
```

新会话**同时**写 title(保持 UI 显示)+ 写正经列(支持索引查询)。

### Phase 6:测试

#### 单元 + 集成测试

- `tests/test_db_index_wechat.py`:
  - 100k 消息 fixture(随机生成),`find_latest_session_by_user` < 5ms
  - `list_sessions` 在混合 channel 数据下,wechat 按 account_id 分组,main 不分组
- `tests/test_db_session_columns.py`:
  - `_ensure_column` 自动迁移幂等(已存在列跳过)
  - 新 `account_id` / `wechat_user_id` 字段写入 + 读出
  - 旧 session(没 account_id / wechat_user_id)优雅处理(查询时过滤 NULL)
- `tests/test_db_wechat_channel_e2e.py`:
  - 重启 wechat_channel,从 DB 重建 user_id → session_id 映射
  - 同一 account 下多个 user 隔离
  - 同一 user 跨多 account 隔离

#### 回归测试

- 旧 `tests/test_db.py`(假定现有):
  - `create_session` 默认行为(不传 account_id)保持兼容
  - `list_sessions` 旧断言(title 解析)→ 改成查 account_id 列

## 验收

- `db.py` 加 3 个 `_ensure_column` + 2 个 partial index
- `find_latest_session_by_user` 改用 `sessions.wechat_user_id` 列,**不再**用 `messages.content LIKE`
- `list_sessions` 改用 SQL GROUP BY,**不再** Python 解析 title
- `wechat_channel.py` 写库走新列
- 100k 消息 fixture:`find_latest_session_by_user` 性能提升 ≥ 50x
- 现有 pytest 全部通过(`tests/test_db.py` 等)
- 新增 `tests/test_db_index_wechat.py` / `tests/test_db_session_columns.py`

## 风险

- **数据迁移窗口**:旧 session 没 account_id / wechat_user_id。改造后,`find_latest_session_by_user` 查不到旧 session — 这是想要的(用户重启 wechat 后,旧 session 不再"继承")。文档里说清楚。
- **partial index 在 SQLite < 3.8 不可用**:Nexus 部署要求 SQLite ≥ 3.24(已有 minimum check),确认无问题。
- **CREATE INDEX 启动期开销**:首次启动 1k session 库 ~50ms,可接受;新会话增量索引更新 ~1ms。
- **`title` 字段保留但不再依赖**:不动现有 UI 显示逻辑(title 仍展示 "微信 ABCD1234 EFGH5678")。

## 实施顺序(commit 拆分)

1. `feat(db): add sessions.account_id / wechat_user_id / channel_meta columns + indexes`
2. `feat(db): create_session accepts account_id / wechat_user_id`
3. `perf(db): find_latest_session_by_user uses sessions.wechat_user_id (no more LIKE)`
4. `perf(db): list_sessions uses SQL NOT EXISTS (no more Python title parse)`
5. `feat(wechat-channel): write account_id / wechat_user_id on session create`
6. `test(db): index perf + session columns + wechat isolation`
7. `docs(db): migration notes for old sessions`