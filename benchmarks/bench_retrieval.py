import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent / "src"))
from recallweaver.retrieval import Retriever

def benchmark():
    print("🔍 正在 10 万条数据中极限检索...")
    r = Retriever()
    start_time = time.time()
    results = r.search("用户编号888")
    end_time = time.time()
    
    ms = (end_time - start_time) * 1000
    print(f"👉 搜到的结果数: {len(results)}")
    print(f"⏱️ 检索耗时: {ms:.2f} 毫秒")

if __name__ == "__main__":
    benchmark()