"""RecallWeaver 的公共包接口。

通过在包初始化时重新导出常用对象，外部代码可以直接从
``recallweaver`` 导入配置、异常类型和数据库管理器，而不必记住内部模块路径。
"""

# 暴露全局配置实例，使调用方可以使用 ``recallweaver.settings`` 读取项目配置。
from .config import settings
# 暴露项目异常体系的基类，便于调用方统一捕获 RecallWeaver 相关错误。
from .errors import RecallWeaverError
# 暴露数据库管理类和默认管理器，分别用于创建自定义实例或直接操作默认数据库。
from .db import Database, db_manager

# 显式声明包的公共接口，避免内部实现细节被误认为稳定的公开 API。
__all__ = ["settings", "RecallWeaverError", "Database", "db_manager"]