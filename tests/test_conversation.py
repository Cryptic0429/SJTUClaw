"""内存对话测试：解释历史写入顺序和失败保护。"""

from __future__ import annotations  # 推迟类型注解求值。

import pytest  # 提供参数化测试和异常断言。

from src.conversation import Conversation  # 导入待验证的内存对话类。


class FakeClient:
    """返回可配置固定回复，并记录收到消息的最小假客户端。"""

    def __init__(self, reply="reply"):
        self.reply = reply  # 保存测试希望模型返回的内容。
        self.received = None  # 稍后记录 Conversation 发送的完整历史。

    def chat(self, messages):
        self.received = messages  # 捕获本次请求，供断言检查。
        return self.reply  # 模拟模型成功或空回复。


def test_send_appends_user_then_successful_assistant():
    # 准备：创建空历史对话和返回 answer 的假客户端。
    client = FakeClient("answer")
    conversation = Conversation(client, initial_messages=[])

    # 执行并断言：send 应直接返回模型文本。
    assert conversation.send("question") == "answer"
    # 断言：调用模型时应已经包含当前 user 消息。
    assert client.received == [{"role": "user", "content": "question"}]
    # 断言：成功后历史按 user、assistant 的顺序保存。
    assert conversation.messages == [
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "answer"},
    ]


def test_messages_property_cannot_mutate_internal_history():
    # 准备：读取对话公开的历史快照。
    conversation = Conversation(FakeClient(), initial_messages=[])
    snapshot = conversation.messages
    # 执行：只修改外部快照。
    snapshot.append({"role": "user", "content": "injected"})

    # 断言：内部历史不应受到外部修改影响。
    assert conversation.messages == []


@pytest.mark.parametrize("message", ["", "   ", None])
def test_empty_message_is_rejected_without_changing_history(message):
    # 准备：创建一段空历史对话。
    conversation = Conversation(FakeClient(), initial_messages=[])

    # 执行并断言：各种空输入都应失败。
    with pytest.raises(ValueError, match="不能为空"):
        conversation.send(message)
    # 断言：无效输入不能污染历史。
    assert conversation.messages == []


@pytest.mark.parametrize("reply", ["", "   ", None])
def test_empty_reply_is_not_added_to_history(reply):
    # 准备：让假客户端返回各种无效空回复。
    conversation = Conversation(FakeClient(reply), initial_messages=[])

    # 执行并断言：Conversation 应拒绝空 assistant。
    with pytest.raises(ValueError, match="assistant"):
        conversation.send("question")
    # 断言：真实 user 输入保留，但不能插入 assistant 占位消息。
    assert conversation.messages == [{"role": "user", "content": "question"}]
