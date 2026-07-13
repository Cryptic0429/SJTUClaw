"""提供 Step 2 的持久化多 Session 命令行入口。"""  # 概括本模块职责。

from __future__ import annotations  # 推迟类型注解求值，提升现代类型写法兼容性。

import logging  # 导入日志模块，用于记录启动和每轮错误。
import sys  # 导入系统模块，用于向标准错误流输出提示。
from collections.abc import Callable  # 导入可调用接口，用于注入可测试的输入输出函数。
from pathlib import Path  # 导入跨平台路径类型，用于日志和 Session 文件路径。
from typing import Protocol  # 导入协议类型，让 CLI 不依赖具体 Runtime 类。

from .config import ConfigurationError, ensure_runtime_directories, load_settings  # 导入启动配置与目录准备函数。
from .llm_client import LLMClient, LLMError  # 导入真实模型客户端和模型错误基类。
from .runtime.session_runtime import SessionRuntime  # 导入持久化 Session 对话 Runtime。
from .stores.session_store import SessionStore, SessionStoreError  # 导入 Session 持久化接口和统一错误。


SESSION_USAGE = (  # 集中定义 Session 命令帮助，错误格式时统一展示。
    "用法：/session new | /session list | /session switch <sessionId> | "  # 列出创建、列表和切换语法。
    "/session rename <sessionId> <title> | /session delete <sessionId>"  # 列出重命名和删除语法。
)  # 结束帮助文本。


class ChatRuntime(Protocol):  # 声明 CLI 发送普通消息所需的最小 Runtime 接口。
    def send(self, session_id: str, user_message: str) -> str: ...  # 要求指定 Session 并返回 assistant 文本。


def _configure_logging(log_file: Path = Path("logs/sjtuclaw.log")) -> None:  # 配置默认文件日志。
    logging.basicConfig(  # 初始化 Python 根日志器。
        filename=log_file,  # 把日志写入运行日志目录。
        level=logging.INFO,  # 记录 INFO 及以上级别事件。
        format="%(asctime)s %(levelname)s %(name)s %(message)s",  # 统一日志时间、级别、来源和正文格式。
        encoding="utf-8",  # 使用 UTF-8 保存中英文日志。
    )  # 结束日志配置调用。


def _format_session_list(store: SessionStore, current_session_id: str) -> list[str]:  # 生成可读 Session 列表。
    sessions = store.list()  # 从 Store 取得按最近更新时间排序的安全快照。
    lines = ["Session 列表："]  # 创建列表标题行。
    for session in sessions:  # 逐个格式化 Session 元数据。
        marker = "*" if session.session_id == current_session_id else " "  # 用星号标出当前 Session。
        lines.append(  # 添加包含稳定 ID、标题和更新时间的一行。
            f"{marker} {session.session_id} | {session.title} | updatedAt={session.updated_at}"  # 不把消息正文打印在列表中。
        )  # 结束单行追加。
    return lines  # 将多行交给 CLI 的 output_fn 逐行展示。


def handle_session_command(  # 解析并执行一条永远不会发送给模型的 Session 命令。
    command: str,  # 接收已经从终端读到的原始命令文本。
    store: SessionStore,  # 接收唯一允许修改 Session 文件的 Store。
    current_session_id: str,  # 接收命令执行前的当前 Session ID。
) -> tuple[str, list[str]]:  # 返回命令执行后的当前 ID 和待展示文本行。
    parts = command.strip().split(maxsplit=3)  # 最多拆成四段，使 rename 标题可包含空格。
    if len(parts) < 2 or parts[0] != "/session":  # 缺少子命令或命令前缀异常时拒绝执行。
        raise ValueError(SESSION_USAGE)  # 返回统一帮助而不是猜测用户意图。
    action = parts[1]  # 读取 new、list、switch、rename 或 delete 子命令。

    if action == "new" and len(parts) == 2:  # `/session new` 不接受额外参数。
        session = store.create()  # 创建并立即持久化一个空 Session。
        return session.session_id, [f"已创建并切换到 Session：{session.session_id}（{session.title}）"]  # 新 Session 自动成为当前项。

    if action == "list" and len(parts) == 2:  # `/session list` 不接受额外参数。
        return current_session_id, _format_session_list(store, current_session_id)  # 只读展示，不改变当前项。

    if action == "switch" and len(parts) == 3:  # 切换命令必须且只能包含一个 ID。
        session = store.get(parts[2])  # 查询目标；无效 ID 由 Store 清晰报错。
        return session.session_id, [f"已切换到 Session：{session.session_id}（{session.title}）"]  # 返回新的当前 ID。

    if action == "rename" and len(parts) == 4:  # 重命名必须包含 ID 和非空标题部分。
        session = store.rename(parts[2], parts[3])  # 由 Store 校验标题并原子保存。
        return current_session_id, [f"已重命名 Session：{session.session_id}（{session.title}）"]  # 重命名不自动切换。

    if action == "delete" and len(parts) == 3:  # 删除命令必须且只能包含一个 ID。
        deleted_id = parts[2]  # 保存待删除 ID，供输出和当前项判断。
        store.delete(deleted_id)  # 先由 Store 验证并原子持久化删除结果。
        if deleted_id != current_session_id:  # 删除非当前 Session 时无需改变当前项。
            return current_session_id, [f"已删除 Session：{deleted_id}"]  # 返回原当前 ID。
        remaining = store.list()  # 删除当前项后查询剩余 Session。
        replacement = remaining[0] if remaining else store.create()  # 优先切到最近 Session；全空则创建安全默认项。
        return replacement.session_id, [  # 返回替代当前项和两行明确反馈。
            f"已删除 Session：{deleted_id}",  # 第一行确认删除目标。
            f"当前 Session：{replacement.session_id}（{replacement.title}）",  # 第二行告知后续消息写入位置。
        ]  # 结束反馈列表。

    raise ValueError(SESSION_USAGE)  # 所有未精确匹配的格式都只展示帮助，不执行副作用。


