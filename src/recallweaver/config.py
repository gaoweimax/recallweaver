import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """
    这是整个项目的全局配置中心。
    它就像一个控制面板，所有的关键参数都在这里管理，避免代码里到处乱写。
    """
    
    # 1. 数据库文件路径：默认会在项目根目录下生成一个名为 recallweaver.db 的文件
    db_path: str = "recallweaver.db"
    
    # 2. DeepSeek 的 API 密钥（用于以后调用 AI 抽取实体）。默认留空，不报错。
    deepseek_api_key: str = ""
    
    # 3. 遗忘算法的默认衰减系数（数值越大，忘记的速度越快）
    default_decay_lambda: float = 0.01
    
    # 下面这行代码的意思是：让程序自动去读取 .env 文件里的配置（如果有的话）
    # 并且告诉它，如果遇到没定义的变量，就忽略，不要报错
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

# 创建一个全局唯一的配置对象
# 以后在任何文件里，只要写 from recallweaver.config import settings 就能直接用！
settings = Settings()