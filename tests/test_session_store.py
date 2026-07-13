"""验证 Session JSON 持久化、恢复、损坏保护和查询错误。"""  # 说明测试模块目标。

from __future__ import annotations  # 推迟类型注解求值。

import json  # 用于直接检查磁盘上的公开 JSON 字段结构。

import pytest  # 提供异常断言和临时目录 fixture。

from src.stores.session_store import (  # 导入 Store 及其可区分错误类型。
    SessionNotFoundError,
    SessionReadError,
    SessionStore,
    SessionWriteError,
)


def test_sessions_persist_and_restore_with_required_fields(tmp_path):  # 验证重启恢复和规格字段。
    # 准备：在临时路径创建、写消息并重命名一个 Session。
    path = tmp_path / "sessions.json"
    store = SessionStore(path)
    created = store.create()
    store.append_message(created.session_id, "user", "持久化消息")
    renamed = store.rename(created.session_id, "课程问题")

    # 执行：新建 Store 实例模拟程序重启，并读取同一个文件。
    restored = SessionStore(path).get(created.session_id)
    raw_session = json.loads(path.read_text(encoding="utf-8"))["sessions"][0]

    # 断言：元数据、历史和五个规格字段均被恢复。
    assert restored.title == "课程问题"
    assert restored.messages == [{"role": "user", "content": "持久化消息"}]
    assert restored.created_at == renamed.created_at
    assert set(raw_session) == {"sessionId", "title", "messages", "createdAt", "updatedAt"}


def test_returned_session_is_a_defensive_copy(tmp_path):  # 验证调用者不能绕过 Store 修改数据。
    # 准备：创建 Session 并修改 get 返回的对象。
    store = SessionStore(tmp_path / "sessions.json")
    created = store.create()
    external = store.get(created.session_id)
    external.messages.append({"role": "user", "content": "未通过 Store"})

    # 断言：Store 内部以及磁盘重新加载的数据都保持不变。
    assert store.get(created.session_id).messages == []
    assert SessionStore(store.path).get(created.session_id).messages == []


def test_corrupted_json_raises_and_is_never_overwritten(tmp_path):  # 验证损坏文件保护。
    # 准备：写入故意截断的 JSON，并保存原始字节文本。
    path = tmp_path / "sessions.json"
    original = '{"version": 1, "sessions": ['
    path.write_text(original, encoding="utf-8")

    # 执行并断言：初始化明确报错，且原始文件内容完全不变。
    with pytest.raises(SessionReadError, match="已损坏"):
        SessionStore(path)
    assert path.read_text(encoding="utf-8") == original


def test_read_failure_is_reported(tmp_path):  # 验证操作系统读取失败不会伪装成空数据。
    # 准备：把目录路径当作 Session 文件路径，使 read_text 失败。
    directory_path = tmp_path / "not-a-file"
    directory_path.mkdir()

    # 执行并断言：Store 返回明确的读取错误。
    with pytest.raises(SessionReadError, match="无法读取"):
        SessionStore(directory_path)


def test_save_failure_does_not_change_in_memory_state(tmp_path):  # 验证先落盘后提交策略。
    # 准备：创建一个普通文件作为“父目录”，使后续 mkdir 无法成功。
    blocked_parent = tmp_path / "blocked"
    blocked_parent.write_text("not a directory", encoding="utf-8")
    store = SessionStore(blocked_parent / "sessions.json")

    # 执行并断言：创建失败明确报错，Store 仍然没有半完成 Session。
    with pytest.raises(SessionWriteError, match="无法保存"):
        store.create()
    assert store.list() == []


def test_delete_unknown_id_has_readable_error(tmp_path):  # 验证无效 ID 不会静默成功。
    # 准备：创建空 Store。
    store = SessionStore(tmp_path / "sessions.json")

    # 执行并断言：删除不存在 ID 返回包含该 ID 的错误。
    with pytest.raises(SessionNotFoundError, match="missing-id"):
        store.delete("missing-id")
