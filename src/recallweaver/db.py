import sqlite3
import random
import threading
import time
from pathlib import Path
from contextlib import contextmanager
from collections.abc import Callable
from typing import TypeVar

# 导入配置和异常
from recallweaver.config import settings
from recallweaver.errors import DatabaseError, StorageError

ResultT = TypeVar("ResultT")


class Database:
    """
    数据库核心管理类。
    负责连接 SQLite、开启外键约束、执行建表脚本。
    """
    MAX_TRANSACTION_RETRIES = 5
    MIN_RETRY_DELAY_SECONDS = 0.01
    MAX_RETRY_DELAY_SECONDS = 0.1

    def __init__(self, db_path: str | None = None):
        # 如果没传路径，就使用 config.py 里的默认路径
        self.db_path = db_path or settings.db_path
        self._retry_lock = threading.Lock()
        self.retry_attempts = 0

    @staticmethod
    def _is_locked_error(error: BaseException) -> bool:
        """Check an exception chain for SQLite's transient lock error."""
        current: BaseException | None = error
        while current is not None:
            if (
                isinstance(current, sqlite3.OperationalError)
                and "database is locked" in str(current).lower()
            ):
                return True
            current = current.__cause__
        return False

    def _record_retry(self) -> None:
        """Increment the concurrent-safe count of recovered lock retries."""
        with self._retry_lock:
            self.retry_attempts += 1

    def run_transaction(
        self,
        operation: Callable[[sqlite3.Connection], ResultT],
        *,
        max_retries: int = MAX_TRANSACTION_RETRIES,
    ) -> ResultT:
        """Run and, on SQLITE_BUSY, retry an entire atomic transaction.

        Each retry opens a new connection, starts a new ``BEGIN IMMEDIATE``
        transaction, reruns the callback, then commits through
        :meth:`get_connection`. On a lock error, that attempt is rolled back
        and closed before randomized exponential backoff; partial writes are
        therefore never retained between attempts.

        Args:
            operation: Database-only callback to execute atomically. It should
                not perform external side effects because it may run repeatedly.
            max_retries: Number of retries after the initial attempt.

        Returns:
            The callback's result after its transaction commits.

        Raises:
            ValueError: If ``max_retries`` is negative.
            DatabaseError: If the operation fails, or a database lock remains
                after the configured retries.
        """
        def execute_once() -> ResultT:
            with self.get_connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                return operation(connection)

        return self.execute_with_retry(execute_once, max_retries=max_retries)

    def execute_with_retry(
        self,
        operation: Callable[[], ResultT],
        *,
        max_retries: int = MAX_TRANSACTION_RETRIES,
    ) -> ResultT:
        """Retry an entire database operation after transient SQLite locks.

        The callback must own its complete transaction boundary: any failed
        attempt must roll back before the callback raises. This allows existing
        transactional operations to be replayed as a unit without retrying an
        individual statement inside a partially applied transaction.

        Args:
            operation: Zero-argument database operation to retry atomically.
            max_retries: Number of retries after the initial attempt.

        Returns:
            The callback's result after successful completion.

        Raises:
            ValueError: If ``max_retries`` is negative.
            DatabaseError: If an operation fails or lock retries are exhausted.
        """
        if (
            isinstance(max_retries, bool)
            or not isinstance(max_retries, int)
            or max_retries < 0
        ):
            raise ValueError("max_retries 必须是非负整数")

        for attempt in range(max_retries + 1):
            try:
                return operation()
            except DatabaseError as error:
                if not self._is_locked_error(error):
                    raise
                if attempt >= max_retries:
                    raise DatabaseError(
                        "数据库操作在重试后仍被锁定："
                        f"{max_retries} 次重试均已耗尽"
                    ) from error
            except sqlite3.OperationalError as error:
                if "database is locked" not in str(error).lower():
                    raise DatabaseError(
                        f"数据库事务执行失败: {error}"
                    ) from error
                if attempt >= max_retries:
                    raise DatabaseError(
                        "数据库操作在重试后仍被锁定："
                        f"{max_retries} 次重试均已耗尽"
                    ) from error
            except sqlite3.Error as error:
                raise DatabaseError(f"数据库操作执行失败: {error}") from error

            self._record_retry()
            delay_ceiling = min(
                self.MAX_RETRY_DELAY_SECONDS,
                self.MIN_RETRY_DELAY_SECONDS * (2**attempt),
            )
            time.sleep(
                random.uniform(self.MIN_RETRY_DELAY_SECONDS, delay_ceiling)
            )

    @contextmanager
    def get_connection(self):
        """获取数据库连接的上下文管理器，自动提交或回滚"""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=1.0)
            # 极度重要：开启 SQLite 的外键约束
            conn.execute("PRAGMA foreign_keys = ON;")
            # 让查询结果可以通过列名访问
            conn.row_factory = sqlite3.Row
            yield conn
            conn.commit()
        except sqlite3.Error as e:
            if conn:
                conn.rollback()
            raise DatabaseError(f"数据库操作失败: {str(e)}") from e
        except BaseException:
            # 不仅 SQL 错误，业务层抛出的异常也必须撤销尚未提交的写入。
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()

    def init_db(self, verbose: bool = True):
        """读取 schema.sql 并初始化数据库"""
        # 定位到项目根目录的 schema.sql
        schema_path = Path(__file__).parent.parent.parent / "schema.sql"
        
        if not schema_path.exists():
            raise StorageError(f"找不到建表图纸: {schema_path}")

        try:
            with open(schema_path, 'r', encoding='utf-8') as f:
                schema_sql = f.read()

            with self.get_connection() as conn:
                conn.executescript(schema_sql)
            
            if verbose:
                print(f"数据库初始化成功！位置: {self.db_path}")
            
        except Exception as e:
            raise StorageError(f"建表失败: {str(e)}")

# 在最外层实例化，供外部调用
db_manager = Database()