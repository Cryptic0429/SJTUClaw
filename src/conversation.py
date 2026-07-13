"""实现 Step 1 使用的、仅保存在内存里的多轮对话。"""  # 概括本模块职责。

from __future__ import annotations  # 推迟解析类型注解，便于使用现代类型写法。

from collections.abc import Sequence  # 导入只读序列接口，用来描述消息列表。
from typing import Protocol  # 导入协议类型，用最小接口约束聊天客户端。


class ChatClient(Protocol):  # 定义 Conversation 所依赖的客户端接口，而非依赖具体实现。
    """描述 Conversation 调用模型时所需的最小客户端能力。"""  # 解释协议的作用。

    def chat(self, messages: Sequence[dict[str, str]]) -> str: ...  # 要求客户端接收消息并返回文本。


DEFAULT_MESSAGES = [  # 定义每段新对话默认携带的初始消息。
    {"role": "system", "content": "You are a concise and helpful AI assistant."}  # 设置模型的基础行为。
]  # 结束默认消息列表。


class Conversation:  # 封装一段进程内对话及其完整历史。
    """保存单个进程内的消息历史，并在每一轮发送完整上下文。"""  # 解释类的核心职责。

    def __init__(  # 初始化一段新对话。
        self,  # 接收当前 Conversation 实例。
        client: ChatClient,  # 接收符合 ChatClient 协议的模型客户端。
        initial_messages: Sequence[dict[str, str]] | None = None,  # 允许测试或调用者自定义初始历史。
    ) -> None:  # 声明初始化方法没有返回值。
        self._client = client  # 保存模型客户端，供后续每轮调用。
        source = DEFAULT_MESSAGES if initial_messages is None else initial_messages  # 未传历史时使用默认 system 消息。
        self._messages = [dict(message) for message in source]  # 深一层复制消息，防止外部修改内部历史。

    @property  # 把 messages 方法暴露为只读属性形式。
    def messages(self) -> list[dict[str, str]]:  # 声明属性返回一份消息列表快照。
        """返回当前内存历史的防御性副本。"""  # 说明调用者拿到的不是内部原对象。

        return [dict(message) for message in self._messages]  # 复制列表和每个字典后再返回。

    def send(self, user_message: str) -> str:  # 处理一轮普通用户消息并返回模型回复。
        """先记录 user，再发送完整历史；成功后才记录 assistant。"""  # 说明关键的数据写入顺序。

        if not isinstance(user_message, str) or not user_message.strip():  # 拒绝非字符串、空串和纯空白输入。
            raise ValueError("消息不能为空。")  # 用清晰错误告诉 CLI 输入无效。

        self._messages.append({"role": "user", "content": user_message})  # 先把真实用户输入加入历史。
        assistant_text = self._client.chat(self.messages)  # 用历史快照请求模型，避免客户端篡改内部列表。
        if not isinstance(assistant_text, str) or not assistant_text.strip():  # 再次保护，拒绝空模型回复。
            raise ValueError("LLM 未返回有效的 assistant 文本内容。")  # 空回复视为失败，不能写进历史。
        self._messages.append({"role": "assistant", "content": assistant_text})  # 仅在成功后记录 assistant 消息。
        return assistant_text  # 把有效回复交给 CLI 展示。
