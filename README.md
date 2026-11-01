# RecallWeaver

**面向 Python 开发者的本地 AI 动态记忆引擎。**

RecallWeaver 帮助 AI 应用把重要信息保存在本机，并在需要时重新找回来。记忆存放在 SQLite 文件中，不需要另行部署数据库服务或向量数据库。

## 🎬 核心演示

> 看！接入此库的大模型，如何瞬间找回被清空的记忆。

![RecallWeaver Demo](./assets/demo.gif)

## 快速开始

### 环境与安装

当前发行版 `recallweaver==1.2.2` 要求 **Python 3.11.9**：

```shell
python --version
python -m pip install recallweaver==1.2.2
```

### Python API：保存并检索记忆

```python
from recallweaver import RecallWeaverAPI

memory = RecallWeaverAPI("recallweaver.db")

# 保存一条结构化事实
memory.remember_triple(
    "鱼片",
    "住在",
    "杭州",
    tenant_id="my-agent",
)

# 之后可在新会话中按问题检索
results = memory.recall(
    "鱼片住在哪里？",
    limit=3,
    tenant_id="my-agent",
)
for result in results:
    print(result.content or f"{result.subject} {result.predicate} {result.object}")
```

写入和检索使用相同的 `tenant_id`，可将不同用户或 Agent 的记忆隔离开。也可以用 `memory.add_memory("鱼片对花生过敏", tenant_id="my-agent")` 保存普通文本。

### 运行上下文重置演示

下面的演示默认使用本地模拟模型，不需要 API Key，也不会发起网络请求。它会先清空对话历史，再对比没有记忆和通过 RecallWeaver 找回记忆时的回答：

```shell
python examples/context_reset_demo.py
```

如需使用真实 DeepSeek 响应，可设置 `DEEPSEEK_API_KEY` 后运行：

```shell
python examples/context_reset_demo.py --live
```

另一个多轮角色记忆演示位于 `examples/deepseek_agent.py`。运行该示例需要设置 `DEEPSEEK_API_KEY`；它使用 RecallWeaver 持久化记忆，并在清空聊天历史后重建模型提示词。

## 它如何工作

1. 应用通过 Python API 把事实或文本写入本地 SQLite 记忆库。
2. 需要回答问题时，应用用当前输入查询相关记忆。
3. 应用将召回内容加入模型提示词；模型据此回答。

RecallWeaver 负责记忆的保存和检索；AI 对话流程和提示词由你的 Python 应用决定。基础记忆读写不要求调用模型 API。

## 🌐 生态与衍生

官方 DSH 桌宠插件已独立开源，请前往新仓库安装：[https://github.com/gaoweimax/dsh-plugin-recallweaver](https://github.com/gaoweimax/dsh-plugin-recallweaver)

## 仓库结构

```text
recallweaver/
├── examples/
│   ├── context_reset_demo.py   # 清空聊天历史后恢复记忆
│   ├── deepseek_agent.py       # 通过 Python API 构建多轮记忆对话
│   └── minimal_demo.py         # 最小 API 演示
├── plugins/
│   └── memory_adapter.py       # 框架无关的 Python 提示词适配示例
├── src/
│   └── recallweaver/           # Python 记忆引擎
├── tests/                      # 自动化测试
└── pyproject.toml              # 包与构建配置
```

## 数据与许可

记忆默认保存在本地 SQLite 文件中。数据库文件不会自动加密或备份，请自行妥善保管并定期备份。
