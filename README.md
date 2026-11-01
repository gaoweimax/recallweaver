
```markdown
# RecallWeaver (织忆)

> **“让 AI 桌宠拥有不会崩塌的长期记忆。”**

RecallWeaver 为 AI Agent 提供可本地运行、可追溯时间变化的长期记忆能力。以单文件 SQLite 为存储基础，将文本记忆、关系事实、历史状态和动态相关性评分放在同一套轻量系统中。**拒绝 Docker，拒绝重型向量数据库。**

[![Python 3.11+](https://img.shields.io/badge/Python-3.11.9-blue)](https://www.python.org/)
[![MIT License](https://img.shields.io/badge/License-MIT-green)](https://opensource.org/license/mit/)
[![PyPI v1.2.2](https://img.shields.io/badge/PyPI-v1.2.2-blue)](https://pypi.org/project/recallweaver/1.2.2/)

> ** 运行时版本说明：** 当前发布包元数据将 Python 精确锁定为 `3.11.9`，请在符合该版本的环境中安装使用。

---

##  为什么需要 RecallWeaver？

把历史对话简单切块后交给向量检索，并不等于拥有可靠的长期记忆。你在折腾本地 AI 伴侣（如 DSH 桌宠“大肥鱼”）时，一定经历过这些绝望：

1. **金鱼记忆**：刚聊过的设定，刷新或新开会话后，AI 秒变陌生人，人设崩塌。
2. **时间精分**：你前天说住北京，昨天搬去上海。传统 RAG 会把两个事实同时塞给模型，导致 AI 回答“您既在北京又在上海”。
3. **基础设施过重**：为了记住几句话，你要去配几个 G 的向量库、折腾 Docker，最后发现还不如直接塞长文本上下文。

**RecallWeaver 破局点：**
它像一个真正的生物大脑。**双时间戳**让 AI 明白“你现在住上海，以前住北京”；**动态遗忘**让废话自动沉底，节省 Token；**纯本地 SQLite** 让部署成本降为零。

---

##  极限压测数据（拒绝自嗨）

本项目在本地普通消费级 PC（无 GPU）上进行了极度苛刻的测试：

| 测试项 | 真实数据记录 | 意味着什么 |
| :--- | :--- | :--- |
| **长稳压测** | **1,800 秒**、50 并发，**0 死锁** | 极高并发读写，稳如老狗，绝不崩溃。 |
| **P99 延迟** | **10.5 ms** | 10万级数据下，99% 的检索都在 10 毫秒内极速完成。 |
| **检索精度** | Precision / Recall **1.0** | 100 组高仿真噪音下，不瞎编，不遗漏。 |

*(压测脚本全在 `/benchmarks` 目录，欢迎复现打假)*

---

##  快速开始

### 1. 环境准备
当前包要求 **Python 3.11.9**。检查你的版本：
```shell
python --version
```

### 2. 一键安装
```shell
python -m pip install recallweaver==1.2.2
```

### 3. 配置环境变量
在终端中设置密钥（用于大模型抽取与对话）：
```powershell
$env:DEEPSEEK_API_KEY = "sk-你的真实密钥"
$env:DB_PATH = "C:\data\recallweaver.db"
```
*(也可以写在项目根目录的 `.env` 文件里)*

### 4. 极简 Python Demo
直接保存为 `quickstart.py` 运行：

```python
from recallweaver import RecallWeaverAPI

api = RecallWeaverAPI("recallweaver.db")
tenant_id = "user-001"

# 1. 写入核心事实（自动处理时间冲突，旧地址会失效）
api.remember_triple("用户", "住在", "北京", tenant_id=tenant_id)
api.remember_triple("用户", "住在", "上海", tenant_id=tenant_id) 

# 2. 写入一段废话文本
api.add_memory("今天天气真好，好想吃火锅。", tenant_id=tenant_id)

# 3. 混合检索（自动过滤废话，按得分重排）
results = api.recall("用户现在住哪？", limit=3, tenant_id=tenant_id)
for res in results:
    print(f"- {res.content} (得分: {res.score:.3f})")
```

---

##  DSH 桌宠接入终极指南

仓库中包含完整的 Node.js 插件包，路径为 [`dsh-plugin-recallweaver/`](dsh-plugin-recallweaver/)。它通过 Cordis 插入点，自动调用本机 Python 进行记忆检索。

> **⚠️ 重要提示：** 当前插件入口仅调用 `recall` 检索命令，**不会**自动拦截 DSH 聊天并写入数据库。你需要先用 Python API 或 CLI 把核心记忆写进去，再在 DSH 里提问测试。

### 详细接入四步走：

#### 第一步：安装 Python 包与放置插件
1. 确保你的 DSH 所用的 Python 环境已安装：`pip install recallweaver==1.2.2`。
2. 把仓库里的 `dsh-plugin-recallweaver` 文件夹，完整复制到 DSH 安装目录的 `plugins/` 下。
   *(通常路径为 `C:\Users\你的用户名\.dsh\plugins\`)*

#### 第二步：修改 DSH Profile 配置
1. 找到 DSH 正在使用的 profile 目录（一般在 `~/.dsh/profiles/web/` 或 `desktop/`）。
2. 打开该目录下的 `cordis.patch.yml` 文件，在末尾追加以下配置：

```yaml
- insert:
    - id: recallweaver-memory
      name: recallweaver-memory
      inject: [systemPrompt]
      config:
        # 强烈建议填写 Python 的绝对路径，防止 DSH 找不到环境
        python: 'C:\Python311\python.exe' 
        # 数据库绝对路径（必须包含你已经写入的记忆）
        dbPath: 'C:\data\recallweaver.db'
        timeoutMs: 10000
