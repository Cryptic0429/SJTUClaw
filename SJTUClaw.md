# SJTUClaw：分步实现规格

本文件是本仓库的实施说明。目标是从零实现一个本地 AI Agent：多轮对话、会话与记忆、工具调用、网页入口、定时任务、受控工作目录与 Skill 系统。

原始课程要求：<https://notes.sjtu.edu.cn/s/hl2bu_P7L>。

## 如何让 Codex 逐步实现

请按顺序输入：

```text
完成 Step 0
完成 Step 1
...
完成 Step 9
```

每次收到“完成 Step N”，Codex 必须：

1. 阅读本文件中该 Step 和所有前置 Step，检查现有代码、测试和未提交改动。
2. 只实现该 Step 的范围；不以方便为由提前加入后续 Step 的核心功能。
3. 先说明简短计划，再修改代码；为新增核心逻辑增加测试并运行验证。
4. 更新 README 中该 Step 的启动、配置、命令、接口和演示方法。
5. 最终说明完成项、修改文件、验证结果、限制，以及下一步可输入的提示词。
6. 为所有新增或修改的 Python 程序代码逐行添加易懂的中文注释；注释应解释该行的目的、数据流或关键语法，测试代码也要说明准备、执行与断言意图。空行、纯注释行以及仅用于排版的闭合行无需机械重复注释。后续每个 Step 都必须持续遵守此要求。
7. 为该 Step 新增或修改的关键代码补充清晰的解释性注释，说明主要数据流、职责边界、重要校验和异常处理逻辑，以提高代码可读性；注释必须与实际实现保持同步，不能用注释代替代码或测试。
8. 实时维护根目录的 `PROJECT_STRUCTURE.md`：每完成一个 Step 或增删、移动、重命名文件后，都必须同步更新当前目录树、各文件职责、文件间依赖关系、主要运行数据流和测试对应关系。文档内容必须描述当前真实实现，不能只追加历史记录或保留已经失效的关系。

若缺少 API Key，仍应完成不依赖真实模型的结构、单元测试和 Mock 测试；真实 API 联调时才要求用户配置 `.env`。

## 总体架构与不变原则

```text
CLI ───────────────┐
网页/图形入口 ──> Gateway ─┐
Scheduler ─────────────────> Agent Runtime / run_agent()
                                    │
                    Context Builder + LLM Client
                                    │
                Tool Registry / Approval / Skill Registry
                                    │
        Session Store / Memory Store / Task Store / 附件存储
```

建议以 Python 3.11+ 实现：FastAPI/Uvicorn 提供 Gateway，Pydantic 校验数据和参数，pytest 负责测试。JSON 文件可作为初始存储，但数据读写必须集中在 Store 层。

### 唯一 Runtime 入口

建议建立稳定的入口：

```python
run_agent(session_id: str, user_message: str, source: str) -> AgentResult
```

CLI、Gateway、Scheduler 都只能调用它。它负责：保存用户消息、构造上下文、调用模型、执行工具或等待审批、写入 tool result、继续循环和保存最终回答。

### 必须保持的职责边界

- LLM Client 只负责模型请求和响应解析。
- Context Builder 只负责组装模型上下文。
- Session/Memory/Task Store 只负责数据持久化。
- Tool Registry 保存工具定义与 handler，并校验参数。
- Gateway 只路由请求，绝不直接调用 LLM 或本地文件/Shell。
- Scheduler 只决定何时触发；到期后仍调用 `run_agent()`。
- 前端只展示和请求 API，绝不保存 API Key。

### 建议目录

```text
src/
  cli.py  config.py  llm_client.py
  runtime/agent_runner.py  runtime/context_builder.py
  runtime/compactor.py  runtime/approvals.py
  stores/session_store.py  stores/memory_store.py  stores/task_store.py
  tools/registry.py  tools/readonly.py  tools/workspace.py
  tools/shell.py  tools/download.py
  gateway/app.py  scheduler/service.py  skills/registry.py
prompts/system.md  prompts/soul.md  prompts/compact.md
skills/  data/  tests/
```

### 全程安全与质量规则

1. `.env`、运行数据、附件、下载缓存和日志中的敏感信息必须加入 `.gitignore`；提供 `.env.example`。
2. 所有外部输入、模型参数、文件路径和上传文件名都不可信，必须校验。
3. JSON 损坏、保存失败、工具失败必须清晰报错，不能静默丢数据或崩溃。
4. Session、任务、审批、附件和工具调用均使用稳定 ID。
5. 工具结果必须真实写入 Session；模型不得声称做过没有结果支持的操作。

