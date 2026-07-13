"""将稳定系统指令与指定 Session 的模型消息组装为请求上下文。"""  # 概括模块职责。

from __future__ import annotations  # 推迟类型注解求值。

from ..stores.session_store import Session  # 导入 Session 数据模型以读取消息历史。


SYSTEM_MESSAGE = "You are a concise and helpful AI assistant."  # Step 2 暂时在代码中保存稳定系统指令。


class ContextBuilder:  # 封装“持久化结构到模型结构”的转换规则。
    """只组装模型上下文，不读写 Store，也不调用 LLM。"""  # 强调职责边界。

    def __init__(self, system_message: str = SYSTEM_MESSAGE) -> None:  # 允许测试替换系统指令。
        if not isinstance(system_message, str) or not system_message.strip():  # 系统指令必须是非空字符串。
            raise ValueError("system_message 不能为空。")  # 在构造阶段拒绝无效稳定上下文。
        self._system_message = system_message  # 保存仅用于组装请求的系统指令。

    def build(self, session: Session) -> list[dict[str, str]]:  # 为一个指定 Session 构造完整模型 messages。
        context = [{"role": "system", "content": self._system_message}]  # system 始终位于上下文第一条。
        context.extend(dict(message) for message in session.messages)  # 复制并追加该 Session 独有的历史。
        return context  # 只返回 role/content，不发送标题、ID 或时间等元数据。
