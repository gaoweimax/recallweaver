import sys
import uuid
import time
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent / "src"))
from recallweaver.db import db_manager

def generate_data():
    print("⏳ 正在生成 10 万条数据，请稍候...")
    now = int(time.time())
    
    data = []
    for i in range(100000):
        data.append((
            str(uuid.uuid4()), "default", f"用户编号{i} 的喜好是 事项{i}", "fact",
            1.0, 1.0, 1.0, 0.01, 0, now, 1.0, now, now, "active", now
        ))
    
    try:
        with db_manager.get_connection() as conn:
            conn.execute("INSERT OR IGNORE INTO tenants (id, name, created_at) VALUES ('default', 'Default', ?)", (now,))
            conn.executemany("""
                INSERT INTO memories (
                    id, tenant_id, content, memory_type, 
                    instruction_weight, emotion_weight, base_weight, 
                    decay_lambda, retrieval_count, last_decay_at, 
                    decayed_weight, valid_from, tx_time, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, data)
        print("✅ 10万条数据生成完毕！你的电脑完美扛住了！")
    except Exception as e:
        print(f"❌ 生成失败: {e}")

if __name__ == "__main__":
    generate_data()