---

## Step 0：环境准备与 LLM API 接入

**学习重点：** 最小 LLM 闭环：读取配置 → 校验 → 发送 `messages` → 解析 assistant 文本 → 处理错误。

### 环境约定

本项目统一使用 Conda 管理 Python 环境，环境名称为 `sjtuclaw`。首次配置时执行：

```powershell
conda create -n sjtuclaw python=3.11
conda activate sjtuclaw
python -m pip install -e ".[dev]"
```

后续运行程序和测试前，请先激活该环境：

```powershell
conda activate sjtuclaw
python -m src.cli
python -m pytest
```

使用 `python -m pip` 可确保依赖安装到当前激活的 `sjtuclaw` 环境，而不是其他 Python 环境。

**实现要求：**

1. 建立程序入口、配置、LLM Client、运行数据/日志目录的工程骨架。
2. 从 `.env` 或环境变量读取：

   ```text
   LLM_API_KEY=
   LLM_BASE_URL=
   LLM_MODEL=
   ```

3. 实现 `chat(messages) -> assistant_text`，至少理解 `system`、`user`、`assistant` 角色。
4. 处理缺失 Key、超时/网络失败、非 2xx HTTP、JSON/响应结构异常、无 assistant 内容等情况。
5. 提供固定启动命令，例如 `python -m src.cli`；启动后发送一条固定 user 消息并打印真实回复。

**不做：** 不做对话循环、Session、持久化、工具或网页。

**验收：** 未配置 Key 有清晰提示；配置正确能真实调用；README 写明安装、配置和启动。

---

## Step 1：实现多轮对话 Loop

**学习重点：** 模型不会自行记住历史；多轮对话依赖应用每次携带历史 `messages`。

**实现要求：**

1. CLI 持续接收输入；启动时创建一个仅在内存中的当前 Session。
2. 每轮普通输入：追加 user → 使用全部当前历史请求模型 → 追加 assistant → 打印回答。
3. CLI 直接处理 `/exit`，不能把该命令发给模型。
4. 将对话处理从 stdin/stdout 抽离成可测试函数或 Runtime 雏形。
5. LLM 调用失败时不能插入空 assistant message。

**不做：** 不做重启恢复、多 Session、memory、compaction、工具协议。

**验收：** 用户先说姓名再提问时模型能回答；每次请求含前序 user 和 assistant 消息；`/exit` 不进历史。

---

## Step 2：多 Session 管理与持久化

**学习重点：** Session 是独立上下文容器；保存结构和发送给模型的结构应分离。

**实现要求：**

1. 每个 Session 至少包含：

   ```text
   sessionId, title, messages, createdAt, updatedAt
   ```

2. 实现 JSON 等本地持久化，重启后恢复；损坏 JSON、读取失败、保存失败均明确报错，不能静默覆盖。
3. CLI 直接处理而不发送模型：

   ```text
   /session new
   /session list
   /session switch <sessionId>
   /session rename <sessionId> <title>
   /session delete <sessionId>
   ```

4. 引入 Context Builder：加入系统指令和当前 Session 的模型 messages；`title`、时间等元数据不直接发给模型。
5. 切换 Session 后，模型只能看到目标 Session 的历史。

**验收：** 两个主题 Session 互不混淆；重启后可列出并恢复；删除无效 ID 有可读错误。

---

## Step 3：System Prompt、Memory 与 Soul

**学习重点：** 稳定上下文（规则、风格、长期事实）与普通对话上下文分离。

**实现要求：**

1. system prompt 从独立文件加载，表达安全与行为边界；不能被普通消息覆盖。
2. soul 从独立文件加载，表达长期身份和语气；不保存某个 Session 的临时进度。
3. 实现持久化的跨 Session Memory Store，且仅由以下 CLI 命令修改：

   ```text
   /memory add <content>
   /memory list
   /memory delete <memoryId>
   ```

4. Context Builder 每次按顺序加入：

   ```text
   system prompt + soul + memory + 当前 session messages
   ```

**验收：** 在 Session A 写入 memory，Session B 可见；重启后修改 prompt/soul 文件生效；普通对话不能修改 memory 或稳定配置。

---

## Step 4：上下文压缩 Compaction

**学习重点：** 用 Session Summary 管理长上下文；只压缩旧会话消息，不能压缩稳定上下文。

**实现要求：**

