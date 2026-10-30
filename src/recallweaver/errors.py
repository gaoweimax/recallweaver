class RecallWeaverError(Exception):
    """
    这是我们整个项目的“老祖宗”异常类。
    以后不管出什么错，都继承它。这样外部调用时，只要捕获这个基类就行了。
    """
    pass

class ConfigError(RecallWeaverError):
    """
    配置错误：比如该填 API Key 没填，或者路径格式写错了。
    """
    pass

class ValidationError(RecallWeaverError):
    """公开 API 入参或出参不符合契约。"""
    pass

class StorageError(RecallWeaverError):
    """
    存储错误：比如数据库文件被锁住了，或者 SQL 语句写错了导致插入失败。
    """
    pass

class DatabaseError(StorageError):
    """数据库事务或 SQL 操作失败，且事务已回滚。"""
    pass

class RetrievalError(RecallWeaverError):
    """
    检索错误：比如去数据库里搜记忆的时候，搜索引擎崩溃了。
    """
    pass