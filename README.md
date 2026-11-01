# 🧠 RecallWeaver (织忆)

**赋予 LLM Agent 永不磨灭的长期记忆**

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue)](https://www.python.org/)
[![PyPI v1.2.2](https://img.shields.io/badge/PyPI-v1.2.2-blue)](https://pypi.org/project/recallweaver/1.2.2/)
[![MIT License](https://img.shields.io/badge/License-MIT-green)](https://opensource.org/license/mit/)
[![Tests Passed](https://img.shields.io/badge/Tests-Passed-brightgreen)](tests/)

RecallWeaver 是一个基于 SQLite 的本地长期记忆引擎。它把文本记忆、关系事实、时间状态和动态相关性评分放进同一套轻量系统，让 Agent 能检索过去、区分事实变化，并逐步降低低价值记忆的权重。

**不需要 Docker，不需要单独部署向量数据库，也不需要 GPU。**

> **Python 版本说明：**项目面向 Python 3.11 系列；当前 `1.2.2` 发行包的元数据将 Python 精确限定为 `3.11.9`。请以实际发行包要求为准。

## 目录

- [为什么需要 RecallWeaver](#为什么需要-recallweaver)
- [设计与核心能力](#设计与核心能力)
- [性能基准](#性能基准)
- [快速开始](#快速开始)
- [DSH 桌宠接入终极指南](#dsh-桌宠接入终极指南)
- [项目结构与核心职责](#项目结构与核心职责)
- [配置参考](#配置参考)
- [免责与合规声明](#免责与合规声明)
- [License](#license)

## 为什么需要 RecallWeaver

传统 RAG 能够从历史材料中找出相似文本，但“找得到相似内容”并不等于“拥有可靠的长期记忆”。在构建本地 Agent 或桌宠时，常见问题包括：

1. **金鱼记忆：**会话一结束，用户偏好、长期设定和重要背景就被丢在上下文之外。下一次对话，Agent 又像第一次见面。
2. **时间精分：**用户之前住在北京，后来搬到上海。若系统只按相似度取回文本而不管理事实的时间状态，旧地址和新地址可能同时进入提示词，模型便可能回答“你同时住在北京和上海”。
3. **算力黑洞：**为了记住少量事实而搭建额外向量数据库、容器和服务，会增加依赖、运维与备份成本；不断把完整对话塞进上下文，又会增加 Token 消耗并挤占推理空间。

RecallWeaver 的解法不是无限堆叠对话，而是显式管理记忆：

- **双时间戳：**区分事实在现实中的有效时间（valid time）与系统记录该事实的时间（transaction time），为事实变更和历史追溯提供基础。
- **动态遗忘：**结合时间衰减与有上限的检索反馈计算当前权重，让近期且有用的信息更容易进入召回结果，降低低价值内容的影响。
- **本地 SQLite：**使用单文件数据库持久化，不要求部署额外数据库服务或向量引擎。
- **混合检索：**使用 SQLite FTS5 trigram 文本检索，并结合关系图谱和评分对候选结果排序。

SQLite 作为存储引擎，不代表 Python 包没有依赖；它代表无需另外运行数据库服务器或容器。模型 API 只在调用相应模型功能时使用，不是本地记忆读写的前置条件。

## 设计与核心能力

| 能力 | 实现方式 | 使用价值 |
|---|---|---|
| 时间化事实 | 分别记录事实有效时间与系统事务时间 | 区分“何时发生”与“系统何时获知”，便于理解事实演变 |
| 动态遗忘 | 指数时间衰减，并对检索带来的权重提升设置上限 | 减少无关旧内容长期占据召回结果的机会 |
| 混合检索 | SQLite FTS5 trigram 文本搜索、关系图谱检索与评分重排 | 同时查找自然语言记忆和显式实体关系 |
| 本地持久化 | SQLite 文件 | 便于自行备份、迁移和管理文件访问权限 |
| 多租户隔离 | 读写 API 接受 `tenant_id` | 在同一数据库中区分不同用户或 Agent 的记忆 |
| 多种接入方式 | Python API、CLI、FastAPI 服务、DSH Node.js 插件 | 从单进程脚本到桌宠集成均可使用相应接口 |

## 性能基准

以下为项目提供的基准记录。实测结果会受硬件、SQLite 版本、数据库大小、并发模式、数据集和测试方法影响，不构成对任意部署环境的性能保证。

| 测试项 | 项目记录 | 说明 |
|---|---:|---|
| 长稳压测 | 1,800 秒、50 并发、0 死锁 | 压测期间未记录死锁；不代表所有工作负载下都不会发生锁争用 |
| P99 延迟 | 3.459 ms | 项目基准记录值；实际延迟须在目标机器和目标数据规模下复测 |
| 检索 Precision | 1.0 | 当前评估数据集上的精确率记录 |
| 检索 Recall | 1.0 | 当前评估数据集上的召回率记录 |

项目的压力与检索评估脚本位于 `benchmarks/`。复现实验时，请同时记录硬件、Python 和 SQLite 版本、数据库规模、并发数、查询集以及统计方法；只有条件一致的测量结果才适合横向比较。

## 快速开始

### 环境要求

安装前确认使用 Python `3.11.9`：

```shell
python --version
```

### 安装

```shell
python -m pip install recallweaver==1.2.2
```

可以检查 CLI 是否可用：

```shell
python -m recallweaver.cli --help
```

### 配置 API Key

需要使用 DeepSeek 服务或 LLM 抽取功能时，配置 `DEEPSEEK_API_KEY`。PowerShell 当前终端窗口的设置方式：

```powershell
$env:DEEPSEEK_API_KEY = "替换为你自己的 API Key"
```

也可以在项目工作目录的 `.env` 文件中设置：

```dotenv
DEEPSEEK_API_KEY=替换为你自己的 API Key
```

基础的本地 `RecallWeaverAPI` 写入和检索，以及 CLI 的 `add`、`recall` 命令，不会仅因操作 SQLite 而调用 DeepSeek。不要把真实 API Key 写入公开仓库、日志或共享配置。

### Python 核心 API

下面的示例创建数据库、写入一条事实并检索：

```python
from recallweaver import RecallWeaverAPI
api = RecallWeaverAPI("recallweaver.db")
api.remember_triple("用户", "住在", "上海", tenant_id="user-001")
results = api.recall("用户现在住在哪里？", limit=3, tenant_id="user-001")
print([item.content for item in results])
```

同一用户的写入和检索必须使用同一个 `tenant_id`。也可以通过 `api.add_memory(content, tenant_id=...)` 保存普通文本记忆。

### CLI 示例

```shell
python -m recallweaver.cli add "张三 住在 北京"
python -m recallweaver.cli recall "张三 住在哪里"
python -m recallweaver.cli history "张三" "住在"
```

`add` 写入图谱三元组，`recall` 检索文本和图谱记忆，`history` 查看指定主语与谓词的事实历史。

## DSH 桌宠接入终极指南

### 为什么接入

DSH 会话上下文并不等于持久化的长期记忆。桌宠新开会话、重启客户端或上下文被截断后，仍可能忘记用户之前告诉它的信息。RecallWeaver 插件会把最新用户消息交给本机 RecallWeaver CLI 检索，再把检索结果注入 DSH 的 `systemPrompt`，供模型在回答时参考。

> **当前插件只负责检索，不会自动保存每条 DSH 消息。**测试前请先用 Python API 或 CLI 写入一条记忆。模型最终如何组织答案，仍取决于 DSH 使用的模型及提示词。

### 第一步：准备 Python 环境并放置插件包

在 DSH 将要使用的 Python 环境中安装 RecallWeaver：

```shell
python --version
python -m pip install recallweaver==1.2.2
```

当前发行包要求 Python `3.11.9`。确认 DSH 使用的解释器与安装包的解释器相同；如有多个 Python，请记下正确解释器的完整路径。

把仓库中的 `dsh-plugin-recallweaver/` 整个文件夹复制到 DSH 安装目录的 `plugins/` 目录下。不要只复制 `index.js`，Python 桥接脚本也必须保留：

```text
DSH 安装目录/
└── plugins/
    └── dsh-plugin-recallweaver/
        ├── package.json
        ├── index.js
        ├── cli-bridge.py
        ├── cordis.patch.yml
        └── README.md
```

如果 DSH 使用插件管理器或自定义插件路径，则按该运行实例实际使用的插件目录放置完整文件夹。

### 第二步：修改当前 DSH profile 的 `cordis.patch.yml`

找到当前 DSH 实例正在加载的 profile 目录，并编辑其中的 `cordis.patch.yml`。不同安装方式或 profile 名称可能对应不同路径，应以当前 DSH 实例的配置位置为准。这里修改的是 **profile 内的配置文件**，不是插件文件夹里自带的 `cordis.patch.yml` 示例。

将以下条目加入 profile 的 `cordis.patch.yml`：

```yaml
- insert:
    - id: recallweaver-memory
      name: recallweaver-memory
      inject: [systemPrompt]
      config:
        python: python
        timeoutMs: 10000
```

如果文件里已经有顶层 `- insert:`，请把 `recallweaver-memory` 条目合并到已有列表中，不要重复创建顶层列表。

如果 DSH 找不到 Python，将 `python: python` 改为已安装 RecallWeaver 的 Python 可执行文件完整路径。例如：

```yaml
        python: 'C:\Python311\python.exe'
```

可选地通过 `dbPath` 指定数据库。写入测试记忆和插件检索必须使用同一个 SQLite 文件：

```yaml
        dbPath: 'C:\data\recallweaver.db'
```

`timeoutMs` 的单位为毫秒，默认示例为 `10000`。插件通过 Node.js 子进程启动 Python，使用独立参数传递消息；Python 桥接脚本负责调用 CLI。

### 第三步：保存配置并彻底重启 DSH

保存 profile 配置后，完全退出 DSH 客户端并重新启动，使新的 profile、插件代码和环境变量生效。若客户端有系统托盘进程，也要按 DSH 的正常退出方式关闭后台进程后再启动。

如果 DSH 使用 DeepSeek 模型，请按 DSH 或模型服务商的说明为 DSH 进程配置 `DEEPSEEK_API_KEY`。插件本身只查询本机记忆，不会读取或转发模型 API Key。

### 第四步：写入测试记忆并验证

先用 DSH 插件配置所指向的 Python 和数据库，写入一条测试事实：

```shell
python -m recallweaver.cli add "大肥鱼 叫 小明"
```

如果要使用自定义数据库，在同一个 PowerShell 窗口中设置路径后写入：

```powershell
$env:DB_PATH = "C:\data\recallweaver.db"
python -m recallweaver.cli add "大肥鱼 叫 小明"
```

先直接验证 CLI 能检索到记忆：

```shell
python -m recallweaver.cli recall "大肥鱼我叫什么名字"
```

确认结果包含“小明”后，打开 DSH 桌宠并询问：

> 大肥鱼，我叫什么名字？

如果 CLI 检索有结果而桌宠没有参考该事实，请检查 profile 是否加载、插件是否成功注入、数据库路径是否一致，以及 DSH 日志中的插件错误。桌宠具体答复措辞由模型决定。

### DSH 配置与故障排查

| 现象 | 排查方式 |
|---|---|
| 插件没有加载 | 核对插件完整目录、当前启用的 profile 和 `cordis.patch.yml` 条目；保存后彻底重启 DSH |
| `python` 无法启动 | 将 `python` 配置为解释器绝对路径，并用该解释器运行 `python -m recallweaver.cli --help` |
| 找不到 `recallweaver` | 在 DSH 配置所指向的 Python 环境执行 `python -m pip install recallweaver==1.2.2` |
| 桌宠找不到测试事实 | 确认写入与检索使用同一个数据库；使用 `dbPath` 显式指定路径 |
| 修改配置后仍无变化 | 确认编辑的是当前 profile，而非插件包内的示例；完整退出并重启 DSH |
| 桌宠没有自动记住新消息 | 这是当前插件行为；使用 CLI 或 API 显式写入记忆 |
| DSH 模型无法回复 | 区分模型服务错误与插件检索错误；按 DSH 配置检查模型服务、网络和 API Key |

## 项目结构与核心职责

下面展示插件、核心 Python 包、数据库迁移、测试和基准工具的主要源码布局。`__pycache__`、本机数据库文件、备份和生成产物不属于源码树。

```text
recallweaver/
├── dsh-plugin-recallweaver/
│   ├── package.json                 # npm 元数据、Node 入口和 DSH 插件声明
│   ├── index.js                     # Cordis 插件入口；读取消息并启动 Python 子进程
│   ├── cli-bridge.py                # 设置 CLI 输出编码并调用 RecallWeaver 命令
│   ├── cordis.patch.yml             # 可供 DSH profile 合并使用的配置示例
│   └── README.md                    # 插件安装、配置、验证和排错文档
├── src/
│   └── recallweaver/
│       ├── __init__.py              # 包版本与公共 API 导出
│       ├── api.py                   # API 门面：校验输入并组合存储、图谱、检索等组件
│       ├── cli.py                   # Click 命令：add、recall、history 等终端操作
│       ├── config.py                # 应用配置、环境变量和 `.env` 加载
│       ├── db.py                    # SQLite 连接、事务、初始化与锁冲突重试
│       ├── decay_engine.py          # 时间衰减和检索反馈权重计算
│       ├── errors.py                # 对外错误类型及异常边界
│       ├── graph.py                 # 实体、关系边、租户隔离与关系历史
│       ├── memory_manager.py        # 文本记忆写入、持久化与读取
│       ├── models.py                # API 输入输出模型与数据校验
│       ├── retrieval.py             # FTS5 文本检索、图谱召回、候选过滤与排序
│       ├── server.py                # FastAPI HTTP 服务及模型对话接口
│       ├── extraction/
│       │   ├── __init__.py          # 抽取模块导出
│       │   ├── base.py              # 事实抽取器抽象接口
│       │   └── llm_extractor.py     # OpenAI 兼容 API 的关系三元组抽取实现
│       ├── migrations/
│       │   ├── __init__.py          # 数据库迁移包
│       │   ├── 0001_init.sql        # 初始数据库结构迁移
│       │   └── runner.py            # 已应用版本检查与迁移执行
│       ├── observability/
│       │   ├── README.md            # 可观测性组件说明
│       │   ├── __init__.py          # 日志和指标模块导出
│       │   ├── logging.py           # 结构化日志、脱敏、Trace ID 与文件处理
│       │   └── metrics.py           # 并发安全的请求计数和延迟统计
│       └── plugins/
│           ├── README.md            # 内部插件扩展说明
│           ├── __init__.py          # 插件模块导出
│           ├── base.py              # 内部扩展接口
│           └── registry.py          # 扩展注册与查找
├── plugins/
│   └── dsh_adapter.py               # Python 侧 DSH 适配器示例
├── schema.sql                       # SQLite 表、索引、触发器和约束定义
├── pyproject.toml                   # Python 包元数据、依赖和构建配置
├── docs/
│   ├── architecture.md              # 系统架构说明
│   ├── data_model.md                # 数据模型说明
│   ├── decay_algorithm.md           # 遗忘评分算法说明
│   ├── DSH 桌宠接入指南.md          # DSH 集成背景与配置说明
│   └── adr/                         # 架构决策记录
├── benchmarks/
│   ├── ablation.py                  # 消融实验
│   ├── bench_quality.py             # 检索质量评估
│   ├── bench_real_world.py          # 真实场景评估
│   ├── bench_retrieval.py           # 检索基准
│   ├── data_quality.py              # 评估数据质量分析
│   ├── dataset_loaders.py            # 基准数据集加载
│   ├── eval_metrics.py               # Precision、Recall 等评估指标
│   ├── gen_complex_data.py           # 复杂测试数据生成
│   ├── gen_data.py                   # 基准数据生成
│   ├── gen_eval_dataset.py           # 评估数据集生成
│   ├── soak_test.py                  # 长时间稳定性与并发压测
│   ├── stress_deadlock.py            # 锁竞争和死锁压力测试
│   └── datasets/                     # 基准评估数据和数据质量报告
└── tests/
    ├── conftest.py                   # pytest 路径和共享数据库 fixture
    ├── integration/
    │   ├── test_api_cli.py           # 公共 API 与 CLI 合约
    │   ├── test_db.py                 # SQLite 行为与事务
    │   ├── test_dsh_adapter.py        # Python DSH 适配器
    │   ├── test_dsh_plugin.py         # Node.js 到 Python CLI 桥接
    │   ├── test_graph.py              # 图谱写入与关系查询
    │   ├── test_memory.py             # 记忆写入和读取
    │   ├── test_memory_conflict.py    # 事实变更和冲突处理
    │   ├── test_noise_filtering.py    # 噪音过滤
    │   ├── test_retrieval.py          # 检索结果与排序
    │   ├── test_server.py             # FastAPI 服务接口
    │   ├── test_chaos_boundaries.py   # 异常边界和输入边界
    │   └── test_ultimate_suite.py     # 端到端综合集成
    ├── unit/
    │   ├── test_decay.py              # 动态遗忘评分算法
    │   ├── test_llm_extractor.py      # LLM 抽取器解析与校验
    │   ├── test_logging.py            # 日志与脱敏
    │   ├── test_metrics.py            # 指标统计
    │   └── test_observability.py      # 可观测性组件
    └── performance/                   # 性能测试
```

### 核心文件职责

| 文件或模块 | 具体职责 |
|---|---|
| `src/recallweaver/api.py` | 对外的主要 Python 接口，集中执行输入校验并组合数据库、文本记忆、图谱和检索组件 |
| `src/recallweaver/db.py` | 管理 SQLite 连接与事务，初始化 schema，并对可重试的锁冲突执行事务重试 |
| `schema.sql` | 定义持久化数据结构、索引、约束及全文检索所需对象 |
| `src/recallweaver/memory_manager.py` | 负责文本记忆的写入、存储和基础读取 |
| `src/recallweaver/graph.py` | 维护租户范围内的实体与关系边，并支持关系事实的时间状态 |
| `src/recallweaver/retrieval.py` | 生成安全的 FTS5 查询、召回文本与图谱候选并排序 |
| `src/recallweaver/decay_engine.py` | 计算时间衰减分数，并限制检索反馈带来的权重上限 |
| `src/recallweaver/models.py` | 定义公开输入输出模型及字段约束 |
| `src/recallweaver/config.py` | 提供默认配置，并从进程环境和 `.env` 读取设置 |
| `src/recallweaver/cli.py` | 将核心能力暴露为终端命令，便于脚本、运维和手工验证 |
| `src/recallweaver/server.py` | 提供 FastAPI 接口和对话服务的 HTTP 层 |
| `src/recallweaver/extraction/llm_extractor.py` | 通过 OpenAI 兼容接口从文本抽取结构化关系 |
| `src/recallweaver/migrations/runner.py` | 跟踪并执行数据库 schema 版本迁移 |
| `src/recallweaver/observability/logging.py` | 生成带 trace 信息的日志，并对敏感值进行脱敏 |
| `src/recallweaver/observability/metrics.py` | 汇总请求数量与延迟等运行指标 |
| `dsh-plugin-recallweaver/index.js` | 注册 Cordis prompt section，读取会话消息并安全地调用 Python 桥接入口 |
| `dsh-plugin-recallweaver/cli-bridge.py` | 为 Python CLI 设置适合子进程的 UTF-8 输出并转发命令 |
| `dsh-plugin-recallweaver/package.json` | 声明 Node 包名、版本、入口、运行环境和 DSH 元数据 |
| `dsh-plugin-recallweaver/cordis.patch.yml` | 提供 DSH profile 插件注册配置示例 |
| `plugins/dsh_adapter.py` | Python 适配器示例：写入本轮消息并按租户检索上下文 |
| `benchmarks/` | 提供长稳、并发、检索质量和数据集评估工具 |
| `tests/` | 覆盖 API、CLI、数据库、图谱、DSH 桥接、检索和算法行为 |

### 核心调用路径

```text
Python API / CLI / FastAPI
            |
            v
          api.py
       /          \
      v            v
memory_manager.py  graph.py
       \            /
        v          v
         db.py + schema.sql
                 |
                 v
              SQLite
                 ^
                 |
retrieval.py <-> decay_engine.py

DSH -> index.js -> cli-bridge.py -> RecallWeaver CLI -> Python API
```

## 配置参考

| 配置项 | 用途 | 说明 |
|---|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek 模型功能凭证 | 仅在调用相应模型服务时需要；请通过安全的环境配置提供 |
| `DB_PATH` | 嵌入式 API 和 CLI 的默认数据库路径 | 默认文件名为 `recallweaver.db` |
| `RECALLWEAVER_DB_PATH` | FastAPI 服务配置的数据库路径 | 服务端设置读取此环境变量 |
| DSH `python` | 插件调用的 Python 可执行文件 | 必须是安装 `recallweaver==1.2.2` 的环境 |
| DSH `dbPath` | 插件查询的 SQLite 文件路径 | 写入和检索应指向同一数据库 |
| DSH `timeoutMs` | Python CLI 调用超时 | 单位为毫秒 |

## 免责与合规声明

RecallWeaver 按“现状”提供，仅供学习、研究、软件开发及其他合法用途。项目不构成医疗、法律、财务、心理或其他专业建议，也不对特定用途、结果准确性、持续可用性或数据永不丢失作出保证。

默认的 SQLite 数据库存储在本地，但本地存储不等于自动加密、自动备份或绝对安全。使用者应自行评估文件权限、账户访问控制、磁盘保护、备份与恢复、数据保留期限及删除策略。启用 DSH、FastAPI、DeepSeek 或其他外部模型服务时，数据处理还会受到相应软件配置、网络传输方式和服务商隐私政策及服务条款的影响。

检索、抽取、评分和模型生成结果可能遗漏、过时、错误或不确定。不得将其作为唯一事实来源；在医疗、安全、法律、财务或其他可能影响重大权益的场景中，必须由具备相应权限和专业能力的人员独立核验。使用者应确保对输入数据具有合法处理权限，并遵守适用的数据保护、隐私、知识产权及其他法律法规。

使用者对 API Key 管理、数据库安全、备份、部署方式、合规审查、人工复核，以及基于本项目采取的行动和由此产生的后果承担责任。除适用法律另有强制规定外，项目贡献者不对因使用、无法使用或依赖本项目所造成的数据丢失、业务中断、决策损失或第三方索赔承担保证或责任。

## License

RecallWeaver 使用 [MIT License](https://opensource.org/license/mit/)。使用、修改或分发本项目时，请遵守 MIT License 条款及适用法律。