1. Session 增加并持久化 `summary`。
2. 使用独立 compact prompt，将“已有 summary + 待压缩旧 messages”生成新的 summary。
3. 设计可解释阈值（字符数、消息数或 token 近似）；在 README/注释说明。
4. 触发后只压缩旧消息，原样保留最近几轮；新摘要应保留任务、已完成事项、用户约束、未解决问题和关键事实。
5. Context Builder 改为：

   ```text
   system prompt + soul + memory + session summary + recent messages
   ```

6. compaction 失败、summary 为空无效或保存失败时，**绝不能删除旧 messages**。
7. 可选 `/compact` 强制压缩；自动/手动成功后都显示摘要预览与消息变化。

**不做：** system prompt、soul、memory、工具定义都不参与压缩；summary 不跨 Session。

**验收：** 长对话能自动压缩且仍记得当前任务；Mock 摘要失败后历史完整保留。

---

## Step 5：只读 Tool、外部反馈闭环与 Agent Loop

**学习重点：** `reason → act → observe → reason`。模型提出工具请求，Runtime 执行并把真实结果反馈给模型。

**实现要求：**

1. 定义统一 Tool：`name`、`description`、输入 schema、`handler`、`safety_level`。
2. Tool Registry 支持注册、列出模型可见定义、按名执行、参数校验、统一成功/失败结果。
3. 至少实现三个只读工具：

   ```text
   current_time
   list_dir
   read_file
   ```

4. 文件不存在、路径错误、文件过大必须返回结构化错误或截断说明；所有本 Step 工具安全等级为 `read_only`。
5. 优先使用模型 API 原生 tool/function calling；否则实现严格 JSON 协议，例如：

   ```json
   {"type":"tool_calls","calls":[{"tool":"read_file","args":{"path":"README.md"}}]}
   ```

   或：

   ```json
   {"type":"final","content":"..."}
   ```

6. Agent Loop：模型返回 final 则结束；请求工具则执行本批最多 5 个调用，写入 tool result 后再次调用模型。不要用固定总迭代数中止整个 turn，但每个工具应有超时与错误处理。
7. 成功与失败的 tool result、trace 都写入当前 Session，后续可被 compaction。
8. 模型输出 JSON 前后混入说明时可提取合法 JSON；不得靠模糊字符串匹配猜工具意图。

**严格禁止：** 写/删/改文件、Shell、安装包、Git 提交、发邮件等改变环境的工具。

**验收：** “现在几点”“列出当前目录”“读取 README 并讲解仓库”都通过真实工具完成；错误工具或错误参数不会导致程序崩溃。

---

## Step 6：Gateway 与图形化操作入口

**学习重点：** 把 CLI Runtime 安全暴露为真实外部服务；Gateway 是路由层，不是第二个 Agent。

**实现要求：**

1. 实现可长期运行的 Gateway Server，可用 HTTP、WebSocket 或 SSE；单个请求失败不得退出进程。
2. 至少提供：发送消息、获得 assistant 回复/错误、列出 Session、创建 Session、查询 Session 历史、上传附件、列出当前 Session 附件。
3. Gateway 根据请求中的 `sessionId` 路由 Session；对缺失或不存在 ID 的策略（创建或报错）必须清楚、一致。
4. Gateway 只能调用已有 `run_agent()`；不能直接调用 LLM Client，也不能绕过 Context Builder、Session Store、Memory、Compaction、Tool Registry。
5. 实现至少一个图形入口（推荐网页），它必须能：

   - 输入和发送消息；
   - 展示当前 Session 历史、assistant 回复和 Gateway 错误；
   - 列出、创建、切换 Session；
   - 切换后仅展示目标 Session 的消息。

6. API Key 只在服务端；前端的所有消息都经过 Gateway。
7. 支持附件上传并按 Session 严格隔离。推荐存储：

   ```text
   data/sessions/<sessionId>/attachments/<attachmentId>
   ```

   保存并展示文件名、大小、类型、上传时间等 metadata。Session A 不能列出或读取 Session B 的附件 metadata。
8. 若 Agent 要知道附件存在，只将当前 Session 的附件 metadata 放入上下文；附件不是 workspace，也不代表 Agent 可修改用户项目。

**不做：** 不要求复杂流式 UI、日历或第三方机器人；Gateway/前端不得写用户项目、执行 Shell 或直接读取服务器文件。

**验收：** CLI 和网页看到同一批 Session；网页消息复用原有 tool/compaction；两个 Session 的附件清单完全隔离；浏览器中无 API Key。

---

## Step 7：Scheduler 与定时任务

