# RecallWeaver：让大肥鱼别再一换会话就失忆

你的大肥鱼是不是一开新会话，就忘了你住哪、喜欢什么？

`dsh-plugin-recallweaver` 是给 DSH 桌宠用的记忆外挂。它会在大肥鱼回答前，从你电脑里的记忆库找出相关信息，放进这次对话的提示词里。这样即使新开会话，大肥鱼也有机会接上之前的话题。

## 🎬 极客演示 (Demo)

> **看！接入了 RecallWeaver 的大肥鱼，即使被强行清空了上下文，依然能瞬间找回关于“鱼片”和“花生过敏”的记忆，并维持傲娇人设！**

![RecallWeaver Demo](./assets/demo.gif)

> **先说清楚：**插件目前负责“找回记忆”，不会自动把每条新聊天存起来。要让它记住一件新事，需要先把这件事写进记忆库。下面会带你一步步完成安装和测试。

## 接入前后，有什么不一样？

假设记忆库里已经存好了“鱼片昨天搬到杭州”和“鱼片对花生过敏”：

- ❌ **未接入插件**：你问“我住哪？”大肥鱼可能回答：“我不知道，我们才刚认识。”
- ✅ **接入插件后**：你问“我住哪？”大肥鱼就能参考找回来的记忆回答：“鱼片，你昨天不是搬到杭州了吗？还说你花生过敏呢！”

这只是效果示意。实际回答由 DSH 使用的大模型决定；插件负责把找到的记忆提供给它，不保证模型一定逐字照搬。

## DSH 桌宠安装指南

### 开始前：准备 Python 和 RecallWeaver

先确认电脑安装了 Python。**当前 `recallweaver==1.2.2` 实际要求 Python 3.11.9**，并不是所有 3.11 及以上版本都能安装。

```shell
python --version
python -m pip install recallweaver==1.2.2
```

如果电脑装了多个 Python，请确认 DSH 插件之后会使用的那个 Python 也装好了 RecallWeaver。稍后可以在配置里填写该 Python 的完整路径。

### 第一步：安装 DSH 插件

Windows 用户可以直接右键运行 `scripts/install_dsh_plugin.ps1` 实现一键安装。

脚本会优先查找 DSH 默认安装位置中的 `dsh.cmd`，找不到时会请你输入 DSH 安装目录或 `dsh.cmd` 的完整路径，然后使用插件文件夹的绝对路径执行安装。安装完成后，请彻底退出 DSH 托盘程序，再重新打开以生效。

如果你使用非 Windows 系统，请通过 DSH 支持的插件管理方式安装仓库中的 `dsh-plugin-recallweaver` 文件夹。

### 第二步：在 DSH 配置里开启插件

找到当前 DSH 正在使用的 profile 配置文件 `cordis.patch.yml`。把下面配置加进去：

```yaml
- insert:
    - id: recallweaver-memory
      name: recallweaver-memory
      inject: [systemPrompt]
      config:
        python: python
        timeoutMs: 10000
```

如果文件里已经有 `- insert:`，把 `recallweaver-memory` 这一项放进现有列表，不要再重复新建一组顶层 `- insert:`。

如果 DSH 找不到 Python，把 `python: python` 换成 Python 可执行文件的完整路径。例如：

```yaml
        python: 'C:\Python311\python.exe'
```

如果你要指定记忆库位置，可以在 `config:` 下面增加 `dbPath`。写入记忆和插件检索必须使用同一个数据库文件：

```yaml
        dbPath: 'C:\data\recallweaver.db'
```

> **注意找对文件：**这里修改的是 DSH 当前 profile 里的 `cordis.patch.yml`，不是插件文件夹自带的同名示例文件。DSH 如果找不到插件或没有变化，优先确认 profile 和插件目录是否是当前实例实际使用的路径。

### 第三步：彻底退出并重新打开 DSH

保存配置后，彻底退出 DSH 再重新打开，让它重新加载插件。若 DSH 还在系统托盘或后台运行，也要按正常退出方式关闭后台进程。只关掉聊天窗口或新开一个会话，通常不会重新加载插件配置。

