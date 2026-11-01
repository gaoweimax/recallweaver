# RecallWeaver DSH 插件：三步接入

这个插件会把桌宠收到的最新一句话交给本机 RecallWeaver 查询，再把查询结果
放进 DSH 的提示词里。插件本身不联网；模型 API Key 仍由 DSH 用来连接你选的
模型服务。

## 第一步：准备环境

打开终端，安装记忆库：

```shell
python --version
pip install recallweaver==1.2.2
```

当前版本需要 Python 3.11.9。若 `python --version` 显示的不是 3.11.9，请先
安装对应版本，并用它运行 pip 命令。

然后照 DSH 或模型服务商的说明配置 API Key。例如使用 DeepSeek 时，在
PowerShell 当前窗口中运行：

```powershell
$env:DEEPSEEK_API_KEY = "替换成你自己的 API Key"
```

从这个终端窗口启动 DSH，确保 DSH 能读到 API Key。不要把真实 API Key 发给
别人或写进公开文件。若电脑上的 Python 命令不是安装
RecallWeaver 时使用的那个，可以把完整路径填到下面的 `python` 配置里。

## 第二步：安装插件

把本文件夹 `dsh-plugin-recallweaver` 整个复制到 DSH 的 `plugins/` 目录。
然后打开 DSH 配置文件 `cordis.patch.yml`，加入以下内容；如果已经有
`- insert:`，就把里面的插件条目合并进去，不要重复添加顶层 `- insert:`：

```yaml
- insert:
    - id: recallweaver-memory
      name: recallweaver-memory
      inject: [systemPrompt]
      config:
        python: python
        timeoutMs: 10000
```

Windows 上如果 DSH 找不到 Python，把 `python: python` 改成 Python 的完整路径，
例如 `python: "C:\\Python311\\python.exe"`。保存后重启 DSH。

## 第三步：验证记忆

先在终端存一条测试记忆（把“小明”换成你想测试的名字）：

```shell
python -m recallweaver.cli add 大肥鱼 叫 小明
```

打开 DSH 桌宠，问它：**“大肥鱼我叫什么名字？”** 如果回答“小明”，就说明
插件已经把问题交给 RecallWeaver 查询了。

如果没反应，先确认 DSH 和终端使用的是同一个 Python，并检查 DSH 是否能找到
RecallWeaver。也可以在终端直接运行：

```shell
python -m recallweaver.cli recall "大肥鱼我叫什么名字"
```
