"""读取并校验 Step 0/1 共用的 LLM 启动配置。"""  # 概括本模块职责。

from __future__ import annotations  # 推迟解析类型注解，支持更简洁的联合类型语法。

import os  # 导入操作系统接口，用来读取环境变量。
from dataclasses import dataclass  # 导入数据类装饰器，用于声明不可变配置对象。
from pathlib import Path  # 导入跨平台路径类型，用于读取 .env 和创建目录。
from urllib.parse import urlparse  # 导入 URL 解析器，用于校验 API 根地址。


class ConfigurationError(ValueError):  # 定义所有配置错误的公共基类。
    """表示必需的应用配置缺失或格式无效。"""  # 说明异常使用场景。


class MissingAPIKeyError(ConfigurationError):  # 为缺失 Key 提供更精确的异常类型。
    """表示用户尚未配置 LLM API Key。"""  # 说明异常使用场景。


@dataclass(frozen=True)  # 自动生成初始化方法，并禁止运行中修改配置。
class Settings:  # 集中保存通过校验的模型请求配置。
    api_key: str  # 保存服务商认证 Key，只用于 Authorization 请求头。
    base_url: str  # 保存 OpenAI 兼容 API 的根地址。
    model: str  # 保存每次 Chat Completions 请求使用的模型名。
    timeout_seconds: float = 30.0  # 设置网络请求默认最多等待 30 秒。


def _read_dotenv(path: Path) -> dict[str, str]:  # 读取项目所需的简化 KEY=VALUE 配置文件。
    """读取本项目所需的 .env 子集；无效非空行会明确报错。"""  # 说明解析策略。

    if not path.exists():  # 没有 .env 时仍允许完全依靠系统环境变量。
        return {}  # 返回空配置表，由 load_settings 继续检查必填项。

    values: dict[str, str] = {}  # 创建字典，逐项保存文件里的配置值。
    try:  # 捕获权限或磁盘等文件读取错误。
        lines = path.read_text(encoding="utf-8").splitlines()  # 用 UTF-8 一次读取并按行拆分。
    except OSError as exc:  # 处理所有操作系统级读取失败。
        raise ConfigurationError(f"无法读取配置文件 {path}: {exc}") from exc  # 转成统一配置错误并保留原因链。

    for line_number, raw_line in enumerate(lines, start=1):  # 遍历每行并从 1 开始记录用户熟悉的行号。
        line = raw_line.strip()  # 去除行首尾空白，方便识别空行和键值。
        if not line or line.startswith("#"):  # 忽略空行和以井号开头的注释行。
            continue  # 继续处理下一行。
        if line.startswith("export "):  # 兼容 shell 常见的 export KEY=VALUE 写法。
            line = line[7:].lstrip()  # 删除 export 前缀和其后的多余空格。
        if "=" not in line:  # 每个有效配置行都必须包含等号。
            raise ConfigurationError(  # 构造包含文件和行号的清晰错误。
                f"{path} 第 {line_number} 行不是有效的 KEY=VALUE 配置"  # 告诉用户应修复的确切位置。
            )  # 结束异常构造。
        key, value = line.split("=", 1)  # 只按第一个等号拆分，允许值本身包含等号。
        key = key.strip()  # 清理配置名两端空白。
        value = value.strip()  # 清理配置值两端空白。
        if not key:  # 拒绝等号左边为空的配置行。
            raise ConfigurationError(f"{path} 第 {line_number} 行的配置名为空")  # 指出具体格式错误。
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:  # 识别成对的单双引号。
            value = value[1:-1]  # 去除外围引号，保留其中的原始内容。
        values[key] = value  # 保存该键；同文件重复键以后出现的值为准。
    return values  # 返回从 .env 解析出的全部键值。


def load_settings(env_file: str | Path = ".env") -> Settings:  # 合并配置来源并返回强类型设置。
    """读取并校验配置；同名系统环境变量优先于 .env。"""  # 说明配置优先级。

    dotenv = _read_dotenv(Path(env_file))  # 将传入路径标准化后读取文件配置。

    def get(name: str) -> str:  # 定义只在本函数使用的统一取值辅助函数。
        return os.environ.get(name, dotenv.get(name, "")).strip()  # 优先取环境变量，并清理两端空白。

    api_key = get("LLM_API_KEY")  # 读取认证 Key。
    base_url = get("LLM_BASE_URL")  # 读取 OpenAI 兼容 API 根地址。
    model = get("LLM_MODEL")  # 读取模型名称。

    if not api_key:  # Key 为空时不能发起任何真实模型请求。
        raise MissingAPIKeyError(  # 抛出专用异常以提供可操作提示。
            "未配置 LLM_API_KEY。请复制 .env.example 为 .env 并填写 API Key，"  # 告知文件配置方法。
            "或设置同名环境变量。"  # 同时告知环境变量配置方法。
        )  # 结束缺失 Key 异常构造。
    if not base_url:  # 根地址为空时无法确定请求目标。
        raise ConfigurationError("未配置 LLM_BASE_URL。请在 .env 或环境变量中设置。")  # 明确指出缺失项。
    parsed_url = urlparse(base_url)  # 将 URL 拆成协议、主机、路径等部分。
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:  # 只接受带主机的 HTTP(S) 地址。
        raise ConfigurationError("LLM_BASE_URL 必须是有效的 http/https URL。")  # 拒绝相对路径和危险协议。
    if not model:  # 模型名为空时服务商无法选择模型。
        raise ConfigurationError("未配置 LLM_MODEL。请在 .env 或环境变量中设置。")  # 明确指出缺失项。

    return Settings(api_key=api_key, base_url=base_url.rstrip("/"), model=model)  # 去掉尾斜杠并构建不可变配置。


def ensure_runtime_directories(root: str | Path = ".") -> None:  # 准备运行数据和日志目录。
    """创建用于运行状态和日志的目录。"""  # 说明函数副作用。

    root_path = Path(root)  # 将字符串或 Path 统一为 Path 对象。
    for directory in (root_path / "data", root_path / "logs"):  # 依次处理数据目录和日志目录。
        try:  # 捕获目录创建时的权限、磁盘等错误。
            directory.mkdir(parents=True, exist_ok=True)  # 连同父目录创建；已存在时不报错。
        except OSError as exc:  # 处理操作系统级创建失败。
            raise ConfigurationError(f"无法创建运行目录 {directory}: {exc}") from exc  # 转成启动阶段可统一展示的错误。
