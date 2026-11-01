# RecallWeaver DSH Plugin

`recallweaver-memory` 是面向 DeepSeek Harness（DSH）的 Node.js 插件包。
插件从当前 DSH 会话读取最新用户消息，通过本机 Python 子进程调用
RecallWeaver CLI，并将检索输出加入 `systemPrompt`。数据检索由本机 SQLite
完成；模型请求和模型 API Key 由 DSH 自己的模型配置负责。

## 目录

- [兼容性与工作方式](#兼容性与工作方式)
- [安装前准备](#安装前准备)
- [安装插件包](#安装插件包)
- [注册到 DSH profile](#注册到-dsh-profile)
- [配置项](#配置项)
- [端到端验证](#端到端验证)
- [故障排查](#故障排查)
- [数据与安全边界](#数据与安全边界)
- [License](#license)

## 兼容性与工作方式

| 组件 | 要求 |
|---|---|
| 插件包 | `recallweaver-memory` `1.2.2` |
| Node.js | 18 或更高版本 |
| Python | RecallWeaver 当前发行版要求 Python `3.11.9` |
| Python 包 | `recallweaver==1.2.2`，安装在 DSH 可启动的解释器环境中 |
| DSH 接口 | Cordis 插件加载机制，使用 `systemPrompt` 注入点 |
| 存储 | RecallWeaver 使用的 SQLite 数据库文件 |

本包包含 `index.js`、`cli-bridge.py` 和 `cordis.patch.yml`。Node.js 插件通过
`child_process.spawnSync` 使用独立命令参数启动 Python，不经 shell 拼接用户
消息；Python 桥接脚本再调用 RecallWeaver CLI 的 `recall` 命令。

**当前行为仅负责检索，不负责自动写入。** DSH 用户的新消息不会因为插件
查询而自动变成已保存记忆。需要先用 CLI 或 Python API 将事实写入同一个数据
库，然后插件才能检索到它。

## 安装前准备

### 检查 Python 版本并安装 RecallWeaver

在与 DSH 相同的操作系统用户及 Python 环境中运行：

```shell
python --version
python -m pip install recallweaver==1.2.2
```

项目当前 PyPI 元数据要求 Python `3.11.9`。如果安装命令中的 `python` 不是
DSH 将使用的解释器，请在插件配置中填写正确的 Python 可执行文件路径。

确认包和 CLI 可用：

```shell
python -c "import recallweaver; print(recallweaver.__version__)"
python -m recallweaver.cli --help
```

### 配置模型服务的 API Key

插件只运行本地 Python 检索，不会自行调用 DeepSeek，也不需要 API Key 才能
查询 SQLite。若 DSH 连接 DeepSeek 模型，则仍需按 DSH 或模型服务商的说明为
DSH 配置 `DEEPSEEK_API_KEY`。

PowerShell 当前窗口的临时设置示例：

```powershell
$env:DEEPSEEK_API_KEY = "替换为你自己的密钥"
```

从该终端启动 DSH，或使用 DSH 支持的安全环境变量配置方式。不要将真实密钥
写进公开配置、提交到代码托管平台或发送给他人。

## 安装插件包

### 从当前源码仓库安装

将仓库内整个 `dsh-plugin-recallweaver` 文件夹复制到 DSH 安装目录下的
`plugins/`：

```text
<DSH 安装目录>/
└── plugins/
    └── dsh-plugin-recallweaver/
        ├── package.json
        ├── index.js
        ├── cli-bridge.py
        ├── cordis.patch.yml
        └── README.md
```

必须保留完整目录结构。不要只复制 `index.js`：入口还会加载同目录的
`cli-bridge.py`。

如果 DSH 提供插件管理器，也可以使用它安装此目录或已发布的
`recallweaver-memory` 包。插件清单中的 `dsh.entry` 是 `./index.js`，bundle
patch 来源是 `./cordis.patch.yml`。无论使用何种安装方式，都要完成下一节的
profile 注册。

## 注册到 DSH profile

### 找到正在使用的 profile

打开当前 DSH 实例实际加载的 profile 目录，找到其中的 `cordis.patch.yml`。
不同 DSH 安装方式和 profile 名称可能对应不同路径；应以该运行实例的配置
位置为准。这里编辑的是 **DSH profile 配置文件**，不是插件包内的
`dsh-plugin-recallweaver/cordis.patch.yml`。

### 添加 Cordis 插件条目

在 profile 的 `cordis.patch.yml` 中添加：

```yaml
- insert:
    - id: recallweaver-memory
      name: recallweaver-memory
      inject: [systemPrompt]
      config:
        python: python
        timeoutMs: 10000
```

如果 profile 文件已经存在 `- insert:` 顶层列表，请将 `recallweaver-memory`
条目合并到已有列表中，不要重复创建另一个顶层插入结构。

Windows 上，如果 DSH 进程解析不到 `python`，可填写 Python 3.11.9 的完整路径：

```yaml
        python: 'C:\Python311\python.exe'
```

保存后**完全退出并重新启动 DSH**，确保 profile patch、插件代码和环境变量
均被重新加载。单纯关闭聊天窗口通常不会重新初始化插件进程。

## 配置项

| 配置 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `python` | 字符串 | `RECALLWEAVER_PYTHON` 环境变量，或 `python` | 启动 Python 的可执行文件路径。建议在 DSH 使用多个 Python 环境时明确指定 |
| `timeoutMs` | 整数 | `10000` | CLI 子进程超时时间，单位为毫秒 |
| `dbPath` | 字符串 | RecallWeaver 默认路径 | 指定插件检索所使用的 SQLite 文件；该文件须包含要查询的记忆 |

`dbPath` 配置会传给子进程作为 `DB_PATH`。如果写入记忆时使用了非默认数据库，
检索插件也必须配置相同路径。SQLite 文件目录必须对运行 DSH 的账户可读写。

Node.js 子进程将 `PYTHONIOENCODING=utf-8` 传给 Python，以避免 Windows 上的
中文 CLI 输出因代码页不匹配而损坏。插件遇到 Python 启动失败、CLI 返回非零
退出码或输出为空时，会报告错误，不会把错误当成成功检索结果。

## 端到端验证

### 1. 写入一条明确的测试记忆

在终端中使用 DSH 插件配置的同一个 Python 和数据库位置：

```shell
python -m recallweaver.cli add "大肥鱼 叫 小明"
```

CLI 应显示写入成功。若写入时设置了 `DB_PATH`，之后查询时也要使用同一路径。
例如 PowerShell：

```powershell
$env:DB_PATH = "C:\data\recallweaver.db"
python -m recallweaver.cli add "大肥鱼 叫 小明"
```

### 2. 先直接测试 CLI

```shell
python -m recallweaver.cli recall "大肥鱼我叫什么名字"
```

结果中应能看到“小明”。如果这一步找不到，先检查数据库路径和写入内容；
尚未确认 CLI 检索成功前，不要从 DSH 插件层开始排查。

### 3. 在 DSH 桌宠中提问

重启 DSH 后，向桌宠发送：

> 大肥鱼我叫什么名字？

插件将该消息传给本地 RecallWeaver CLI，并把检索表格放入 system prompt。
桌宠是否按期望措辞回答，还取决于所用模型及其提示词处理；检索是否成功应以
CLI 输出和 DSH 日志中的插件执行结果共同判断。

## 故障排查

| 现象 | 检查步骤 |
|---|---|
| 插件未加载 | 确认目录为 `plugins/dsh-plugin-recallweaver/`，入口文件和桥接脚本都存在；确认编辑的是当前 profile 并完整重启 DSH |
| 找不到 Python | 在 DSH profile 的 `python` 配置中填写绝对路径；从同一解释器执行 `python -m recallweaver.cli --help` |
| `No module named recallweaver` | 用 DSH 配置的同一 Python 执行 `python -m pip install recallweaver==1.2.2` |
| 找不到测试记忆 | 确认写入和 DSH 检索使用同一个 SQLite 文件；核对 `dbPath` 或 `DB_PATH` |
| Python 版本不兼容 | 检查解释器版本；当前发行版要求 Python `3.11.9` |
| 中文乱码 | 确认使用本包的 `cli-bridge.py`；该桥接脚本随插件设置 UTF-8 CLI 输出 |
| DSH 无模型回复 | 先区分插件检索错误与模型连接错误；后者需按 DSH 配置检查模型服务、网络和 API Key |
| 测试消息没有变成记忆 | 这是当前插件行为：只调用 `recall`，需先显式用 CLI 或 Python API 写入记忆 |

## 数据与安全边界

RecallWeaver 默认将数据库保存在本地，但本地文件不自动加密，也不自动备份。
部署者负责数据库文件权限、备份、恢复、保留期限和敏感信息管理。DSH 仍会将
对话发送给其配置的模型服务；“插件本地检索”不代表 DSH 的模型交互也完全
离线。

API Key 应通过安全的环境变量或 DSH 密钥配置管理，不应写入公开 profile、
日志或插件源码。仅写入和处理依法有权使用的数据，并遵守适用隐私、数据保护
及服务条款。检索结果可能缺失、过时或不准确，不应未经核验就用于医疗、
法律、财务、安全或其他重大决策。

## License

本插件的 package metadata 声明使用 [MIT License](https://opensource.org/license/mit/)。
