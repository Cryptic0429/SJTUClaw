"""验证 Context Builder 只发送稳定 system 和目标 Session 消息。"""  # 说明测试模块目标。

from __future__ import annotations  # 推迟类型注解求值。

from src.runtime.context_builder import ContextBuilder  # 导入待测 Builder。
from src.stores.session_store import Session  # 导入数据模型构造测试输入。


def test_context_excludes_session_metadata():  # 验证持久化结构与模型结构真正分离。
    # 准备：构造包含 ID、标题、时间和一条消息的 Session。
    session = Session(
        session_id="metadata-must-not-leak",
        title="私有标题",
        messages=[{"role": "user", "content": "你好"}],
        created_at="2026-07-12T00:00:00Z",
        updated_at="2026-07-12T00:00:00Z",
    )

    # 执行：使用可辨识的 system 指令构造模型上下文。
    context = ContextBuilder("测试系统指令").build(session)

    # 断言：上下文严格只有 system 和当前消息，不含任何元数据。
    assert context == [
        {"role": "system", "content": "测试系统指令"},
        {"role": "user", "content": "你好"},
    ]
    serialized = str(context)
    assert session.session_id not in serialized
    assert session.title not in serialized
    assert session.created_at not in serialized