### 第四步：写一条记忆，再开新会话测试

插件现在只会查找已有记忆，不会自动保存你在聊天里说的话。先在终端运行下面的命令，手动写入一条测试记忆：

```shell
python -m recallweaver.cli add "鱼片 住在 杭州"
```

如果你刚才在配置中指定了 `dbPath`，写入时也要指向同一个数据库。例如在 PowerShell 里：

```powershell
$env:DB_PATH = "C:\data\recallweaver.db"
python -m recallweaver.cli add "鱼片 住在 杭州"
```

先确认记忆库能找到这条信息：

```shell
python -m recallweaver.cli recall "鱼片住在哪里"
```

确认结果里出现“杭州”后，打开 DSH：

1. 在一个会话里和大肥鱼聊几句。
2. 新开一个会话。
3. 问：“鱼片住哪？”

大肥鱼此时可以参考插件找回的记忆回答。也可以把测试内容换成你自己的信息；**不要把密码、证件号码等敏感信息写入记忆库。**

### 常见问题和避坑

| 现象 | 先检查这里 |
|---|---|
| 安装时报 Python 版本不兼容 | 当前 `recallweaver==1.2.2` 要求 Python `3.11.9`。 |
| DSH 说找不到 Python 或 RecallWeaver | 配置 `python` 为安装过 RecallWeaver 的 Python 完整路径，并用同一个 Python 执行安装命令。 |
| 插件没有加载 | 检查插件文件夹是否放在 DSH 实际使用的插件目录，并确认修改的是当前 profile 的 `cordis.patch.yml`。 |
| 大肥鱼还是不知道答案 | 先运行 `python -m recallweaver.cli recall "你的问题"`。若命令都找不到，检查记忆内容和数据库路径；若命令能找到，查看 DSH 插件日志。 |
| 聊天里说了“记住我住杭州”，新会话却忘了 | 当前插件不会自动保存聊天。先通过 CLI 或 Python API 把信息写进记忆库。 |
| 改完配置没变化 | 完全退出 DSH（包括托盘或后台进程）后再打开。 |

## 不用 DSH，也能在 Python 项目里使用

安装同一个 Python 包后，可以在自己的程序里直接存取记忆：

```shell
python -m pip install recallweaver==1.2.2
```

```python
from recallweaver import RecallWeaverAPI

memory = RecallWeaverAPI("recallweaver.db")
memory.remember_triple("鱼片", "住在", "杭州", tenant_id="my-agent")

results = memory.recall(
    "鱼片住在哪里？",
    limit=3,
    tenant_id="my-agent",
)
for result in results:
    print(result.content)
```

保存和查询时使用同一个 `tenant_id`，这样不同用户或 Agent 的记忆可以分开管理。

## 它是怎么把记忆找回来的？

说白了，流程就三步：

1. DSH 插件拿到你最新发给桌宠的消息。
2. 插件请本机的 RecallWeaver 去 SQLite 记忆库里查找相关信息。
3. 插件把找到的内容放进大模型这次回答要看的 System Prompt。

记忆库存放在本机 SQLite 文件里。这个插件负责查询和提供记忆，不会自动保存每条新消息，也不会自行调用 DeepSeek 或 OpenAI 的网络接口。模型服务仍由 DSH 自己配置。

## 项目与更多说明

- DSH 插件目录：[dsh-plugin-recallweaver/](dsh-plugin-recallweaver/)
- DSH 桌宠接入补充说明：[docs/DSH 桌宠接入指南.md](docs/DSH%20%E6%A1%8C%E5%AE%A0%E6%8E%A5%E5%85%A5%E6%8C%87%E5%8D%97.md)
- 技术设计说明：[docs/architecture.md](docs/architecture.md)

RecallWeaver 使用 SQLite 本地保存记忆，不需要单独部署数据库服务器或向量数据库。数据库文件不会自动加密或备份，请自行妥善保管并定期备份。
