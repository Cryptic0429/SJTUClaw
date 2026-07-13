"""验证 Runtime 的持久化顺序、完整历史和 Session 隔离。"""  # 说明测试模块目标。

from __future__ import annotations  # 推迟类型注解求值。

import pytest  # 提供异常断言。

from src.llm_client import LLMNetworkError  # 用真实项目错误模拟模型失败。
from src.runtime.context_builder import ContextBuilder  # 导入可辨识 system 的 Builder。
from src.runtime.session_runtime import SessionRuntime  # 导入待测 Runtime。
from src.stores.session_store import SessionStore  # 导入真实临时 JSON Store。


class RecordingClient:  # 创建记录完整请求并按顺序回复的假客户端。
    def __init__(self, replies: list[str]) -> None:  # 接收每轮预定回复。
        self._replies = iter(replies)  # 转成迭代器逐轮取值。
        self.calls: list[list[dict[str, str]]] = []  # 保存所有请求快照。

    def chat(self, messages):  # 模拟 LLMClient.chat 接口。
        self.calls.append([dict(message) for message in messages])  # 复制上下文供断言。
        return next(self._replies)  # 返回下一条模型回复。


def test_runtime_persists_history_and_isolates_sessions(tmp_path):  # 验证两个主题不互相泄漏。
    # 准备：创建两个 Session、假客户端和 Runtime。
    path = tmp_path / "sessions.json"
    store = SessionStore(path)
    first = store.create("数学")
    second = store.create("文学")
    client = RecordingClient(["答案 A", "答案 B"])
    runtime = SessionRuntime(store, client, ContextBuilder("system"))

    # 执行：分别在两个 Session 中发送不同主题消息。
    runtime.send(first.session_id, "问题 A")
    runtime.send(second.session_id, "问题 B")

    # 断言：第二个请求只含 system 和问题 B，不含第一个 Session 历史。
    assert client.calls[1] == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "问题 B"},
    ]
    assert "问题 A" not in str(client.calls[1])

    # 断言：模拟重启后，两份完整问答分别保存在自己的 Session。
    restored = SessionStore(path)
    assert restored.get(first.session_id).messages == [
        {"role": "user", "content": "问题 A"},
        {"role": "assistant", "content": "答案 A"},
    ]
    assert restored.get(second.session_id).messages == [
        {"role": "user", "content": "问题 B"},
        {"role": "assistant", "content": "答案 B"},
    ]


def test_model_failure_keeps_user_but_adds_no_assistant(tmp_path):  # 保留 Step 1 的失败安全规则。
    class FailingClient:  # 定义每次都模拟断网的客户端。
        def chat(self, messages):  # 实现最小 chat 接口。
            raise LLMNetworkError("offline")  # 在模型阶段抛出统一网络错误。

    # 准备：创建 Session 和使用失败客户端的 Runtime。
    store = SessionStore(tmp_path / "sessions.json")
    session = store.create()
    runtime = SessionRuntime(store, FailingClient())

    # 执行并断言：模型错误向上传递，不伪造回复。
    with pytest.raises(LLMNetworkError, match="offline"):
        runtime.send(session.session_id, "真实用户输入")

    # 断言：用户消息已真实保存，但不存在空 assistant。
    assert SessionStore(store.path).get(session.session_id).messages == [
        {"role": "user", "content": "真实用户输入"}
    ]
