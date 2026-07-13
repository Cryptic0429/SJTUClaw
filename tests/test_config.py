"""配置模块测试：每个用例按“准备、执行、断言”说明学习意图。"""

from __future__ import annotations  # 推迟类型注解求值。

import pytest  # 提供异常断言、临时目录和环境变量隔离能力。

from src.config import ConfigurationError, MissingAPIKeyError, load_settings  # 导入待验证的配置接口。


CONFIG_NAMES = ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL")  # 集中列出三个必填环境变量。


def clear_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """清空测试进程里的模型配置，避免本机真实配置影响结果。"""
    for name in CONFIG_NAMES:
        monkeypatch.delenv(name, raising=False)  # 变量不存在也不报错。


def test_load_settings_from_dotenv(tmp_path, monkeypatch):
    # 准备：创建只包含测试值的临时 .env。
    clear_config(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LLM_API_KEY=test-key\n"
        "LLM_BASE_URL=https://example.test/v1/\n"
        "LLM_MODEL=test-model\n",
        encoding="utf-8",
    )

    # 执行：从指定临时文件加载配置。
    settings = load_settings(env_file)

    # 断言：三个字段正确读取，且 URL 尾斜杠被规范化。
    assert settings.api_key == "test-key"
    assert settings.base_url == "https://example.test/v1"
    assert settings.model == "test-model"


def test_environment_overrides_dotenv(tmp_path, monkeypatch):
    # 准备：同时提供文件值与环境变量值。
    clear_config(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LLM_API_KEY=file-key\nLLM_BASE_URL=https://file.test/v1\nLLM_MODEL=file-model\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LLM_MODEL", "environment-model")

    # 执行并断言：环境变量应覆盖文件中的同名模型值。
    assert load_settings(env_file).model == "environment-model"


def test_missing_api_key_has_actionable_error(tmp_path, monkeypatch):
    # 准备：确保任何配置来源中都没有 API Key。
    clear_config(monkeypatch)
    # 执行并断言：应抛出专用异常，提示中包含配置名。
    with pytest.raises(MissingAPIKeyError, match="LLM_API_KEY"):
        load_settings(tmp_path / "missing.env")


def test_invalid_base_url_is_rejected(tmp_path, monkeypatch):
    # 准备：提供 Key 和模型，但故意使用无效 URL。
    clear_config(monkeypatch)
    monkeypatch.setenv("LLM_API_KEY", "key")
    monkeypatch.setenv("LLM_BASE_URL", "not-a-url")
    monkeypatch.setenv("LLM_MODEL", "model")

    # 执行并断言：URL 校验应在发起网络请求前失败。
    with pytest.raises(ConfigurationError, match="http/https"):
        load_settings(tmp_path / "missing.env")
