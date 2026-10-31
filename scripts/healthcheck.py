"""Check RecallWeaver's SQLite database and required schema objects."""

import argparse
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import Final

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from recallweaver.config import settings

CORE_TABLES: Final[tuple[str, ...]] = ("memories", "entities", "edges")
GREEN: Final[str] = "\033[32m"
RED: Final[str] = "\033[31m"
RESET: Final[str] = "\033[0m"


def _report(message: str, *, healthy: bool) -> None:
    """Print a health-check line in green or red.

    Args:
        message: Human-readable status or failure detail.
        healthy: Whether the line represents a passing health check.
    """
    color = GREEN if healthy else RED
    print(f"{color}{message}{RESET}")


def check_database(db_path: Path) -> bool:
    """Verify that the database is readable and contains core RecallWeaver tables.

    Args:
        db_path: SQLite database file to inspect.

    Returns:
        ``True`` if all required health checks pass; otherwise ``False``.
    """
    print("🩺 RecallWeaver 数据库健康检查")
    print(f"📍 数据库：{db_path}")

    try:
        if not db_path.is_file():
            _report(f"数据库文件不存在：{db_path}", healthy=False)
            return False
    except OSError as exc:
        _report(f"无法检查数据库文件：{exc}", healthy=False)
        return False

    try:
        with closing(sqlite3.connect(db_path, timeout=5.0)) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            foreign_keys_enabled = connection.execute(
                "PRAGMA foreign_keys"
            ).fetchone()
            if foreign_keys_enabled is None or foreign_keys_enabled[0] != 1:
                _report("SQLite 外键约束未启用", healthy=False)
                return False
            _report("SQLite 外键约束已启用", healthy=True)

            integrity = connection.execute("PRAGMA quick_check").fetchone()
            if integrity is None or integrity[0] != "ok":
                _report(f"SQLite 完整性检查失败：{integrity}", healthy=False)
                return False
            _report("SQLite 可连接且完整性检查通过", healthy=True)

            existing_tables = {
                row[0]
                for row in connection.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE type = 'table'
                    """
                )
            }
            missing_tables = [
                table for table in CORE_TABLES if table not in existing_tables
            ]
            if missing_tables:
                _report(f"缺少核心表：{', '.join(missing_tables)}", healthy=False)
                return False
            _report(f"核心表已创建：{', '.join(CORE_TABLES)}", healthy=True)

            if "schema_migrations" in existing_tables:
                version = connection.execute(
                    "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
                ).fetchone()[0]
                print(f"ℹ️ 已应用的最高迁移版本：{version}")
            else:
                print("ℹ️ 未发现 schema_migrations，核心表检查仍已通过")
    except (OSError, sqlite3.Error) as exc:
        _report(f"数据库检查失败：{exc}", healthy=False)
        return False

    _report("健康检查通过", healthy=True)
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