# 🧠 织忆 (RecallWeaver)

**赋予 LLM Agent 穿越时间的记忆能力。零 Docker、零向量库、纯单文件 SQLite 构筑的工业级 AI 海马体。**

<p align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.11+"></a>
  <a href="#"><img src="https://img.shields.io/badge/Tests-Passing-brightgreen?style=for-the-badge&logo=pytest&logoColor=white" alt="Tests Passing"></a>
  <a href="#"><img src="https://img.shields.io/badge/Latency-10ms-blueviolet?style=for-the-badge&logo=speedtest&logoColor=white" alt="Latency 10ms"></a>
  <a href="#"><img src="https://img.shields.io/badge/Precision-1.0-success?style=for-the-badge" alt="Precision 1.0"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge" alt="MIT License"></a>
</p>

![Demo](./assets/demo.gif)

> 看！大肥鱼在真实 DeepSeek 环境下，如何利用纯本地记忆识破主人的花生过敏陷阱，并完成北京到杭州的时空转移。

**无需 Docker，无需向量数据库，也不必把整段对话塞进上下文。** RecallWeaver 为 Agent 提供可演变、可检索、会遗忘的长期记忆。

[核心特性](#-核心高光特性) · [性能与质量](#-性能与质量验证) · [快速开始](#-快速开始) · [架构](#-项目架构)

---

## 💥 为什么选择 RecallWeaver？

传统 RAG 记忆方案经常把“检索到文本”误当成“理解了事实”。当对话变长、事实更新、闲聊增多时，常见问题会逐渐显现：

| 传统方案的痛点 | 可能造成的结果 |
|---|---|
| 🕰️ **时间逻辑混乱** | “以前住在北京”与“现在住在杭州”同时进入上下文，Agent 前后矛盾，像是“精神分裂”。 |
| 🔊 **高频噪音挤占上下文** | 股票涨跌、天气闲聊等高频内容挤掉过敏、住址等真正重要的事实。 |
| 🧱 **部署成本高** | 重型向量库、图数据库和配套服务带来额外的部署、运维与资源成本。 |

### RecallWeaver 的破局方式

以**单文件 SQLite** 为持久化核心，结合**双时间戳事实版本**与**动态遗忘评分**：事实更新时保留历史并关闭旧版本；检索时综合相关性、时效与权重，并通过分数阈值过滤低价值噪音。轻量部署，也能明确回答“现在是什么”以及“以前是什么”。

---

## 📊 性能与质量验证

以下为项目压测与评测记录中的结果：

### 🔥 并发与长稳压测

| 持续时间 | 并发线程 | 总请求数 | 成功率 | 死锁 | P99 延迟 |
|---:|---:|---:|---:|---:|---:|
| 1,800 秒 | 50 | 180,000 | **100%** | **0** | **10.5 ms** |

### 🎯 检索质量评估

基于 100 组高仿真测试数据，评估检索结果与核心事实标准答案的一致性：

| Precision | Recall | F1-Score | 评测样本 |
|---:|---:|---:|---:|
| **1.0000** | **1.0000** | **1.0000** | 100 组 |

### 🧪 混沌工程边界验证

| 场景 | 验证结果 |
|---|---|
| SQL 注入文本 | 参数化查询防护通过 |
| 高频恶意检索刷分 | 权重加成上限与噪音阈值拦截通过 |
| 空数据库调用 | 空结果兜底通过 |

> 这些数字是项目当前记录的基准结果。实际表现会随硬件、SQLite 版本、数据集和运行配置变化。

---

## ✨ 核心高光特性

### 🕰️ 双时间戳时空图谱 (Temporal Graph)

事实带有 `valid_from` 与 `valid_to`。同一主谓关系发生冲突时，系统在事务中关闭旧事实并写入新事实，历史不被覆盖。基于 SQLite 递归 CTE 的图谱遍历支持多跳关系查询，让 Agent 能区分事实的当前状态与历史状态。

### 📉 动态遗忘打分池 (Decay Pool)

以指数衰减为基础，综合记忆权重与检索反馈计算候选得分。检索次数的加成受有用性权重和上限约束；最终结果还会经过分数阈值截断，避免无关闲聊仅凭频繁出现就长期霸屏。

### ⚡ 混合检索 (Hybrid Search)

结合 SQLite FTS5 全文检索与图谱召回，再由衰减引擎统一重排。FTS5 的 `trigram` 分词支持中文连续子串匹配；结构化事实则可通过图谱关系查找，互补关键词召回与事实关联。

### 🔎 可观测、可解释

通过结构化日志、Trace ID 与线程安全指标记录核心链路状态。召回结果包含来源、分数及有效时间信息，便于排查与理解 Agent 为什么记住或忽略某条信息。

---

## 🚀 快速开始

### 1. 克隆并安装

```bash
git clone https://github.com/gaoweimax/recallweaver.git
cd recallweaver
python -m pip install -e .
```

### 2. 配置 DeepSeek 密钥

示例使用环境变量读取密钥。请替换为你自己的密钥，**不要把真实密钥写入代码或提交到仓库**。

```bash
export DEEPSEEK_API_KEY="sk-..."
```

Windows PowerShell 可使用：

```powershell
$env:DEEPSEEK_API_KEY = "sk-..."
```

### 3. 写入事实并检索

```python
from recallweaver.api import RecallWeaverAPI

api = RecallWeaverAPI(db_path="recallweaver.db")

# 记录结构化事实
api.remember_triple(
    subject="张三",
    predicate="住在",
    object_="杭州",
)

# 检索与问题相关的记忆
results = api.recall("张三住在哪里？", limit=3)
for memory in results:
    print(f"[{memory.score:.3f}] {memory.content or memory.object}")
```

运行带真实 DeepSeek API 的 Rich 终端示例：

```bash
python examples/deepseek_agent.py
```

---

## 🏗️ 项目架构

```text
src/recallweaver/
├── api.py                 # 统一 API 门面与输入校验
├── config.py              # L1：环境与配置管理
├── errors.py              # 领域异常定义
├── db.py                  # SQLite 连接、事务与重试
├── models.py              # Pydantic 输入/输出模型
├── memory_manager.py      # 记忆持久化与双时间戳冲突处理
├── graph.py               # 图谱关系查询与递归 CTE
├── retrieval.py           # FTS5 与图谱混合检索、结果重排
├── decay_engine.py        # L3：衰减评分、有用性权重与阈值过滤
├── extraction/            # 实体与事实抽取组件
└── observability/
    ├── logging.py         # 结构化日志与敏感信息处理
    └── metrics.py         # 线程安全的内存指标
```

模块按职责拆分：**L1 配置与校验**提供稳定边界，**L3 检索与衰减算法**专注记忆质量，**L6 可观测性**提供日志和运行指标。架构取舍与演进记录见 [`docs/adr/`](docs/adr/)。

---

## 🧑‍💻 开发与测试

安装开发依赖后，可运行单元与集成测试：

```bash
python -m pip install -e ".[dev]"
pytest -v
```

检索基准脚本：

```bash
python benchmarks/bench_retrieval.py
```

## 🤝 参与贡献

欢迎通过 Issue 讨论问题、提交改进建议或贡献代码。涉及行为变更时，请一并补充相应测试与文档。

## 📄 开源协议

RecallWeaver 采用 [MIT License](LICENSE)。