def run_chat_loop(  # 运行支持多 Session 命令的交互循环。
    runtime: ChatRuntime,  # 接收负责普通消息数据流的 Runtime。
    store: SessionStore,  # 接收负责命令查询和变更的 Session Store。
    current_session_id: str,  # 接收启动时恢复或创建的当前 Session ID。
    *,  # 强制后续输入输出函数使用关键字传入。
    input_fn: Callable[[str], str] = input,  # 默认读取真实终端，测试可注入输入序列。
    output_fn: Callable[[str], None] = print,  # 默认输出到标准输出，测试可注入列表 append。
    error_fn: Callable[[str], None] | None = None,  # 允许测试独立收集错误输出。
) -> None:  # 循环退出时不返回业务数据。
    """处理本地命令，并将普通消息路由到当前 Session。"""  # 说明 CLI 的职责边界。

    if error_fn is None:  # 调用者未指定错误输出时使用标准错误流。
        error_fn = lambda message: print(message, file=sys.stderr)  # 创建默认错误打印函数。

    current = store.get(current_session_id)  # 验证启动传入的当前 ID 并取得标题。
    output_fn("SJTUClaw 已启动。输入 /exit 退出，输入 /session list 查看会话。")  # 展示可用入口。
    output_fn(f"当前 Session：{current.session_id}（{current.title}）")  # 明确告诉用户消息将写入哪个 Session。
    while True:  # 持续读取输入直到退出或输入流结束。
        current = store.get(current_session_id)  # 每轮刷新标题，确保 rename 后提示立即更新。
        try:  # 捕获终端关闭和 Ctrl+C。
            user_message = input_fn(f"[{current.title}] 你：")  # 在提示符中展示当前 Session 标题。
        except (EOFError, KeyboardInterrupt):  # 处理管道结束或用户主动中断。
            output_fn("")  # 补换行保持终端排版整洁。
            output_fn("再见！")  # 输出友好退出提示。
            return  # 结束循环。

        stripped_message = user_message.strip()  # 统一去除命令判断所需的两端空白。
        if stripped_message == "/exit":  # 精确识别本地退出命令。
            output_fn("再见！")  # 告知用户程序结束。
            return  # 不把 /exit 写入 Store 或发送模型。
        if not stripped_message:  # 拒绝空串和纯空白输入。
            error_fn("错误：消息不能为空。")  # 给出可读提示。
            continue  # 不写 Store、不调用模型，直接读取下一条。

        if stripped_message == "/session" or stripped_message.startswith("/session "):  # 将所有 Session 命令留在 CLI 本地。
            try:  # 捕获格式、无效 ID 和持久化错误，保持进程存活。
                current_session_id, lines = handle_session_command(stripped_message, store, current_session_id)  # 执行命令并更新当前 ID。
            except (ValueError, SessionStoreError) as exc:  # 统一处理命令校验和 Store 错误。
                logging.error("Session command failed: %s", exc)  # 记录不含消息正文的诊断信息。
                error_fn(f"错误：{exc}")  # 向用户展示具体失败原因。
                continue  # 命令失败后继续交互。
            for line in lines:  # 逐行展示命令结果。
                output_fn(line)  # 使用可注入输出函数便于测试。
            continue  # 命令绝不继续落入普通模型消息路径。

        try:  # 单独保护每轮持久化和模型调用。
            answer = runtime.send(current_session_id, user_message)  # 将原始普通消息路由到当前 Session。
        except (LLMError, SessionStoreError, ValueError) as exc:  # 捕获模型、磁盘和输入校验错误。
            logging.error("Conversation turn failed: %s", exc)  # 记录错误类型但不记录 API Key。
            error_fn(f"错误：{exc}")  # 展示可操作错误并保持 CLI 存活。
            continue  # 允许用户继续输入或切换 Session。
        output_fn(f"AI：{answer}")  # 展示成功且已持久化的 assistant 回复。


def main() -> int:  # 定义模块启动主函数并返回进程退出码。
    try:  # 统一捕获启动阶段的目录、Session 文件和模型配置错误。
        ensure_runtime_directories()  # 确保 data 和 logs 目录存在。
        _configure_logging()  # 在日志目录存在后启用文件日志。
        store = SessionStore()  # 首先读取 Session 文件，使损坏数据不会被静默覆盖。
        settings = load_settings()  # 从环境变量或 .env 读取并校验模型配置。
        sessions = store.list()  # 恢复已有 Session，并按最近更新排序。
        current = sessions[0] if sessions else store.create()  # 默认恢复最近 Session；首次启动创建一个。
        runtime = SessionRuntime(store, LLMClient(settings))  # 组合 Store、Builder 和 LLM Client。
        logging.info("Starting session %s with model %s", current.session_id, settings.model)  # 记录 ID 和模型名但不记录 Key。
    except (ConfigurationError, SessionStoreError) as exc:  # 捕获所有可预期启动失败。
        logging.error("Startup failed: %s", exc)  # 将失败原因写入日志便于诊断。
        print(f"错误：{exc}", file=sys.stderr)  # 在终端展示清晰错误。
        return 1  # 返回非零状态表示启动失败。

    run_chat_loop(runtime, store, current.session_id)  # 配置成功后进入当前 Session 的交互循环。
    return 0  # 正常退出返回成功状态。


if __name__ == "__main__":  # 仅在 python -m src.cli 运行该模块时执行。
    raise SystemExit(main())  # 把 main 返回值传给操作系统作为退出码。
