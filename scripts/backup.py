"""Create a timestamped, transactionally consistent SQLite backup."""

import argparse
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from recallweaver.config import settings


def create_backup(db_path: Path, output_dir: Path | None = None) -> Path:
    """Create a consistent SQLite backup using SQLite's online backup API.

    Args:
        db_path: Existing source database file.
        output_dir: Destination directory; defaults to the source directory.

    Returns:
        The path of the completed timestamped backup.

    Raises:
        FileNotFoundError: If the source database is missing.
        FileExistsError: If the timestamped destination already exists.
        OSError: If the destination cannot be created or removed after failure.
        sqlite3.Error: If SQLite cannot read or back up the source database.
    """
    if not db_path.is_file():
        raise FileNotFoundError(f"源数据库不存在：{db_path}")

    destination_dir = output_dir or db_path.parent
    destination_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = destination_dir / f"{db_path.stem}_{timestamp}{db_path.suffix}"
    if backup_path.exists():
        raise FileExistsError(f"备份文件已存在：{backup_path}")

    try:
        with closing(sqlite3.connect(db_path)) as source, closing(
            sqlite3.connect(backup_path)
        ) as destination:
            source.backup(destination)
            integrity = destination.execute("PRAGMA quick_check").fetchone()
            if integrity is None or integrity[0] != "ok":
                raise sqlite3.DatabaseError(
                    f"备份完整性检查失败：{integrity}"
                )
    except (OSError, sqlite3.Error):
        if backup_path.exists():
            backup_path.unlink()
        raise

    return backup_path


def main() -> int:
    """Parse backup options, print the result, and return a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path(settings.db_path),
        help="SQLite database path (default: configured db_path)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Backup directory (default: source database directory)",
    )
    args = parser.parse_args()

    try:
        backup_path = create_backup(args.db_path, args.output_dir)
    except (FileExistsError, FileNotFoundError, OSError, sqlite3.Error) as exc:
        print(f"❌ 备份失败：{exc}", file=sys.stderr)
        return 1

    print(f"✅ 数据库备份完成：{backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())