**学习重点：** 定时任务是未来自动送入某个 Session 的 user message；Scheduler 决定何时触发，Runtime 决定如何推理。

**实现要求：**

1. 实现可长期运行的 Scheduler，可与 Gateway 同进程或独立进程；说明它的启动、数据访问和 Runtime 调用方式。
2. 任务至少包含：

   ```text
   taskId, content, taskType, schedule/repeatRule, nextRunAt,
   status, sessionId, createdAt, updatedAt, executionHistory
   ```

3. 支持一次性任务与真正重复的周期任务。周期规则可限制为固定间隔或每天固定时间，不强制完整 cron；但需清楚定义语义和下一次执行时间计算。
4. 创建时校验时间、规则、Session；无效输入不得创建。
5. 支持任务列表、执行历史、取消。列表显示内容、类型、规则、下次时间、状态、Session、创建/更新时间；周期任务保留每次历史而非仅最后一次。
6. 任务和历史持久化；服务重启后未完成任务、状态、规则、下次时间不丢失。
7. 到期流程：标记运行中 → 调用 `run_agent(sessionId, task_content, source="scheduler")` → 保存 assistant 回复或错误 → 更新状态 → 周期任务计算下次时间。
8. 明确并测试：任务失败后是否继续、执行时长超过周期如何处理、取消是否取消未来触发、离线时错过的任务是否补跑。
9. 在 Step 6 网页中增加：创建一次性/周期任务、列表、状态、结果、重复规则、下次时间、所属 Session、取消未来触发。所有操作经服务端接口；前端/Gateway 不自行调度。

**并发要求：** 同一 Session 同时收到网页和 Scheduler 消息时，以 Session 级锁或队列串行，避免两次写入覆盖消息或 summary。

**验收：** 一次性任务实际执行并写回指定 Session；周期任务至少留下两条历史；重启后待执行任务仍在；取消后不再触发。

---

## Step 8：Workspace、Advanced Tool 与 Approval

**学习重点：** Agent 可在明确边界内真实操作环境，但每次可能改变环境的操作必须先获用户批准。

### 8.1 Workspace

1. 支持设置和查看当前 workspace；可绑定 Session 或 Runtime 配置，但用户必须明确 Agent 正在操作哪个目录。
2. 未设置 workspace 时，写文件、Shell、附件拷贝、下载入口创建都必须失败并提示先设置。
3. 相对路径按 workspace 解析；规范化并解析符号链接后仍必须确认目标位于 workspace 内。
4. 拒绝绝对路径、`../` 逃逸、符号链接逃逸。
5. 实现 `copy_attachment_to_workspace`：只能复制当前 Session 已绑定附件到 workspace 内目标路径；不能访问其他 Session 附件或写到 workspace 外。

### 8.2 Update Tool

实现多个工具或统一 `update_file`，但必须覆盖：

```text
create_file       创建文件
overwrite_file    覆盖已有文件
edit_file         局部编辑已有文件
```

每个 result 至少包含成功状态、工具名、影响路径、简短结果或错误。所有目标路径必须通过 Workspace 校验。

### 8.3 Shell Tool

1. `new_shell`：启动新的 Shell；有旧 Shell 先退出；初始 cwd 为 workspace 或其子目录。
2. `run_command`：仅在当前已创建 Shell 中执行；多次调用复用进程，使 cwd、环境变量、source 结果可延续。
3. 当前没有 Shell 时明确要求先调用 `new_shell`。
4. 每次执行前后确认 cwd 仍在 workspace；离开时终止 Shell 并报错。
5. 返回命令、cwd、退出码、stdout、stderr、是否超时、是否截断和错误信息；限制超时与最大输出。

### 8.4 Download Tool

实现 `create_download(path)`：只为 workspace 内已存在文件向 Gateway 注册短期下载入口（`downloadId` 或临时 URL）。不把文件内容放进模型上下文；它不需要显式 approval，最终下载由用户点击确认；Gateway 负责过期与不存在处理。

### 8.5 Approval

1. 所有 update tool 与 Shell tool 必须先创建 Approval，不能立刻执行。
2. Approval 至少保存：`approvalId`、tool 名、可安全展示的完整参数、Session、创建时间、状态。
3. Runtime 遇到此类 tool call 时创建待审批请求、暂停工具执行，并让 CLI/Gateway 展示。
4. 用户批准后 Runtime 执行原 tool，将真实 result 写回 Session 并继续 Agent Loop。
5. 用户拒绝后绝不执行；拒绝原因可写入 Session，供模型调整方案。
6. Gateway/前端只展示和收集决定，不能自行改文件或运行命令。

