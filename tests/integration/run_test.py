import sys
import sqlite3
from pathlib import Path

# 把 src 加入路径
sys.path.append(str(Path(__file__).parent.parent.parent / "src"))
from recallweaver.db import db_manager

def test_database():
    print("1. 正在初始化数据库...")
    db_manager.init_db()
    
    print("2. 正在连接数据库检查表名...")
    conn = sqlite3.connect(db_manager.db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    print(f"3. 查到的表: {tables}")
    
    # 断言检查
    assert "memories" in tables, "错误：找不到 memories 表"
    assert "entities" in tables, "错误：找不到 entities 表"
    
    print("✅ 测试完美通过！你的数据库完全符合标准！")

if __name__ == "__main__":
    test_database()