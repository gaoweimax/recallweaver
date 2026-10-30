"""全项目共享的 pytest 夹具与测试环境设置。"""

# sys.path 用于确保直接在仓库根目录运行 pytest 时能够导入 src 布局中的项目包。
import sys
# Path 用于根据本文件的位置定位仓库根目录和 src 目录。
from pathlib import Path
# Iterator 用于标注会在测试结束阶段执行清理操作的 yield 夹具。
from typing import Iterator

# pytest 提供测试夹具机制以及明确的测试生命周期管理。
import pytest

# 当前文件位于仓库根目录/tests/conftest.py，向上一级即可定位仓库根目录。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
# 本项目使用 src 布局；将 src 放到导入路径首位，确保导入的是当前工作区代码。
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

# 延迟在路径准备完成后导入项目对象，避免测试环境依赖已安装的外部副本。
from recallweaver.db import Database, db_manager


@pytest.fixture
def test_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Database]:
    """为每个测试建立独立的临时 SQLite 数据库并在结束后清理。

    使用 pytest 的 ``tmp_path`` 为每个测试函数分配独立目录，因此不同测试
    不会共享数据，也不会访问或修改配置中的真实 ``recallweaver.db`` 文件。
    默认数据库管理器的路径仅在当前测试生命周期内被替换；``monkeypatch``
    会在测试结束时恢复原值，夹具随后显式删除本次创建的数据库文件。
    """
    # 为当前测试创建一个独立的数据库文件，而不是复用项目默认数据库路径。
    database_path = tmp_path / "test_temp.db"
    # 让现有单例管理器在本测试中连接到专属临时文件。
    monkeypatch.setattr(db_manager, "db_path", str(database_path))

    # 初始化完整 schema，确保外键、索引、触发器和 FTS5 表均可用于集成测试。
    db_manager.init_db()

    try:
        # 返回共享管理器，使各测试调用项目真实的持久化和检索代码路径。
        yield db_manager
    finally:
        # 所有连接均应由各自的 with 块关闭；确认文件存在后再执行定向清理。
        if database_path.exists():
            database_path.unlink()