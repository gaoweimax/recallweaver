import sqlite3
from pathlib import Path
from contextlib import contextmanager

# 导入配置和异常
from recallweaver.config import settings
from recallweaver.errors import DatabaseError, StorageError

class Database:
    """
    数据库核心管理类。
    负责连接 SQLite、开启外键约束、执行建表脚本。
    """
    def __init__(self, db_path: str = None):
        # 如果没传路径，就使用 config.py 里的默认路径
        self.db_path = db_path or settings.db_path

    @contextmanager
    def get_connection(self):
        """获取数据库连接的上下文管理器，自动提交或回滚"""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
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

    def init_db(self):
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
            
            print(f"✅ 数据库初始化成功！位置: {self.db_path}")
            
        except Exception as e:
            raise StorageError(f"建表失败: {str(e)}")

# 在最外层实例化，供外部调用
db_manager = Database()