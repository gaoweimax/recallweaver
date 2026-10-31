"""Create a timestamped, transactionally consistent SQLite backup."""

import argparse
import os
import sqlite3
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Final
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from recallweaver.config import settings

DEFAULT_BACKUP_DIR: Final[Path] = PROJECT_ROOT / "backups"
GREEN: Final[str] = "\033[32m"
RED: Final[str] = "\033[31m"
RESET: Final[str] = "\033[0m"


class BackupError(Exception):
    """Raised when an online database backup cannot be safely completed."""


def create_backup(db_path: Path, output_dir: Path | None = None) -> Path:
    """Create a consistent SQLite backup using SQLite's online backup API.

    Args:
        db_path: Existing source database file.
        output_dir: Destination directory; defaults to the repository's
            ``backups`` directory.

    Returns:
        The path of the completed timestamped backup.

    Raises:
        BackupError: If the source is missing, a filesystem operation fails,
            or SQLite cannot create and verify the backup.
    """
    try:
        source_path = db_path.resolve(strict=True)
        if not source_path.is_file():
            raise BackupError(f"源数据库不是普通文件：{source_path}")

        destination_dir = (output_dir or DEFAULT_BACKUP_DIR).resolve()
        destination_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = destination_dir / f"recallweaver_{timestamp}.db"
        if backup_path.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            backup_path = destination_dir / f"recallweaver_{timestamp}.db"
        if backup_path.resolve() == source_path:
            raise BackupError("备份目标不能与源数据库相同")
    except BackupError:
        raise
    except (OSError, RuntimeError) as exc:
        raise BackupError(f"无法准备备份路径：{exc}") from exc

    temporary_path = destination_dir / f".{backup_path.name}.{uuid4().hex}.tmp"
    try:
        # SQLite 在线备份按页复制快照，避免对主库执行长时间独占锁定。
        with closing(sqlite3.connect(source_path, timeout=30.0)) as source, closing(
            sqlite3.connect(temporary_path, timeout=30.0)
        ) as destination:
            source.backup(destination, pages=256, sleep=0.1)
            integrity = destination.execute("PRAGMA quick_check").fetchone()
            if integrity is None or integrity[0] != "ok":
                raise sqlite3.DatabaseError(
                    f"备份完整性检查失败：{integrity}"
                )
        # 同目录重命名是原子发布步骤，调用方不会看到半成品备份。
        if backup_path.exists():
            raise BackupError(f"备份文件已存在：{backup_path}")
        os.rename(temporary_path, backup_path)
    except (OSError, sqlite3.Error, BackupError) as exc:
        cleanup_error: OSError | None = None
        try:
            if temporary_path.exists():
                temporary_path.unlink()
        except OSError as cleanup_exc:
            cleanup_error = cleanup_exc
        detail = f"数据库在线备份失败：{exc}"
        if cleanup_error is not None:
            detail += f"；临时文件清理失败：{cleanup_error}"
        if isinstance(exc, BackupError) and cleanup_error is None:
            raise
        raise BackupError(detail) from exc

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
        help="Backup directory (default: repository backups directory)",
    )
    args = parser.parse_args()

    try:
        backup_path = create_backup(args.db_path, args.output_dir)
    except BackupError as exc:
        print(f"{RED}❌ 备份失败：{exc}{RESET}", file=sys.stderr)
        return 1

    print(f"{GREEN}✅ 数据库备份完成：{backup_path}{RESET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())