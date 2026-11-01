# RecallWeaver (织忆)

为 AI Agent 提供可本地运行、可追溯时间变化的长期记忆能力。RecallWeaver
以 SQLite 为存储基础，将文本记忆、关系事实、历史状态和动态相关性评分放在
同一套轻量系统中。

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue)](https://www.python.org/)
[![MIT License](https://img.shields.io/badge/License-MIT%20License-green)](https://opensource.org/license/mit/)
[![PyPI v1.2.2](https://img.shields.io/badge/PyPI-v1.2.2-blue)](https://pypi.org/project/recallweaver/1.2.2/)

> **运行时版本说明：**项目当前发布元数据将 Python 精确限定为 `3.11.9`。
> 徽章表示 Python 3.11 系列，不表示当前安装包已经兼容所有 3.11+ 版本。

## 目录

- [为什么需要 RecallWeaver](#为什么需要-recallweaver)
- [设计与能力](#设计与能力)
- [快速开始](#快速开始)
- [DSH 桌宠接入](#dsh-桌宠接入)
- [性能基准](#性能基准)
- [项目结构与模块职责](#项目结构与模块职责)
- [配置参考](#配置参考)
- [免责与合规声明](#免责与合规声明)
- [License](#license)

## 为什么需要 RecallWeaver

把历史对话简单切块后交给向量检索，并不等于拥有可靠的长期记忆。传统 RAG
常见的三个问题是：

1. **记忆没有状态。**相似度检索能找到“某句话”，却不天然知道它是当前事实、
   已过时信息，还是一次性的上下文。用户从“住在北京”搬到“上海”后，如果
   旧、新记录没有明确关系，检索结果可能同时返回两者。
2. **时间逻辑混乱。**事实何时在现实中生效，与系统何时收到、保存这条事实，
   是两个不同的问题。把两者压成一个时间戳，会让历史追溯和冲突判断变得含糊。
3. **基础设施过重。**为了保存少量个人或 Agent 记忆而额外部署向量数据库、
   容器和独立服务，会增加安装、运维、备份及故障排查成本。

RecallWeaver 不把记忆等同于无限增长的文本仓库。它提供结构化的事实记录、
时间维度、评分与检索机制，并以本地 SQLite 文件作为默认存储，尽量缩短从
安装到集成的路径。

## 设计与能力

| 能力 | RecallWeaver 的做法 | 带来的作用 |
|---|---|---|
| 双时间戳事实 | 分别表示事实的有效时间（valid time）和系统记录时间（transaction time） | 可以区分“事实何时成立”与“系统何时知道”，并支持历史回溯 |
| 动态遗忘评分 | 按时间衰减基础权重，并将受限的检索反馈纳入评分 | 较新的、有用的记忆更容易进入结果；评分不会因重复检索无限增长 |
| 混合检索 | SQLite FTS5 trigram 文本检索与关系图谱查询、结果评分相结合 | 同时处理自然语言文本和显式实体关系 |
| 纯本地存储 | 默认使用 SQLite；不要求部署向量数据库、Docker 或独立存储服务 | 数据库可备份、迁移和按常规文件权限管理 |
| 租户隔离 | 写入、图谱和检索 API 支持 `tenant_id` | 可将不同用户或 Agent 的记忆划分到不同命名空间 |
| 可集成接口 | 提供 Python API、命令行工具、FastAPI 服务及 DSH 桥接示例 | 可按应用规模选择嵌入式或 HTTP 接入方式 |

SQLite 是主要的本地存储，不代表所有依赖都只有 Python 标准库。发布包仍包含
Python 层依赖；这里的“轻量”是指无需额外运行数据库服务或容器。

## 快速开始

### 1. 准备 Python

项目定位为 Python 3.11+，但当前 PyPI 包的元数据要求 **Python 3.11.9**。
请先确认解释器版本：

```shell
python --version
```

使用 Windows 启动器时也可以明确选择解释器：

```powershell
py -3.11 --version
```

如版本不是 `3.11.9`，请先安装该版本，并在后续命令中使用同一个 Python
解释器安装依赖和运行程序。

### 2. 安装 RecallWeaver

```shell
python -m pip install recallweaver==1.2.2
```

确认命令行入口可用：

```shell
python -m recallweaver.cli --help
```

### 3. 配置 API Key 与数据库

如果要使用 RecallWeaver 的 DeepSeek 服务或 LLM 抽取功能，需要配置
`DEEPSEEK_API_KEY`。基础的本地 Python API 和 `add` / `recall` CLI 不会仅因
读写 SQLite 而调用 DeepSeek；API Key 是连接模型服务时使用的配置。

在终端临时设置：

```powershell
$env:DEEPSEEK_API_KEY = "替换为你自己的密钥"
$env:DB_PATH = "C:\data\recallweaver.db"
```

也可以在项目工作目录的 `.env` 文件中配置：

```dotenv
DEEPSEEK_API_KEY=替换为你自己的密钥
DB_PATH=C:/data/recallweaver.db
```

不要把真实密钥粘贴到公开 issue、聊天记录或提交到版本控制。服务端可通过
`RECALLWEAVER_DB_PATH` 单独指定数据库文件；嵌入式 API 和 CLI 的常规配置名为
`DB_PATH`。请确保数据库所在目录已存在且当前用户具有读写权限。

### 4. 写入并检索一条记忆

以下示例可直接保存为 `quickstart.py` 并运行。它显式指定数据库文件，因此
不依赖当前目录中是否已有数据库：

```python
from recallweaver import RecallWeaverAPI

api = RecallWeaverAPI("recallweaver.db")

# tenant_id 用于隔离不同用户或 Agent 的数据；同一用户后续检索时应复用它。
tenant_id = "user-001"

# 写入一条普通文本记忆。
memory_id = api.add_memory(
    "我对花生过敏，点餐时需要避开花生。",
    tenant_id=tenant_id,
)
print(f"已保存记忆：{memory_id}")

# 用自然语言查询同一个租户的记忆。
results = api.recall(
    "点餐时有什么需要注意的过敏信息？",
    limit=3,
    tenant_id=tenant_id,
)

if results:
    for result in results:
        print(f"- {result.content} (score={result.score:.3f})")
else:
    print("没有检索到相关记忆。")
```

运行：

```shell
python quickstart.py
```

`RecallWeaverAPI` 初始化时会准备数据库结构。文本写入和检索使用同一个
`tenant_id`，才能在对应命名空间中找到记录。需要保存明确关系时，可使用
`remember_triple(subject, predicate, object_)` 写入图谱事实。

#### 命令行示例

CLI 适合快速验证数据库和检索流程：

```shell
python -m recallweaver.cli add "张三 住在 北京"
python -m recallweaver.cli recall "张三 住在哪里"
python -m recallweaver.cli history "张三" "住在"
```

`add` 接收主语、谓词和宾语；`recall` 输出混合检索结果；`history` 用于查看
指定主语与谓词的关系历史。

## DSH 桌宠接入

仓库中的独立 Node.js 插件位于 [`dsh-plugin-recallweaver/`](dsh-plugin-recallweaver/)。
它通过 Cordis `systemPrompt` 插入点调用本机 Python 桥接脚本，再运行
RecallWeaver CLI 检索当前消息。插件版本为 `1.2.2`，要求 Node.js 18 或更高
版本，以及 DSH 可调用的 Python 3.11.9 环境。

**需要区分“检索”和“写入”：**当前 Node.js 插件入口调用 CLI 的 `recall`
命令，并不会自动把 DSH 中的每条新消息写入数据库。请先用 Python API 或
`add` 命令保存需要测试的记忆，再在 DSH 中提问。

### 安装与配置步骤

1. **安装 Python 包。**在运行 DSH 插件的 Python 环境中执行：

   ```shell
   python -m pip install recallweaver==1.2.2
   ```

2. **放置插件目录。**把仓库中的整个 `dsh-plugin-recallweaver` 文件夹复制到
   DSH 安装目录的 `plugins/` 下。最终目录应包含：

   ```text
   <DSH 安装目录>/
   └── plugins/
       └── dsh-plugin-recallweaver/
           ├── package.json
           ├── index.js
           ├── cli-bridge.py
           └── cordis.patch.yml
   ```

   `package.json` 声明插件入口 `./index.js`；`cordis.patch.yml` 是供 DSH
   加载的 Cordis patch 清单。若 DSH 使用自己的插件管理器或自定义目录，请按
   该实例的插件目录约定放置整个包，不要只复制 `index.js`。

3. **编辑当前启用的 DSH profile。**找到 DSH 正在使用的 profile 目录，并在
   该目录的 `cordis.patch.yml` 中加入插件条目。这个文件属于 DSH profile，
   不等于插件包内的同名示例文件。DSH 不同安装方式的 profile 路径可能不同；
   应编辑当前运行实例实际加载的那一份配置。

   ```yaml
   - insert:
       - id: recallweaver-memory
         name: recallweaver-memory
         inject: [systemPrompt]
         config:
           python: python
           timeoutMs: 10000
   ```

   如果配置中已经有顶层 `- insert:`，请把 `recallweaver-memory` 条目并入
   现有列表，不要创建重复的顶层结构。如果 DSH 找不到 Python，将
   `python: python` 改为该 Python 3.11.9 解释器的完整路径，例如：

   ```yaml
           python: 'C:\Python311\python.exe'
   ```

   可选的 `dbPath` 配置用于指定插件查询的 SQLite 文件；路径必须指向包含待
   检索记忆的数据库：

   ```yaml
           dbPath: 'C:\data\recallweaver.db'
   ```

   `timeoutMs` 是 Python CLI 调用的超时毫秒数，默认值为 `10000`。只有当
   DSH 加载的 Python 环境正确安装了 RecallWeaver 时，插件才能成功调用。

4. **配置模型服务并重启 DSH。**如果 DSH 使用 DeepSeek 模型，在 DSH 进程的
   环境或该 DSH 服务支持的密钥配置位置设置 `DEEPSEEK_API_KEY`。插件自身只
   执行本地检索，不会读取或转发模型密钥。保存 profile 配置后，完全退出并
   重新启动 DSH，确保新 patch 和环境变量已加载。

### 验证流程

先写入一条可检索的测试记忆：

```shell
python -m recallweaver.cli add "大肥鱼 叫 小明"
```

确认命令成功后，在桌宠中询问：

> 大肥鱼我叫什么名字？

也可以先在同一 Python 环境直接检查 CLI：

```shell
python -m recallweaver.cli recall "大肥鱼我叫什么名字"
```

终端检索能找到记忆、DSH 仍不能使用时，依次核对：

| 检查项 | 应确认的内容 |
|---|---|
| Profile | 修改的是当前 DSH 实际加载的 `cordis.patch.yml`，且重启过 DSH |
| 插件路径 | `plugins/dsh-plugin-recallweaver/` 中包含清单、JS 入口及 Python 桥接文件 |
| Python 环境 | `python` 或 YAML 中配置的解释器能导入 `recallweaver` |
| 数据库位置 | DSH 查询与写入测试记忆使用同一 SQLite 文件；必要时设置 `dbPath` |
| CLI 单独运行 | 使用 DSH 配置的同一个 Python 手动运行上面的 `recall` 命令 |
| 模型密钥 | 仅当模型服务未启动或无法回复时，再检查 DSH 的 API Key 配置 |

更多入门说明见插件包内的 [`dsh-plugin-recallweaver/README.md`](dsh-plugin-recallweaver/README.md)。

## 性能基准

以下为项目现有基准记录，不是对所有硬件、SQLite 构建、数据库规模或并发模式
的服务等级承诺：

| 测试项 | 项目记录 | 解释 |
|---|---:|---|
| 长稳压测 | 1,800 秒、50 并发、0 死锁 | 压测期间未记录死锁；不代表所有工作负载下都绝不会发生锁争用 |
| P99 延迟 | 10.5 ms | 特定基准环境中的第 99 百分位延迟，实际值取决于数据与机器 |
| 检索 Precision | 1.0 | 当前评估集中的精确率 |
| 检索 Recall | 1.0 | 当前评估集中的召回率 |

检索质量结果来自项目当前记录的 100 组评测数据。要用于生产决策，应在目标
机器、目标数据库规模和真实查询分布上重新测量。

## 项目结构与模块职责

```text
recallweaver/
├── dsh-plugin-recallweaver/       # 可独立放入 DSH plugins/ 的 Node.js 插件包
│   ├── index.js                   # Cordis 插件入口、读取消息并调用 Python CLI
│   ├── cli-bridge.py              # Unicode 安全的 Python CLI 桥接入口
│   ├── package.json               # npm 元数据、DSH entry 和 Python 依赖声明
│   ├── cordis.patch.yml           # DSH profile 可采用的 Cordis 插入配置示例
│   └── README.md                  # DSH 安装、配置和验证教程
├── docs/
│   ├── architecture.md            # 系统架构说明
│   ├── data_model.md               # 数据模型说明
│   ├── decay_algorithm.md          # 遗忘评分算法说明
│   ├── DSH 桌宠接入指南.md         # DSH 集成背景与配置说明
│   └── adr/                        # 架构决策记录
├── plugins/
│   └── dsh_adapter.py              # Python 侧 DSH 适配器示例
├── schema.sql                      # SQLite 表、索引与约束定义
├── src/
│   └── recallweaver/
│       ├── __init__.py             # 包公共导出及版本号
│       ├── api.py                  # 面向调用方的校验 API 与组件装配
│       ├── cli.py                  # add、recall、history 等 Click 命令
│       ├── config.py               # 应用设置与 `.env` 加载
│       ├── db.py                   # SQLite 连接、事务、初始化和锁重试
│       ├── decay_engine.py         # 动态遗忘及当前记忆分数计算
│       ├── errors.py               # 对外稳定的异常类型
│       ├── graph.py                # 租户隔离的实体、关系边与历史读写
│       ├── memory_manager.py       # 文本记忆持久化及基础访问
│       ├── models.py               # API 输入、输出和校验模型
│       ├── retrieval.py            # FTS5 trigram、图谱结果和评分检索
│       ├── server.py               # FastAPI HTTP 服务及 DeepSeek 对话接口
│       ├── extraction/
│       │   ├── base.py             # 知识抽取器抽象接口
│       │   └── llm_extractor.py    # OpenAI 兼容模型的关系三元组抽取
│       ├── migrations/
│       │   ├── 0001_init.sql       # 初始数据库迁移
│       │   └── runner.py           # 按版本执行数据库迁移
│       ├── observability/
│       │   ├── logging.py          # 结构化日志、脱敏与 trace 上下文
│       │   └── metrics.py          # 线程安全的请求计数和延迟指标
│       └── plugins/
│           ├── base.py             # 内部扩展接口
│           └── registry.py         # 内部扩展注册管理
└── tests/
    ├── integration/                # API、CLI、DSH 与服务集成测试
    ├── unit/                       # 算法及组件单元测试
    └── performance/                # 性能与压力测试
```

### 核心调用路径

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

DSH ─► index.js ─► cli-bridge.py ─► recall CLI ─► RecallWeaver API
```

## 配置参考

| 配置项 | 用途 | 说明 |
|---|---|---|
| `DEEPSEEK_API_KEY` | FastAPI 对话或 DeepSeek 抽取功能的服务凭证 | 通过环境变量或 `.env` 设置；普通本地记忆读写不需要发起模型请求 |
| `DB_PATH` | 嵌入式 API 和 CLI 默认数据库路径 | 未设置时使用 `recallweaver.db` |
| `RECALLWEAVER_DB_PATH` | FastAPI 服务使用的数据库路径 | 服务端配置显式读取此变量 |
| DSH `python` | 插件启动的 Python 解释器 | 应指向安装 RecallWeaver 的 Python 3.11.9 环境 |
| DSH `dbPath` | 插件查询的 SQLite 数据库文件 | 插件将该配置传给桥接进程的 `DB_PATH` |
| DSH `timeoutMs` | Python 子进程最大运行时间 | 默认 `10000` 毫秒 |

## 免责与合规声明

RecallWeaver 按“现状”提供，仅供学习、研究、软件开发和其他合法用途。它不是
医疗、法律、财务、心理或其他专业服务，也不构成任何形式的专业意见、诊断、
治疗、担保或结果承诺。

默认情况下，记忆数据保存在本机 SQLite 数据库中；但“本地存储”不等于自动
加密、自动备份或绝对安全。使用者应自行评估设备与账户访问控制、文件权限、
磁盘加密、备份与恢复策略、数据保留期限以及敏感信息处理方式。若启用
DeepSeek、其他模型提供商、HTTP 服务或第三方 DSH 环境，输入、输出、日志及
凭证可能受相应软件配置、网络传输方式和服务商条款影响。请在向任何外部服务
发送数据前，阅读其隐私政策和服务条款，并取得必要授权。

检索结果、自动抽取的关系、衰减评分及大语言模型生成的回答都可能遗漏、过时、
错误或带有不确定性。不得把召回内容当作唯一事实来源，也不得在未经独立核验
的情况下据此作出可能影响人身安全、医疗照护、财产、就业、教育、法律权利或
其他重大利益的决定。对于重要事实，应由有权限的人员核验并保留适当的人工
复核流程。

使用者须对输入和处理的数据拥有合法权利，遵守适用的数据保护、隐私、知识
产权及其他法律法规，不得输入未经授权的个人信息、机密信息或第三方敏感
数据。使用者对部署、访问控制、密钥管理、备份、数据删除、合规评估及其
使用本项目产生的后果承担责任。除适用法律明确要求外，项目贡献者不对因
使用、无法使用或依赖本项目而产生的数据丢失、服务中断、错误决策、损害或
第三方索赔承担保证或责任。

## License

本项目使用 [MIT License](https://opensource.org/license/mit/)。使用、修改或
分发时，请遵守 MIT License 的条款及适用法律。
