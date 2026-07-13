"""LLM 客户端测试：使用 MockTransport 覆盖成功和全部错误边界。"""

from __future__ import annotations  # 推迟类型注解求值。

import json

import httpx
import pytest

from src.config import Settings
from src.llm_client import (
    LLMClient,
    LLMHTTPError,
    LLMNetworkError,
    LLMResponseError,
)


SETTINGS = Settings(  # 使用不会访问真实服务的统一测试配置。
    api_key="secret-test-key",
    base_url="https://example.test/v1",
    model="test-model",
)
MESSAGES = [  # 构造包含三种 Step 1 角色的完整示例历史。
    {"role": "system", "content": "Be helpful."},
    {"role": "user", "content": "Hello"},
    {"role": "assistant", "content": "Hi"},
]


def client_with(handler) -> LLMClient:
    """用指定请求处理器创建完全不联网的客户端。"""
    return LLMClient(SETTINGS, transport=httpx.MockTransport(handler))  # 注入 Mock 传输层。


def test_chat_sends_messages_and_returns_assistant_text():
    # 准备：在 Mock handler 内检查 URL、认证头和 JSON 请求体。
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://example.test/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer secret-test-key"
        payload = json.loads(request.content)
        assert payload == {"model": "test-model", "messages": MESSAGES}
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "你好！"}}]},
        )

    # 执行并断言：客户端应解析并返回 assistant 文本。
    assert client_with(handler).chat(MESSAGES) == "你好！"


def test_timeout_is_mapped_to_network_error():
    # 准备：模拟 httpx 读取超时。
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    # 执行并断言：底层超时应转换为项目网络错误。
    with pytest.raises(LLMNetworkError, match="超时"):
        client_with(handler).chat(MESSAGES)


def test_network_failure_is_mapped_to_network_error():
    # 准备：模拟无法连接服务商。
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    with pytest.raises(LLMNetworkError, match="网络请求失败"):
        client_with(handler).chat(MESSAGES)


def test_non_2xx_does_not_leak_provider_body_or_key():
    # 准备：让服务商错误正文故意包含测试 Key。
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="secret-test-key provider details")

    with pytest.raises(LLMHTTPError) as error:
        client_with(handler).chat(MESSAGES)
    # 断言：错误保留状态码，但绝不回显 Key 或服务商正文。
    assert "HTTP 401" in str(error.value)
    assert "secret-test-key" not in str(error.value)


def test_invalid_json_is_rejected():
    # 准备：返回 HTTP 200，但正文不是 JSON。
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    with pytest.raises(LLMResponseError, match="不是有效 JSON"):
        client_with(handler).chat(MESSAGES)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"choices": []},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"role": "assistant", "content": ""}}]},
        {"choices": [{"message": {"role": "user", "content": "wrong role"}}]},
    ],
)
def test_invalid_response_structures_are_rejected(body):
    # 准备：逐一返回缺字段、空 choices、空内容和错误角色。
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    # 执行并断言：所有异常结构都应转成统一响应错误。
    with pytest.raises(LLMResponseError):
        client_with(handler).chat(MESSAGES)


@pytest.mark.parametrize(
    "messages",
    [
        [],
        [{"role": "tool", "content": "no"}],
        [{"role": "user", "content": ""}],
        ["not a message"],
    ],
)
def test_invalid_messages_are_rejected_before_request(messages):
    # 准备：若 handler 被调用就立即让测试失败，以证明没有联网。
    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("invalid input must not cause an HTTP request")

    # 执行并断言：空列表、错误角色、空正文和非字典消息都被本地拒绝。
    with pytest.raises(ValueError):
        client_with(handler).chat(messages)
