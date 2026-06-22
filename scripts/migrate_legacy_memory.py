"""一次性把 nexus.db ``memory`` 表的 explicit 记录迁到 ``~/.nexus/AGENTS.md``。

WHY: nexus v0.1.0 自定义 ``MemoryService`` 已被 deepagents 框架替代;
旧 ``memory`` 表里的 explicit 偏好是用户的真实数据,不能丢。session/
evolved 类型是会话残留 / 自动蒸馏产物,丢弃无所谓。

迁移步骤:
  1. 读 ``memory`` 表 ``is_active=1 AND memory_type='explicit'`` 的所有行
  2. 追加到 ``~/.nexus/AGENTS.md`` 的 ``## Migrated Preferences`` 段
  3. ``ALTER TABLE memory RENAME TO memory_legacy``(数据保留,可 grep 历史)
  4. ``VACUUM`` 回收空间

幂等:已迁过的(``memory_legacy`` 已存在)直接退出 0,不再追加。

用法:
    python scripts/migrate_legacy_memory.py [--dry-run] [--db-path PATH]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

DEFAULT_DB_PATH = Path.home() / ".nexus" / "nexus.db"
USER_AGENTS_MD = Path.home() / ".nexus" / "AGENTS.md"
MIGRATED_HEADING = "## Migrated Preferences"


def already_migrated(conn: sqlite3.Connection) -> bool:
    """``memory_legacy`` 表已存在 → 之前跑过,跳过。"""
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='memory_legacy'").fetchone()
    return row is not None


def fetch_explicit_rows(conn: sqlite3.Connection) -> list[dict]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT id, memory_type, category, key, value
        FROM memory
        WHERE is_active = 1 AND memory_type = 'explicit'
        ORDER BY category, key
        """
    ).fetchall()
    # sqlite3.Row 在 Python 3.14 下不可直接 ``dict(row)``,要按 keys 显式转
    return [{key: row[key] for key in row.keys()} for row in rows]


def render_migrated_block(rows: list[dict]) -> str:
    if not rows:
        return ""
    lines = [MIGRATED_HEADING, ""]
    for row in rows:
        lines.append(f"- [{row['category']}] {row['key']}: {row['value']}")
    return "\n".join(lines) + "\n"


def append_to_agents_md(block: str) -> None:
    """把 block 追加到 USER_AGENTS_MD,已有 MIGRATED_HEADING 则替换该段。"""
    USER_AGENTS_MD.parent.mkdir(parents=True, exist_ok=True)
    if USER_AGENTS_MD.exists():
        existing = USER_AGENTS_MD.read_text(encoding="utf-8")
    else:
        existing = "<!-- managed by deepagents MemoryMiddleware. 用户/agent 可自由编辑。 -->\n\n# Nexus 用户偏好\n"

    if MIGRATED_HEADING in existing:
        # 替换现有段(以 ## 开头下一个 heading 为止)
        head, _, rest = existing.partition(MIGRATED_HEADING)
        # 找下一个 "## " 或文件末尾
        next_heading_idx = rest.find("\n## ")
        if next_heading_idx >= 0:
            rest = rest[next_heading_idx:]
            new_rest = "\n" + block + rest
        else:
            new_rest = "\n" + block
        new_content = head + new_rest
    else:
        new_content = existing.rstrip() + "\n\n" + block

    USER_AGENTS_MD.write_text(new_content, encoding="utf-8")


def rename_memory_table(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE memory RENAME TO memory_legacy")
    conn.commit()


def vacuum(conn: sqlite3.Connection) -> None:
    conn.execute("VACUUM")


def run(db_path: Path, *, dry_run: bool) -> int:
    if not db_path.exists():
        print(f"[migrate] db 不存在: {db_path} (跳过,首次安装无需迁移)", file=sys.stderr)
        return 0

    conn = sqlite3.connect(str(db_path))
    try:
        if already_migrated(conn):
            print("[migrate] memory_legacy 已存在,跳过")
            return 0

        # 检查 memory 表是否存在
        has_memory = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='memory'").fetchone()
        if not has_memory:
            print("[migrate] memory 表不存在,无需迁移")
            return 0

        rows = fetch_explicit_rows(conn)
        skipped = conn.execute(
            "SELECT COUNT(*) FROM memory WHERE NOT (is_active = 1 AND memory_type = 'explicit')"
        ).fetchone()[0]

        block = render_migrated_block(rows)
        if dry_run:
            print(f"[migrate --dry-run] 将迁移 {len(rows)} 条 explicit,跳过 {skipped} 条")
            if block:
                print("--- 写入 ~/.nexus/AGENTS.md ---")
                print(block)
            return 0

        if block:
            append_to_agents_md(block)
        rename_memory_table(conn)
        vacuum(conn)
        print(f"[migrate] 完成: 迁移 {len(rows)} 条 explicit 偏好 → {USER_AGENTS_MD}, 跳过 {skipped} 条非 explicit")
        return 0
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH, help="nexus.db 路径")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要写入的内容,不实际修改")
    args = parser.parse_args()
    return run(args.db_path, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
