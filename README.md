```markdown
<div align="center">

# 🧠 RecallWeaver (织忆)

**赋予 LLM Agent 永不磨灭的长期记忆**

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg?style=flat-square)](https://www.python.org/)
[![PyPI version](https://img.shields.io/badge/PyPI-v1.2.2-blue.svg?style=flat-square)](https://pypi.org/project/recallweaver/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/Tests-100%25%20Passed-brightgreen.svg?style=flat-square)](#)

**拒绝 Docker，拒绝向量库，拒绝算力黑洞。**
仅用单文件 SQLite 与纯 Python，为你的 AI 伴侣或本地 Agent 手搓一个工业级“海马体”。

[核心痛点](#-为什么需要-recallweaver) · [性能数据](#-极限压测数据) · [一键安装](#-快速开始) · [DSH 桌宠接入](#-dsh-桌宠接入终极指南) · [API 示例](#-python-api-基础用法)

</div>

---

## 💔 为什么需要 RecallWeaver？

如果你正在开发本地 AI 桌宠（如 DSH 框架下的“大肥鱼”），你一定经历过这种崩溃：
1. **金鱼记忆**：刚聊完的设定，刷新或新开会话后，AI 秒变陌生人。
2. **精神分裂**：你前天说住北京，昨天搬去上海，传统 RAG 会把两个事实同时塞给 AI，让它胡言乱语。
3. **算力刺客**：为了记住一句话，你要去部署几个 G 的向量数据库，还要调高昂的 Token 去跑全量上下文。

**RecallWeaver 的破局：**
它像一个真正的生物大脑。**双时间戳图谱**让 AI 明白“你现在住上海，以前住北京”；**动态遗忘算法**让废话自动沉底，只保留核心事实；**纯本地 SQLite** 让数据绝对安全，永不丢失。

---

## 📊 极限压测数据

本项目拒绝自嗨，所有数据均在 50 并发、十万级数据量下实测得出：

| 测试维度 | 测试条件 | 结果 |
| :--- | :--- | :--- |
| **并发抗压** | 50 线程高频混合读写，持续 30 秒 | **0 死锁**，成功率 100% |
| **长稳延迟** | 1800 秒不间断浸泡压测 | **P99 延迟 3.459 ms** |
| **检索精度** | 100 组高仿真噪音数据召回测试 | **Precision / Recall 1.0** |

*(压测脚本均存放于 `/benchmarks` 目录，欢迎复现打假)*

---

## 🚀 快速开始

### 1. 环境要求
- Python 3.11 或更高版本
- 一个 DeepSeek API Key（用于底层实体抽取与大模型对话）

### 2. 一键安装
```bash
pip install recallweaver==1.2.2
```

### 3. 配置密钥
在终端中设置环境变量（Windows 示例）：
```bash
set DEEPSEEK_API_KEY=sk-你的真实Key
```
*(或者将 `DEEPSEEK_API_KEY` 写入系统的环境变量中)*

---

## 🧩 DSH 桌宠接入终极指南 (以“大肥鱼”为例)

如果你在使用 **DeepSeek Harness (DSH)** 框架开发桌宠，请严格按照以下步骤，让你的大肥鱼瞬间获得终身记忆。

### 为什么要接入？
DSH 原生上下文有限。接入 RecallWeaver 后，每次对话，插件会自动拦截大肥鱼的底层请求，去本地库里捞出你的核心设定（如“你过敏”、“你喜欢吃白米饭”），强行注入给大模型。

### 详细接入四步走：

#### 第一步：获取插件包
下载本仓库中的 `dsh-plugin-recallweaver` 文件夹。
找到你电脑上的 DSH 插件目录（通常在 `C:\Users\你的用户名\.dsh\plugins\`），将刚才的文件夹整个复制进去。

#### 第二步：修改 DSH 配置
找到 DSH 的配置文件（一般在 `~/.dsh/config/cordis.patch.yml`）。
用记事本打开它，在文件末尾粘贴以下配置代码：

```yaml
- insert:
    - id: recallweaver-memory
      name: recallweaver-dsh
      # 告诉 DSH 拦截 System Prompt 注入过程
      inject: ['systemPrompt']
      config:
        # Python 解释器路径（如果在虚拟环境里，请填写 python 的绝对路径）
        python: python
        # 检索超时限制（毫秒）
        timeoutMs: 10000
```

#### 第三步：重启 DSH
彻底退出 DSH 客户端（注意右下角托盘图标也要右键退出），然后重新启动桌面端程序。

#### 第四步：灵魂验证（如何测试有没有接上）
1. **注入记忆**：对桌宠说：“大肥鱼记住，我昨天从北京搬到杭州了，另外我对花生过敏。”
2. **强制失忆**：在 DSH 客户端里开启一个**全新的会话**（清空所有上下文）。
3. **见证奇迹**：在新会话里问：“大肥鱼，我现在住哪？给我推荐点零食。”
   👉 **预期回答**：“鱼片！你不是搬到杭州了吗？还有你对花生过敏，千万别吃花生相关的零食！”
*(如果回答正确，恭喜你，你的大肥鱼已经拥有了永久记忆。)*

### 🚑 常见报错排查 (FAQ)
*   **报错 `ModuleNotFoundError`**：说明 DSH 启动的 Python 和你安装 `recallweaver` 的 Python 不是同一个。请把配置里的 `python: python` 改为你的真实绝对路径（如 `C:\Python311\python.exe`）。
*   **桌宠没反应**：检查 `pip install recallweaver` 是否装在全局环境里，或者修改 `cordis.patch.yml` 后是否彻底重启了 DSH。

---

## 💻 Python API 基础用法

如果你不是 DSH 用户，想在普通的 Python 脚本或别的 Agent 里接入：

```python
from recallweaver.api import RecallWeaverAPI

# 1. 初始化（数据全存这个 db 文件里）
api = RecallWeaverAPI(db_path="./my_agent_memory.db")

# 2. 存入事实（自动处理时间冲突，北京会被标记为失效）
api.remember_triple("用户", "住在", "北京")
api.remember_triple("用户", "住在", "上海") 

# 3. 存入废话（底层自动衰减，不占用后续对话 Token）
api.add_memory("今天天气真不错，好想吃火锅。")

# 4. 检索（自动过滤废话，按得分重排）
results = api.recall("用户现在住哪", limit=3)
for res in results:
    print(f"记忆内容: {res.content} | 衰减得分: {res.score:.2f}")
```

---

## 🏗️ 项目架构

```text
src/recallweaver/
├── api.py              # 统一对外门面，极度简洁
├── config.py           # 环境变量与路径加载
├── db.py               # SQLite WAL 模式、死锁重试机制
├── models.py           # Pydantic 强数据校验
├── decay_engine.py     # 指数衰减算法（动态遗忘）
├── graph.py            # 递归 CTE 时空图谱（防死循环）
├── memory_manager.py   # 双时间戳事实冲突处理核心
├── retrieval.py        # FTS5 混合检索与权重重排
├── server.py           # FastAPI 服务层
└── plugins/            # DSH 等框架的适配插件
```

---

## 🛡️ 免责声明与合规说明

本项目仅供学习与研究使用。因为 `RecallWeaver` 纯本地化运行，你的所有数据与记忆都存储在你本人的计算机中。用户需自行承担接入大模型产生的 API 费用及与 AI 交互产生的任何风险。

## 📄 协议

本项目基于 [MIT License](https://opensource.org/licenses/MIT) 协议开源。你可以随意修改、商用、分发，但请保留原作者版权声明。
```
