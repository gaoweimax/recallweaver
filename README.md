# 🧠 RecallWeaver (织忆)

一个面向大语言模型（LLM）的轻量级动态记忆引擎。

**核心特性：遗忘权重 + 时空图谱 + 可解释检索。**
拒绝重型依赖：无 Docker，无独立图数据库，只用 SQLite。

## 🚀 解决什么痛点？

大模型存在“上下文失忆”和“时间逻辑冲突”。传统 RAG 依赖重型向量库，且无法处理否定句和事实演变（比如用户昨天住北京，今天搬到了上海）。

本项目通过动态衰减算法和双时间戳机制，让 AI 像人类一样拥有真正的长时记忆。

## ✨ 核心功能

- **动态遗忘打分池**：像人类一样遗忘。随着时间推移，非核心信息自动降权进入冷库。
- **时空图谱 (双时间戳)**：绝不删除旧事实，通过 `valid_from` 和 `valid_to` 追踪事实演变。
- **极简部署**：纯 Python 与 SQLite (FTS5) 构建。
- **可解释性**：每次检索结果都会返回召回明细。

## 🛠️ 快速开始

1. 克隆项目：`git clone https://github.com/gaoweimax/recallweaver.git`
2. 初始化数据库：`python -c "import sqlite3; c=sqlite3.connect('recallweaver.db'); c.executescript(open('schema.sql').read())"`
