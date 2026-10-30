# 🧠 RecallWeaver (织忆)

> **A lightweight, dynamic memory engine for LLM Agents.**
> **一个面向大语言模型（LLM）的轻量级动态记忆引擎。**

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![SQLite](https://img.shields.io/badge/SQLite-FTS5-green.svg)](https://sqlite.org/)
[![No Docker](https://img.shields.io/badge/Docker-Not%20Required-orange.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

RecallWeaver 致力于解决大模型（LLM）在长对话中的**“上下文失忆”**与**“时间逻辑冲突”**问题。我们摒弃了传统的重型向量数据库（Vector DB）和图数据库，仅依靠纯本地单文件 **SQLite**，打造出极致轻量、完全可解释的 AI 记忆外挂。

---

## 🚀 性能基准 (Performance)

我们在本地对 **100,000 条** 完整记忆数据进行了极限压力测试，得益于底层的 FTS5 全文索引与惰性衰减重排算法，检索结果极其惊人：

*   **数据规模**：100,000 条结构化记忆
*   **查询耗时**：**2.63 毫秒** (比人类眨一次眼睛快 100 倍)
*   **环境依赖**：普通消费级 PC，无需 GPU，无需云服务器。

---

## 💡 解决什么痛点？

*   **传统 RAG 的拉胯**：依赖语义相似度，无法处理“否定句”（如：我不喜欢红色）和“时间演变”（如：我搬家了）。
*   **长文本的灾难**：强行塞入 36MB 的聊天记录，导致大模型“迷失在中间”，且 API 费用高昂。
*   **隐私与成本**：RecallWeaver 的记忆全部存储在本地的一个 `.db` 文件中，零 API 费用，绝对隐私。

---

## ✨ 核心特性 (Features)

- **动态遗忘打分池 (Dynamic Decay Pool)**：像人类一样遗忘。非核心信息随时间指数级衰减，低于阈值进入冷库，极大节省上下文 Token。
- **时空图谱与双时间戳 (Spatiotemporal Graph)**：遇到信息冲突（如“住北京”变“搬上海”），绝不删除旧事实，而是打上 `valid_to` 失效时间戳。默认优先检索最新事实，并支持历史回溯。
- **极速全文检索 (FTS5)**：内置 SQLite FTS5 引擎，毫秒级精准召回。
- **零重型依赖 (Zero Heavy Dependencies)**：纯 Python 构建，拒绝 Docker，拒绝独立图数据库。

---

## 🛠️ 快速开始 (Quick Start)

### 1. 安装与初始化

```bash
# 克隆项目
git clone https://github.com/gaoweimax/recallweaver.git
cd recallweaver

# 创建虚拟环境并安装依赖
python -m venv .venv
# Windows: .venv\Scripts\activate
# Mac/Linux: source .venv/bin/activate
pip install -e .

# 初始化数据库（自动执行 9 张表与 FTS5 触发器）
python -m recallweaver.cli init
