"""实现最小的 OpenAI 兼容 Chat Completions HTTP 客户端。"""  # 概括本模块职责。

from __future__ import annotations  # 推迟类型注解求值，支持现代类型写法。

from collections.abc import Sequence  # 导入序列接口，用于约束 messages 参数。
from typing import Any  # 导入 Any，用来描述尚未校验的外部消息值。

import httpx  # 导入 HTTP 客户端库，负责连接、超时和 JSON 请求。

from .config import Settings  # 导入已经过校验的模型配置数据类。


class LLMError(RuntimeError):  # 定义所有模型请求错误的公共基类。
    """表示可安全展示给用户的 LLM 请求失败。"""  # 说明异常边界。


class LLMNetworkError(LLMError):  # 区分连接和超时类错误。
    """表示请求超时或底层网络传输失败。"""  # 说明异常场景。


class LLMHTTPError(LLMError):  # 区分服务端非成功状态码。
    """表示模型服务商返回了非 2xx HTTP 状态。"""  # 说明异常场景。


class LLMResponseError(LLMError):  # 区分成功状态下的响应格式问题。
    """表示成功响应无法解析出有效 assistant 文本。"""  # 说明异常场景。


class LLMClient:  # 封装一次 Chat Completions 请求的构造和解析。
    """发送 Chat Completions 请求并返回 assistant 文本。"""  # 说明类的输入输出边界。

    _ALLOWED_ROLES = {"system", "user", "assistant"}  # Step 1 只允许这三种标准消息角色。

    def __init__(  # 初始化模型客户端。
        self,  # 接收当前客户端实例。
        settings: Settings,  # 接收通过统一配置校验的参数。
        *,  # 强制 transport 使用关键字传入，避免误传。
        transport: httpx.BaseTransport | None = None,  # 允许测试注入 MockTransport，正常运行时为空。
    ) -> None:  # 声明初始化方法没有返回值。
        self._settings = settings  # 保存 API 地址、Key、模型和超时配置。
        self._transport = transport  # 保存可选传输层，以便无网络单元测试。

    def chat(self, messages: Sequence[dict[str, Any]]) -> str:  # 用一组完整消息请求模型文本。
        normalized = self._validate_messages(messages)  # 在联网前校验并规范化全部外部消息。
        url = f"{self._settings.base_url}/chat/completions"  # 拼出 OpenAI 兼容请求端点。
        headers = {  # 构造模型服务商需要的 HTTP 请求头。
            "Authorization": f"Bearer {self._settings.api_key}",  # 使用 Bearer 方式携带 API Key。
            "Content-Type": "application/json",  # 声明请求体使用 JSON 格式。
        }  # 结束请求头字典。
        payload = {"model": self._settings.model, "messages": normalized}  # 构造只含模型名和消息的最小请求体。

        try:  # 把底层 httpx 异常转换为项目自己的稳定错误类型。
            with httpx.Client(  # 创建会在代码块结束时自动关闭连接的同步客户端。
                timeout=self._settings.timeout_seconds,  # 应用配置中的总请求超时。
                transport=self._transport,  # 正常使用默认网络传输，测试可替换为 Mock。
            ) as client:  # 进入客户端上下文并确保资源最终释放。
                response = client.post(url, headers=headers, json=payload)  # 向模型端点发送 JSON POST 请求。
        except httpx.TimeoutException as exc:  # 单独识别所有连接、读写阶段的超时。
            raise LLMNetworkError("LLM 请求超时，请稍后重试或检查网络。") from exc  # 提供简洁建议并保留异常链。
        except httpx.RequestError as exc:  # 捕获断网、DNS、TLS 等其他请求错误。
            raise LLMNetworkError(f"LLM 网络请求失败：{exc}") from exc  # 转成 CLI 能统一处理的网络错误。

        if not response.is_success:  # 任何非 2xx 状态都不能当作模型回复解析。
            request_id = response.headers.get("x-request-id")  # 尝试提取服务商请求 ID 便于排障。
            suffix = f"（request id: {request_id}）" if request_id else ""  # 仅在存在时附加请求 ID。
            raise LLMHTTPError(f"LLM API 返回 HTTP {response.status_code}{suffix}。")  # 不回显响应正文，避免泄露敏感信息。

        try:  # 单独处理成功状态但响应体不是 JSON 的情况。
            body = response.json()  # 将 HTTP 响应正文解析为 Python 对象。
        except ValueError as exc:  # httpx 在 JSON 语法无效时抛出 ValueError。
            raise LLMResponseError("LLM API 返回的内容不是有效 JSON。") from exc  # 转换成明确的响应错误。

        try:  # 按 Chat Completions 标准结构逐层提取第一条回复。
            message = body["choices"][0]["message"]  # 取得第一个候选结果里的消息对象。
            role = message.get("role", "assistant")  # 某些兼容服务省略 role 时按 assistant 处理。
            content = message["content"]  # 取得模型实际回复文本。
        except (KeyError, IndexError, TypeError, AttributeError) as exc:  # 覆盖缺字段、空列表和类型错误。
            raise LLMResponseError("LLM API 响应结构异常：缺少 choices[0].message.content。") from exc  # 告知预期结构。

        if role != "assistant":  # 防止把 user 等其他角色内容误当模型回答。
            raise LLMResponseError("LLM API 响应结构异常：首个 choice 不是 assistant 消息。")  # 拒绝角色异常响应。
        if not isinstance(content, str) or not content.strip():  # 只接受包含非空白内容的字符串。
            raise LLMResponseError("LLM API 未返回有效的 assistant 文本内容。")  # 避免向对话写入空回复。
        return content  # 将有效 assistant 原文交给 Conversation。

    @classmethod  # 声明校验逻辑只依赖类常量，不依赖某个客户端实例。
    def _validate_messages(cls, messages: Sequence[dict[str, Any]]) -> list[dict[str, str]]:  # 校验外部消息并收窄类型。
        if isinstance(messages, (str, bytes)) or not isinstance(messages, Sequence):  # 排除“字符串也是序列”的特殊情况。
            raise ValueError("messages 必须是消息列表。")  # 要求调用者传入真正的消息序列。
        if not messages:  # Chat Completions 至少需要一条上下文消息。
            raise ValueError("messages 不能为空。")  # 在发 HTTP 请求前快速失败。

        normalized: list[dict[str, str]] = []  # 创建只含合法 role/content 字符串的新列表。
        for index, message in enumerate(messages):  # 遍历消息并记录索引，方便定位错误。
            if not isinstance(message, dict):  # 每条消息都必须是具有字段的字典。
                raise ValueError(f"messages[{index}] 必须是对象。")  # 指出无效消息的下标。
            role = message.get("role")  # 读取尚未校验的角色值。
            content = message.get("content")  # 读取尚未校验的正文值。
            if role not in cls._ALLOWED_ROLES:  # 拒绝 Step 1 尚未支持的 tool 等角色。
                raise ValueError(  # 构造角色约束错误。
                    f"messages[{index}].role 必须是 system、user 或 assistant。"  # 列出当前允许的三种角色。
                )  # 结束异常构造。
            if not isinstance(content, str) or not content.strip():  # 正文必须是非空白字符串。
                raise ValueError(f"messages[{index}].content 必须是非空字符串。")  # 指出具体无效字段。
            normalized.append({"role": role, "content": content})  # 仅复制模型 API 需要的两个安全字段。
        return normalized  # 返回经过完整校验、可直接序列化的消息列表。
