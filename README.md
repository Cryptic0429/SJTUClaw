# SJTUClaw

SJTUClaw 是一个按课程规格逐步实现的本地 AI Agent。目前已完成 **Step 2**：从配置读取模型参数，通过 OpenAI 兼容 API 对话，并在命令行管理可持久化、彼此隔离的多个 Session。

当前版本刻意不包含跨 Session Memory、Compaction、工具或网页入口；这些属于后续 Step。

想按文件理解代码时，请阅读 [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)。该文档记录当前目录树、每个文件的职责、相互依赖和主要数据流，并会随每个 Step 同步更新。

## 环境要求与安装

- Python 3.11 或更高版本
- 一个支持 `POST /chat/completions` 的 OpenAI 兼容 LLM API

项目统一使用名为 `sjtuclaw` 的 Conda 环境：

```powershell
conda create -n sjtuclaw python=3.11
conda activate sjtuclaw
python -m pip install -e ".[dev]"
```

以后运行程序或测试前先执行 `conda activate sjtuclaw`。使用 `python -m pip` 可以确保依赖安装到当前环境。

## 配置

复制示例配置：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，填写：

```dotenv
LLM_API_KEY=你的 API Key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4.1-mini
```

也可以设置同名环境变量；环境变量优先于 `.env`。`LLM_BASE_URL` 应指向 API 根路径（通常以 `/v1` 结尾），程序会请求其 `/chat/completions`。`.env` 已被 Git 忽略，请勿提交真实密钥。

## 启动与演示

```powershell
python -m src.cli
```

启动后会恢复最近更新的 Session；首次启动则自动创建一个。每次请求只携带固定 system 指令和当前 Session 的完整 `user → assistant` 历史。输入 `/exit` 即可退出。

Session 命令均由 CLI 本地处理，不会发送给模型：

```text
/session new
/session list
/session switch <sessionId>
/session rename <sessionId> <title>
/session delete <sessionId>
```

示例：

```text
[/session list 后复制 ID]
你：/session new
你：/session rename <新ID> Python 学习
你：什么是装饰器？
AI：……
你：/session switch <旧ID>
你：我们刚才讨论了什么？
AI：只会根据旧 Session 的历史回答，不会看到“装饰器”对话。
你：/exit
再见！
```

Session 数据保存在 `data/sessions.json`，每项包含 `sessionId`、`title`、`messages`、`createdAt` 和 `updatedAt`。写入采用“同目录临时文件 → 刷盘 → 原子替换”，保存失败时不会提交半完成的内存状态。损坏 JSON、读取失败和保存失败都会明确报错；损坏文件不会被自动覆盖。

Context Builder 只向模型发送 system 指令和目标 Session 的消息，`sessionId`、标题、时间等持久化元数据不会进入模型上下文。某轮模型调用失败时不会插入空 assistant 消息。

未配置 Key 时会显示可操作的错误提示并以非零状态退出。超时、网络失败、非 2xx 响应、无效 JSON 和异常响应结构也会转化为简洁错误，不会输出 API Key。

运行数据与日志目录为 `data/` 和 `logs/`；其中 Session JSON 和日志默认不纳入版本控制。

## 测试

测试使用 Mock HTTP transport，不需要真实 API Key，也不会访问网络：

```powershell
python -m pytest
```

测试覆盖重启恢复、两个 Session 上下文隔离、五种 CLI 命令、损坏 JSON 保护、读取/保存失败、元数据过滤和模型调用失败等行为。真实 API 联调需配置 `.env` 后执行启动命令。


这是一个对git分支功能的使用调试

这是第二轮尝试
