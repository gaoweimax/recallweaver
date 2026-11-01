# DSH 桌宠接入指南

本插件通过 DSH 的 Cordis bundle patch 注册一个 system-prompt 分段。每次
DSH 为某个会话组装 System Prompt 时，插件读取最新的用户消息，在本机调用
RecallWeaver Python 适配器完成“写入后检索”，并把召回事实放进提示词。
对话内容只写入本机配置的 SQLite 数据库；插件不会自行请求 OpenAI 或
DeepSeek 网络接口。

## 环境要求

- DeepSeek Harness（DSH）及 Node.js 18 或更高版本。
- RecallWeaver 所要求的 Python 3.11.9。
- `recallweaver==1.2.1` 已安装在 DSH 插件进程可调用的 Python 环境中。

DSH 使用 npm 管理 Cordis 插件，而 RecallWeaver 发布在 PyPI，因此 npm 不会
自动安装 Python 包。请先在运行 DSH 插件的 Python 环境中执行：

```shell
python -m pip install recallweaver==1.2.1
```

若 `python` 指向了其他 Python 环境，可指定可执行文件：

```shell
python -m pip install recallweaver==1.2.1
```

随后将 `RECALLWEAVER_PYTHON` 环境变量设为该解释器路径。例如 Windows：

```powershell
$env:RECALLWEAVER_PYTHON = "C:\Python311\python.exe"
```

插件配置中的 `python` 字段优先级高于 `RECALLWEAVER_PYTHON`。未设置时使用
系统的 `python` 命令。

## 安装 DSH 插件

1. 在 DSH 的插件管理器中从本地目录安装 `dsh_plugin/`，或在
   `recallweaver-dsh` 发布到 npm 后，按插件清单的 tarball 来源安装。
   清单使用与 `dsh-purge` 相同的 `dsh.bundle.patch` / `dsh.install` 元数据
   模式。
2. 确认安装完成后，按下一节把插件插入当前 DSH profile 的
   `cordis.patch.yml`。

## 修改 `cordis.patch.yml`

打开当前 DSH profile 的 `cordis.patch.yml`，在顶层增加以下内容。若文件已有
其他 `- insert:` 项，可将此插件条目合并到已有的 `insert` 列表，避免重复
创建顶层列表：

```yaml
- insert:
    - id: recallweaver-memory
      name: recallweaver-dsh
      inject: [systemPrompt]
      config:
        python: python
        timeoutMs: 10000
```

`name` 必须与插件 package 名称相同。Windows 上也可以把 `python` 替换为
Python 可执行文件完整路径。可选地通过 `dbPath` 指定 SQLite 数据库位置：

```yaml
        dbPath: "D:/dsh-data/recallweaver.db"
```

没有设置 `dbPath` 时，RecallWeaver 使用环境变量
`RECALLWEAVER_DB_PATH`；若该变量也不存在，则使用 RecallWeaver 默认数据库
路径。数据库目录必须对运行 DSH 的账户可写。

保存后重启或重新加载 DSH profile。首次调用时，插件会将最新用户消息写入
该用户对应的 RecallWeaver 租户，并把相关记忆作为系统提示词内容提供给模型。
默认租户标识取 DSH agent ID；单用户桌宠如需固定隔离标识，可在 `config`
下增加 `userId: "my-dsh-user"`。

## 环境变量

| 变量 | 用途 |
|---|---|
| `RECALLWEAVER_PYTHON` | 指定已安装 RecallWeaver 的 Python 解释器；默认 `python`。 |
| `RECALLWEAVER_DB_PATH` | 指定 SQLite 数据库文件；`dbPath` 配置可覆盖它。 |

如果插件启动失败，请先确认 DSH 进程能运行所配置的 Python、Python 环境已
安装 `recallweaver==1.2.1`，并且数据库目录可写。桥接错误会返回 Python 标准
错误输出，便于排查。
