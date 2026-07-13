"""协调 Session Store、Context Builder 和 LLM Client 完成一轮对话。"""  # 概括模块职责。

from __future__ import annotations  # 推迟类型注解求值。

from collections.abc import Sequence  # 导入消息序列类型，用于声明最小客户端接口。
from typing import Protocol  # 导入协议类型，便于测试注入假客户端。

from .context_builder import ContextBuilder  # 导入只负责上下文组装的组件。
from ..stores.session_store import SessionStore  # 导入集中持久化组件。


class ChatClient(Protocol):  # 声明 Runtime 所需的最小 LLM 能力。
    def chat(self, messages: Sequence[dict[str, str]]) -> str: ...  # 要求接收完整 messages 并返回 assistant 文本。


class SessionRuntime:  # 提供普通聊天消息进入系统的唯一 Step 2 入口。
    """保存 user、构造上下文、调用模型，再保存 assistant。"""  # 说明一轮请求的数据流。

    def __init__(  # 通过依赖注入组合三个职责独立的组件。
        self,  # 接收当前 Runtime 实例。
        store: SessionStore,  # 接收负责所有 Session 持久化的 Store。
        client: ChatClient,  # 接收只负责 HTTP 模型请求的客户端。
        context_builder: ContextBuilder | None = None,  # 允许传入定制 Builder，默认创建标准版本。
    ) -> None:  # 声明构造方法无返回值。
        self._store = store  # 保存 Store 引用供每轮读写。
        self._client = client  # 保存 LLM 客户端引用供每轮调用。
        self._context_builder = context_builder or ContextBuilder()  # 未注入时使用默认系统指令 Builder。

    def send(self, session_id: str, user_message: str) -> str:  # 在指定 Session 中完成一轮普通消息。
        if not isinstance(user_message, str) or not user_message.strip():  # 拒绝空串、纯空白或错误类型输入。
            raise ValueError("消息不能为空。")  # 给 CLI 返回清晰输入错误。
        session = self._store.append_message(session_id, "user", user_message)  # 先真实持久化用户输入。
        context = self._context_builder.build(session)  # 仅从目标 Session 构造模型上下文。
        assistant_text = self._client.chat(context)  # 将完整上下文交给 LLM Client。
        if not isinstance(assistant_text, str) or not assistant_text.strip():  # 防御假客户端或异常兼容服务的空回复。
            raise ValueError("LLM 未返回有效的 assistant 文本内容。")  # 失败时绝不写入空 assistant。
        self._store.append_message(session_id, "assistant", assistant_text)  # 成功后持久化真实模型回复。
        return assistant_text  # 将回复交给 CLI 展示。