### 8.6 Runtime 接入

所有 Advanced Tool 注册进已有 Tool Registry；只读工具、memory、compaction、Context Builder 保持可用：

```text
用户请求 → 模型请求工具
→ update/shell：创建 approval → 用户批准/拒绝 → 执行或记录拒绝
→ download：创建临时下载入口
→ tool/approval result 写入 Session → 模型基于真实结果继续回答
```

**验收：** 未批准的文件/Shell 请求没有副作用；批准后能在 workspace 内执行，拒绝后保留原因；绝对路径、`../`、符号链接逃逸均失败；Shell 状态可复用且离开 workspace 会停止；网页可展示审批/下载入口但没有直接文件权限。

---

## Step 9：Skill System

**学习重点：** Skill 是可复用任务手册，不是 system prompt、memory 或另一套 Agent；未选中 Skill 的全文不能进入每轮上下文。

### 9.1 Skill 格式

一个 Skill 至少含 `SKILL.md`，可带模板和参考资料：

```text
skills/<skill-name>/
  SKILL.md
  assets/
  references/
```

`SKILL.md` 使用 frontmatter：

```markdown
---
name: course-report
description: 生成结构化课程报告草稿；适用于课程小论文、学习总结和实验报告。
---

# Course Report
具体流程、模板、检查清单与引用要求。
```

### 9.2 Skill Registry

实现扫描本地 `skills/`、识别 name/description/资源、列出、按名查找并完整加载、生成轻量索引的 Registry。轻量索引只提供名称、描述、适用场景；Registry 不执行任务。

### 9.3 两种调用方式

显式调用的 CLI：

```text
/skill list
/skill show <skill-name>
/skill <skill-name> <task>
/skill usage
```

显式调用直接加载完整 Skill，记录来源 `explicit`。

普通消息时，Context Builder 只放轻量索引；模型通过明确内部结构/tool 提出“使用某 Skill”。Runtime 必须先展示 Skill 使用审批，含 Skill 名和选择原因；用户同意后才加载全文，记录来源 `auto`。用户拒绝时不加载完整 Skill。

### 9.4 Runtime 接入与记录

加载后上下文含：名称、描述、适用场景、完整指令、必要模板/检查清单、用户任务和来源。它仍复用 Session、Memory、Tool Registry、Workspace、Approval 与 Compaction。

每次使用记录：Skill 名、Session、任务、来源、自动选择原因、时间、最终输出/保存路径。Skill 需要写文件时，必须走 Step 8 的 update tool 与 approval。

### 9.5 必须提供的 Skills

至少三个且包含：

1. `course-report`：根据课程要求、主题、字数、材料、保存路径生成结构化 Markdown 课程报告草稿。
2. `material-summary`：汇总 workspace 中学习材料、课堂笔记或调研资料。
3. `presentation-outline`：生成课堂展示/PPT 页面结构和讲稿提纲。

每个 description 必须清晰可区分，便于自动选择。

### 9.6 图形入口

网页支持列出 Skill、查看描述/适用场景、选择 Skill 输入任务、普通聊天的自动选择说明、使用原因/记录展示，以及保存产物时的 approval。

**验收：** `/skill list` 和 `/skill show` 正确；显式 `course-report` 能生成草稿并经审批保存；自动选择会先请求用户同意；未选 Skill 的全文不进入每次模型请求。

---

## 最终端到端验收

完成 Step 9 后，依次演示：

1. CLI 创建两组 Session，重启恢复且不混淆。
2. 添加 Memory，切换 Session 后仍可使用。
3. 触发 Compaction，验证摘要保留任务且稳定上下文未被压缩。
4. Agent 用真实只读工具列目录、读 README、讲解项目。
5. 网页管理同一批 Session；不同 Session 上传附件并验证隔离。
6. 网页创建一次性和周期任务，验证写回对应 Session，重启后任务仍在。
7. 设置 workspace；先拒绝一次写文件审批，确认无副作用；再批准并确认文件写入。
8. 创建下载入口并从网页获取 workspace 输出文件。
9. 显式使用 `course-report`，再演示普通请求的自动 Skill 选择与审批。

## 提交建议

每完成一个 Step，单独提交：

```text
feat(step-0): add configurable LLM bootstrap
feat(step-1): add multi-turn CLI loop
...
feat(step-9): add skill registry and course-report skill
```

提交前运行当前 Step 相关测试和手工演示。绝不提交 `.env`、真实附件、下载文件、运行 JSON、API 日志或凭据。
