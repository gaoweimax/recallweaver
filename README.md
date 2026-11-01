# RecallWeaver (织忆)

Local memory for evolving AI agents.

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue)](https://www.python.org/)
[![MIT License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![PyPI version](https://img.shields.io/pypi/v/recallweaver)](https://pypi.org/project/recallweaver/)

纯本地、零 Docker、无向量库，基于 SQLite 的 AI 动态记忆引擎。

## Core Features

- **双时间戳时空图谱**：记录事实演变，支持历史回溯。
- **动态遗忘打分池**：指数衰减评分，过滤低价值噪音。
- **混合检索**：FTS5 trigram 全文检索与图谱召回、重排。

## Benchmarks

| 指标 | 结果 |
|---|---:|
| 长稳测试 | 1,800 秒，50 并发，0 死锁 |
| P99 延迟 | 10.5 ms |
| 检索 Precision / Recall | 1.0 / 1.0（100 组评测数据） |

基准结果来自项目当前记录，实际表现取决于硬件、SQLite 版本和数据集。

## Quick Start

```shell
python -m pip install recallweaver
```

当前发行元数据要求 Python 3.11.9。

```python
from recallweaver import RecallWeaverAPI
api = RecallWeaverAPI("recallweaver.db")
api.add_memory("我对花生过敏", tenant_id="user-1")
memories = api.recall("过敏", limit=3, tenant_id="user-1")
print(memories[0].content if memories else "无相关记忆")
```

## DSH 桌宠接入

安装 DSH 插件依赖并注册 Cordis 插件：

```shell
python -m pip install recallweaver==1.2.1
```

在 DSH profile 的 `cordis.patch.yml` 中加入：

```yaml
- insert:
    - id: recallweaver-memory
      name: recallweaver-dsh
      inject: [systemPrompt]
      config:
        python: python
        timeoutMs: 10000
```

插件从当前会话读取最新用户消息，在本地写入并召回记忆，然后将结果加入
System Prompt。配置 `RECALLWEAVER_PYTHON` 可指定 Python 解释器；
`RECALLWEAVER_DB_PATH` 可指定 SQLite 文件路径。

完整安装步骤与配置说明见 [DSH 桌宠接入指南](docs/DSH%20%E6%A1%8C%E5%AE%A0%E6%8E%A5%E5%85%A5%E6%8C%87%E5%8D%97.md)。

## Disclaimer

本项目仅供学习、研究和合法用途，不构成法律、医疗或其他专业建议。用户应
自行评估并负责其输入数据、数据库备份与访问控制，以及基于 AI 输出采取的
任何行动。项目按现状提供，不保证数据永不丢失、输出准确或适用于特定用途。
使用者应遵守适用法律、服务条款及他人权利；请勿输入未获授权的敏感信息。

## Architecture

```text
src/recallweaver/
├── api.py
├── db.py
├── memory_manager.py
├── graph.py
├── retrieval.py
├── decay_engine.py
├── server.py
├── extraction/
├── migrations/
└── observability/
```

架构决策记录见 [`docs/adr/`](docs/adr/)。

## License

[MIT](LICENSE)