```

#### 第三步：重启并验证
1. 彻底退出 DSH（包括右下角托盘）。
2. 重新打开，对大肥鱼提问：“大肥鱼，我现在住哪？”
3. 如果它能回答出“上海”，说明记忆已成功注入！

*(如果在终端能查到记忆，但 DSH 读不到，请检查 YAML 里的 `python` 和 `dbPath` 路径是否正确。)*

---

## 🏗️ 项目结构与核心职责

```text
recallweaver/
├── dsh-plugin-recallweaver/       # DSH 桌宠专属插件包 (Node.js)
│   ├── index.js                   # Cordis 插件入口，负责拦截聊天并调用 Python
│   ├── cli-bridge.py              # 解决中文乱码的 Python CLI 桥接脚本
│   ├── package.json               # 插件元数据与启动入口声明
│   └── cordis.patch.yml           # DSH 注入点配置示例
│
├── docs/                          # 工业级文档区
│   ├── architecture.md            # 数据流向图 (API -> 抽取 -> DB -> 检索)
│   ├── data_model.md              # 9张核心表的数据字典说明
│   ├── decay_algorithm.md         # 指数衰减数学公式与噪音过滤推导
│   ├── DSH桌宠接入指南.md         # 详细的 DSH 插件配置排雷文档
│   └── adr/                       # 架构决策记录 (为什么不用 Docker 等)
│
├── schema.sql                     # 核心数据库图纸 (含双时间戳、FTS5、触发器)
│
├── src/recallweaver/              # 底层核心源码区 (L1 - L6 架构)
│   ├── __init__.py                # 暴露全局版本号
│   ├── api.py                     # 门面类：提供 remember, recall, explain 统一接口
│   ├── cli.py                     # 命令行工具：在终端直接操作记忆库
│   ├── config.py                  # Pydantic-Settings 环境配置加载
│   ├── errors.py                  # 自定义异常体系 (RW-XXX 错误码)
│   ├── db.py                      # SQLite 连接池、WAL 模式、死锁重试机制
│   ├── decay_engine.py            # 动态遗忘算法：指数衰减计算与权重封顶
│   ├── graph.py                   # 时空图谱引擎：递归 CTE 多跳查询与防环
│   ├── memory_manager.py          # 记忆大内总管：双时间戳并发冲突处理
│   ├── models.py                  # Pydantic 数据模型强校验
│   ├── retrieval.py               # 混合检索引擎：FTS5 + 图谱召回 + 重排
│   ├── server.py                  # FastAPI Web 服务层 (提供 HTTP 接口)
│   │
│   ├── extraction/                # 实体抽取插件区
│   │   ├── base.py                # 抽取器抽象基类
│   │   └── llm_extractor.py       # 接入 DeepSeek 的自然语言三元组抽取
│   │
│   ├── migrations/                # 数据库版本管理区
│   │   ├── 0001_init.sql          # 初始建表迁移脚本
│   │   └── runner.py              # 版本迁移执行器
│   │
│   ├── observability/             # 黑匣子监控区
│   │   ├── logging.py             # JSON 格式脱敏日志与全链路 Trace ID
│   │   └── metrics.py             # 线程安全的耗时与命中率监控
│   │
│   └── plugins/                   # 内部扩展插件区
│       ├── base.py                # 扩展接口定义
│       └── registry.py            # 插件注册中心
│
└── tests/                         # 质量保障防线
    ├── integration/               # 集成测试 (API, CLI, DSH, FastAPI)
    ├── unit/                      # 单元测试 (衰减算法、抽取器)
    └── performance/               # 性能压测 (长稳、死锁、假阴阳率)
```

### 🧠 核心调用路径 (数据流向)

```text
Python 调用方 / CLI / FastAPI
            │
            ▼
       api.py ─────────── 统一输入校验、组件装配、异常与指标
        ┌───┴─────────────┐
        ▼                 ▼
memory_manager.py     graph.py
        └──────┬──────────┘
               ▼
       db.py + schema.sql ─── SQLite
               ▲
               │
retrieval.py ◄─┴─► decay_engine.py

DSH (Node.js) ─► index.js ─► cli-bridge.py ─► recall CLI ─► api.py
```

---

## ⚙️ 配置参考

| 配置项 | 用途 | 默认值 |
| :--- | :--- | :--- |
| `DEEPSEEK_API_KEY` | LLM 抽取或对话凭证 | 无（本地纯记忆读写不需要） |
| `DB_PATH` | API 和 CLI 的 SQLite 路径 | `recallweaver.db` |
| `RECALLWEAVER_DB_PATH` | FastAPI 服务的数据库路径 | 无 |

---

## 🛡️ 免责与合规声明

RecallWeaver 按“现状”提供，仅供学习、研究及其他合法用途。它不是医疗、法律或财务专业服务。
默认情况下，记忆数据保存在本机 SQLite 中，但本地存储不等于绝对安全，请自行做好备份与磁盘加密。若启用第三方模型服务，数据可能受服务商条款影响。使用者需对输入数据的合法性及 AI 生成的结果承担核验责任。

## 📄 License

本项目基于 [MIT License](https://opensource.org/license/mit/) 开源。你可以随意修改、商用、分发，但请保留原作者版权声明。
```

