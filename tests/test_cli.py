"""验证 Step 2 CLI 命令在本地执行，并正确路由当前 Session。"""  # 说明测试模块目标。

from __future__ import annotations  # 推迟类型注解求值。

import pytest  # 提供参数化测试。

from src import cli  # 导入待测 CLI 模块。
from src.stores.session_store import SessionStore  # 导入真实临时 Store。


class RecordingRuntime:  # 创建只记录普通消息且不调用网络的假 Runtime。
    def __init__(self) -> None:  # 初始化调用记录。
        self.calls: list[tuple[str, str]] = []  # 保存 sessionId 和消息正文。

    def send(self, session_id: str, user_message: str) -> str:  # 模拟 Runtime 成功回复。
        self.calls.append((session_id, user_message))  # 记录 CLI 实际路由目标。
        return "mock reply"  # 返回固定文本供输出断言。


def input_sequence(*values: str):  # 将字符串序列转换为可注入的终端输入函数。
    values_iterator = iter(values)  # 创建保持原顺序的迭代器。
    return lambda prompt: next(values_iterator)  # 每次忽略提示符并返回下一项。


def test_session_commands_create_list_switch_rename_and_delete(tmp_path):  # 覆盖全部五种命令。
    # 准备：创建初始 Session。
    store = SessionStore(tmp_path / "sessions.json")
    first = store.create("第一个")

    # 执行并断言 new：创建结果成为当前 Session。
    current_id, new_lines = cli.handle_session_command("/session new", store, first.session_id)
    assert current_id != first.session_id
    assert "已创建并切换" in new_lines[0]

    # 执行并断言 rename：标题可包含空格，且不改变当前项。
    current_id, rename_lines = cli.handle_session_command(
        f"/session rename {current_id} 新 标题", store, current_id
    )
    assert store.get(current_id).title == "新 标题"
    assert "新 标题" in rename_lines[0]

    # 执行并断言 list：星号只标记当前项。
    _, list_lines = cli.handle_session_command("/session list", store, current_id)
    assert sum(line.startswith("*") for line in list_lines) == 1
    assert any(first.session_id in line for line in list_lines)

    # 执行并断言 switch：切回第一个 Session。
    current_id, _ = cli.handle_session_command(
        f"/session switch {first.session_id}", store, current_id
    )
    assert current_id == first.session_id

    # 执行并断言 delete：删除当前项后自动选择剩余 Session。
    replacement_id, delete_lines = cli.handle_session_command(
        f"/session delete {first.session_id}", store, current_id
    )
    assert replacement_id != first.session_id
    assert "已删除" in delete_lines[0]


@pytest.mark.parametrize(  # 用多种错误格式证明 CLI 不猜测命令意图。
    "command",
    ["/session", "/session new extra", "/session switch", "/session rename only-id", "/session unknown"],
)
def test_invalid_session_command_shows_usage(command, tmp_path):  # 验证错误命令统一帮助。
    # 准备：创建一个有效当前 Session。
    store = SessionStore(tmp_path / "sessions.json")
    current = store.create()

    # 执行并断言：格式错误抛出包含用法的 ValueError。
    with pytest.raises(ValueError, match="用法"):
        cli.handle_session_command(command, store, current.session_id)


def test_session_command_never_reaches_runtime(tmp_path):  # 验证命令与模型路径严格分离。
    # 准备：创建 Store、假 Runtime 和 list/exit 输入。
    store = SessionStore(tmp_path / "sessions.json")
    current = store.create()
    runtime = RecordingRuntime()

    # 执行：运行只包含 Session 命令的短交互。
    cli.run_chat_loop(
        runtime,
        store,
        current.session_id,
        input_fn=input_sequence("/session list", "/exit"),
        output_fn=lambda message: None,
    )

    # 断言：Runtime 完全没有收到命令。
    assert runtime.calls == []


def test_switch_routes_messages_to_target_session(tmp_path):  # 验证切换后的普通消息目标。
    # 准备：创建两个 Session，并输入切换命令、普通消息和退出命令。
    store = SessionStore(tmp_path / "sessions.json")
    first = store.create("A")
    second = store.create("B")
    runtime = RecordingRuntime()

    # 执行：从 A 切到 B 后发送消息。
    cli.run_chat_loop(
        runtime,
        store,
        first.session_id,
        input_fn=input_sequence(f"/session switch {second.session_id}", "只给 B", "/exit"),
        output_fn=lambda message: None,
    )

    # 断言：普通消息只路由到 B。
    assert runtime.calls == [(second.session_id, "只给 B")]


def test_cli_restores_most_recent_session_on_start(monkeypatch, tmp_path):  # 验证 main 的重启恢复策略。
    # 准备：在隔离目录创建两个 Session，并配置 Mock 模型参数。
    monkeypatch.chdir(tmp_path)
    store = SessionStore("data/sessions.json")
    store.create("旧会话")
    newest = store.create("最近会话")
    monkeypatch.setenv("LLM_API_KEY", "key")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("LLM_MODEL", "model")
    captured_ids: list[str] = []
    monkeypatch.setattr(cli, "run_chat_loop", lambda runtime, loaded_store, current_id: captured_ids.append(current_id))

    # 执行并断言：main 不联网，并把最近更新 Session 交给循环。
    assert cli.main() == 0
    assert captured_ids == [newest.session_id]


def test_cli_missing_key_has_clear_message(monkeypatch, tmp_path, capsys):  # 保留 Step 0 缺失 Key 验收。
    # 准备：隔离目录并删除全部模型环境变量。
    monkeypatch.chdir(tmp_path)
    for name in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)

    # 执行并断言：main 返回 1 且错误明确提到 API Key。
    assert cli.main() == 1
    assert "LLM_API_KEY" in capsys.readouterr().err
