"""Check RecallWeaver's SQLite database and required schema objects."""

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from recallweaver.config import settings

CORE_TABLES = ("memories", "entities", "edges")


def check_database(db_path: Path) -> bool:
    """Verify that the database is readable and contains core RecallWeaver tables.

    Args:
        db_path: SQLite database file to inspect.

    Returns:
        ``True`` if all required health checks pass; otherwise ``False``.
    """
    print("🩺 RecallWeaver 数据库健康检查")
    print(f"📍 数据库：{db_path}")

    if not db_path.is_file():
        print("❌ 数据库文件不存在")
        return False

    try:
        with sqlite3.connect(db_path) as connection:
            integrity = connection.execute("PRAGMA quick_check").fetchone()
            if integrity is None or integrity[0] != "ok":
                print(f"❌ SQLite 完整性检查失败：{integrity}")
                return False
            print("✅ SQLite 可连接且完整性检查通过")

            existing_tables = {
                row[0]
                for row in connection.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE type IN ('table', 'view')
                    """
                )
            }
            missing_tables = [
                table for table in CORE_TABLES if table not in existing_tables
            ]
            if missing_tables:
                print(f"❌ 缺少核心表：{', '.join(missing_tables)}")
                return False
            print(f"✅ 核心表已创建：{', '.join(CORE_TABLES)}")

            if "schema_migrations" in existing_tables:
                version = connection.execute(
                    "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
                ).fetchone()[0]
                print(f"ℹ️ 已应用的最高迁移版本：{version}")
            else:
                print("ℹ️ 未发现 schema_migrations，核心表检查仍已通过")
    except sqlite3.Error as exc:
        print(f"❌ 数据库检查失败：{exc}")
        return False

    print("✅ 健康检查通过")
    return True


def main() -> int:
    """Parse command-line options and return a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path(settings.db_path),
        help="SQLite database path (default: configured db_path)",
    )
    args = parser.parse_args()
    return 0 if check_database(args.db_path) else 1


if __name__ == "__main__":
    raise SystemExit(main())