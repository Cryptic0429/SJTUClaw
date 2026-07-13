"""定义 Session 数据模型，并通过单个 JSON 文件安全持久化。"""  # 概括模块职责。

from __future__ import annotations  # 推迟类型注解求值，支持类自身作为返回类型。

import json  # 导入标准 JSON 库，用于序列化和解析 Session 数据。
import os  # 导入操作系统接口，用于刷盘和原子替换文件。
import tempfile  # 导入临时文件工具，用于先完整写入再替换正式文件。
from dataclasses import dataclass  # 导入数据类装饰器，减少模型样板代码。
from datetime import datetime, timedelta, timezone  # 导入带时区时间和微秒增量工具，统一保存 UTC 时间。
from pathlib import Path  # 导入跨平台路径类型。
from typing import Any  # 导入 Any，用于描述尚未校验的 JSON 外部数据。
from uuid import UUID, uuid4  # 导入 UUID 校验器和随机稳定 ID 生成器。


class SessionStoreError(RuntimeError):  # 定义 Session Store 所有错误的公共基类。
    """表示 Session 读取、校验、查询或保存失败。"""  # 解释异常边界。


class SessionReadError(SessionStoreError):  # 区分磁盘读取或 JSON 解析问题。
    """表示持久化文件无法安全读取。"""  # 说明异常用途。


class SessionWriteError(SessionStoreError):  # 区分创建目录或原子保存问题。
    """表示 Session 数据无法安全保存。"""  # 说明异常用途。


class SessionNotFoundError(SessionStoreError):  # 区分无效 Session ID。
    """表示请求的 Session ID 不存在。"""  # 说明异常用途。


class SessionValidationError(SessionStoreError):  # 区分文件内容结构损坏或无效输入。
    """表示 Session 字段或消息结构不符合约定。"""  # 说明异常用途。


def utc_now() -> str:  # 生成可排序、含时区的当前 UTC 时间文本。
    """返回 ISO 8601 UTC 时间，并用 Z 表示零时区。"""  # 解释时间格式。

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")  # 生成微秒精度的标准时间字符串。


def _validate_timestamp(value: Any, field_name: str) -> str:  # 校验来自 JSON 的时间字段。
    if not isinstance(value, str) or not value:  # 时间必须是非空字符串。
        raise SessionValidationError(f"{field_name} 必须是非空 ISO 8601 时间字符串。")  # 拒绝缺失或类型错误。
    try:  # 尝试按 ISO 8601 解析以发现损坏数据。
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))  # 将 Z 转成 Python 可直接识别的零时区。
    except ValueError as exc:  # 捕获日期数值和格式错误。
        raise SessionValidationError(f"{field_name} 不是有效的 ISO 8601 时间。") from exc  # 给出具体字段名。
    if parsed.tzinfo is None:  # 不接受缺少时区、含义模糊的本地时间。
        raise SessionValidationError(f"{field_name} 必须包含时区。")  # 要求所有时间可稳定比较。
    return value  # 校验通过后保留原始规范文本。


def _validate_title(title: Any) -> str:  # 校验用户提供或文件读取的 Session 标题。
    if not isinstance(title, str) or not title.strip():  # 标题必须是包含可见字符的字符串。
        raise SessionValidationError("Session 标题不能为空。")  # 用统一错误阻止无效标题。
    normalized = title.strip()  # 去掉标题两端无意义空白。
    if len(normalized) > 200:  # 限制标题长度，避免终端和 JSON 被异常输入撑大。
        raise SessionValidationError("Session 标题不能超过 200 个字符。")  # 明确告知长度上限。
    return normalized  # 返回可安全展示和保存的标题。


def _validate_messages(messages: Any) -> list[dict[str, str]]:  # 校验 Session 中持久化的模型消息。
    if not isinstance(messages, list):  # JSON messages 必须是数组。
        raise SessionValidationError("Session messages 必须是列表。")  # 拒绝对象、字符串等错误类型。
    normalized: list[dict[str, str]] = []  # 创建不共享原字典引用的规范消息列表。
    for index, message in enumerate(messages):  # 逐条检查并记录易读下标。
        if not isinstance(message, dict):  # 每条消息都必须是 JSON 对象。
            raise SessionValidationError(f"messages[{index}] 必须是对象。")  # 指出损坏位置。
        role = message.get("role")  # 读取尚未可信的消息角色。
        content = message.get("content")  # 读取尚未可信的消息正文。
        if role not in {"user", "assistant"}:  # Step 2 只在 Session 中保存用户和模型消息。
            raise SessionValidationError(f"messages[{index}].role 必须是 user 或 assistant。")  # 拒绝元数据或 system 混入。
        if not isinstance(content, str) or not content.strip():  # 消息正文必须是非空字符串。
            raise SessionValidationError(f"messages[{index}].content 必须是非空字符串。")  # 防止空消息污染上下文。
        normalized.append({"role": role, "content": content})  # 仅复制模型真正需要的字段。
    return normalized  # 返回完成校验的消息副本。


@dataclass  # 自动生成清晰的 Session 初始化方法。
class Session:  # 表示一个独立上下文容器及其持久化元数据。
    session_id: str  # 保存稳定 UUID，在命令和存储中定位 Session。
    title: str  # 保存便于用户识别的标题。
    messages: list[dict[str, str]]  # 保存该 Session 独有的 user/assistant 历史。
    created_at: str  # 保存 Session 创建时的 UTC 时间。
    updated_at: str  # 保存最近修改时的 UTC 时间。

    def to_dict(self) -> dict[str, Any]:  # 转成规格要求的 camelCase JSON 结构。
        return {  # 显式映射字段，避免内部实现细节意外写入磁盘。
            "sessionId": self.session_id,  # 输出稳定 Session ID。
            "title": self.title,  # 输出用户可见标题。
            "messages": [dict(message) for message in self.messages],  # 输出消息字典副本。
            "createdAt": self.created_at,  # 输出创建时间。
            "updatedAt": self.updated_at,  # 输出更新时间。
        }  # 结束 JSON 对象。

    @classmethod  # 声明解析函数通过类本身创建 Session 实例。
    def from_dict(cls, payload: Any) -> Session:  # 从不可信 JSON 对象校验并构造 Session。
        if not isinstance(payload, dict):  # 每个 Session 必须是 JSON 对象。
            raise SessionValidationError("每个 Session 必须是对象。")  # 拒绝列表项类型损坏。
        session_id = payload.get("sessionId")  # 读取稳定 ID。
        if not isinstance(session_id, str):  # UUID 文本首先必须是字符串。
            raise SessionValidationError("sessionId 必须是 UUID 字符串。")  # 拒绝缺失或错误类型。
        try:  # 使用标准库严格验证 UUID 文本。
            UUID(session_id)  # 仅执行校验，不需要保存解析对象。
        except ValueError as exc:  # 捕获 UUID 字符或长度无效。
            raise SessionValidationError("sessionId 必须是有效 UUID。") from exc  # 给出明确数据错误。
        return cls(  # 用全部校验后的字段构建内部数据模型。
            session_id=session_id,  # 保存已验证 UUID。
            title=_validate_title(payload.get("title")),  # 校验并保存标题。
            messages=_validate_messages(payload.get("messages")),  # 校验并复制消息。
            created_at=_validate_timestamp(payload.get("createdAt"), "createdAt"),  # 校验创建时间。
            updated_at=_validate_timestamp(payload.get("updatedAt"), "updatedAt"),  # 校验更新时间。
        )  # 结束 Session 构造。

    def copy(self) -> Session:  # 为 Store 调用者提供不会反向修改内部状态的副本。
        return Session.from_dict(self.to_dict())  # 借助现有序列化和校验逻辑完成深一层复制。


class SessionStore:  # 集中负责 Session 的查询、变更和 JSON 持久化。
    """通过原子文件替换持久化多个 Session。"""  # 强调写入安全策略。

    _FORMAT_VERSION = 1  # 保存顶层格式版本，为未来迁移保留依据。

    def __init__(self, path: str | Path = "data/sessions.json") -> None:  # 初始化 Store 并立即恢复已有数据。
        self._path = Path(path)  # 统一保存目标为 Path 对象。
        self._sessions = self._load()  # 读取并校验整个文件；损坏时直接阻止启动。

    @property  # 以只读属性公开当前持久化文件位置。
    def path(self) -> Path:  # 声明属性返回 Path。
        return self._path  # 返回路径对象，主要用于诊断和测试。

    def _load(self) -> dict[str, Session]:  # 从磁盘恢复全部 Session。
        if not self._path.exists():  # 首次启动没有数据文件属于正常情况。
            return {}  # 返回空集合，但此时不主动创建文件。
        try:  # 捕获权限、路径和磁盘读取错误。
            raw_text = self._path.read_text(encoding="utf-8")  # 使用 UTF-8 读取完整 JSON 文本。
        except OSError as exc:  # 处理所有系统级读取失败。
            raise SessionReadError(f"无法读取 Session 文件 {self._path}: {exc}") from exc  # 保留路径和底层原因。
        try:  # 将 JSON 语法错误与文件读取错误区分开。
            payload = json.loads(raw_text)  # 解析外部持久化内容。
        except json.JSONDecodeError as exc:  # 捕获截断、乱码结构等 JSON 语法问题。
            raise SessionReadError(  # 转成不会被 CLI 静默忽略的明确错误。
                f"Session 文件 {self._path} 已损坏（第 {exc.lineno} 行，第 {exc.colno} 列）；原文件未被覆盖。"  # 指出修复位置和保护行为。
            ) from exc  # 保留原始解析异常链。
        if not isinstance(payload, dict):  # 顶层必须是包含版本和列表的对象。
            raise SessionReadError("Session 文件顶层必须是对象；原文件未被覆盖。")  # 拒绝意外格式。
        if payload.get("version") != self._FORMAT_VERSION:  # 只读取当前明确支持的格式版本。
            raise SessionReadError("Session 文件版本不受支持；原文件未被覆盖。")  # 避免错误解释其他版本数据。
        raw_sessions = payload.get("sessions")  # 读取 Session 数组。
        if not isinstance(raw_sessions, list):  # 数组缺失或类型错误表示结构损坏。
            raise SessionReadError("Session 文件缺少 sessions 列表；原文件未被覆盖。")  # 明确报告结构问题。
        sessions: dict[str, Session] = {}  # 创建以稳定 ID 索引的内存表。
        try:  # 把具体字段校验错误包装为读取错误。
            for raw_session in raw_sessions:  # 逐个解析持久化 Session。
                session = Session.from_dict(raw_session)  # 校验所有元数据和消息。
                if session.session_id in sessions:  # 同一文件不允许重复稳定 ID。
                    raise SessionValidationError(f"发现重复 sessionId：{session.session_id}")  # 防止后项静默覆盖前项。
                sessions[session.session_id] = session  # 保存完成校验的 Session。
        except SessionValidationError as exc:  # 捕获任何 Session 字段损坏。
            raise SessionReadError(f"Session 文件内容无效：{exc}；原文件未被覆盖。") from exc  # 统一为启动可展示的读取错误。
        return sessions  # 只有整个文件完全有效时才返回数据。

    def _save(self, sessions: dict[str, Session]) -> None:  # 将候选状态完整原子保存到磁盘。
        payload = {  # 构建带版本号的稳定顶层 JSON 结构。
            "version": self._FORMAT_VERSION,  # 写入当前格式版本。
            "sessions": [session.to_dict() for session in sessions.values()],  # 序列化所有候选 Session。
        }  # 结束顶层对象。
        temporary_path: Path | None = None  # 记录临时文件名，失败时用于清理。
        try:  # 统一捕获目录创建、写入、刷盘和替换错误。
            self._path.parent.mkdir(parents=True, exist_ok=True)  # 确保持久化目录存在。
            with tempfile.NamedTemporaryFile(  # 在目标同目录创建临时文件，保证可原子替换。
                mode="w",  # 以文本写入模式打开。
                encoding="utf-8",  # 使用 UTF-8 保存中英文内容。
                dir=self._path.parent,  # 临时文件必须与目标处于同一文件系统。
                prefix=f".{self._path.name}.",  # 使用可识别但不冲突的临时前缀。
                suffix=".tmp",  # 使用临时后缀，便于诊断残留文件。
                delete=False,  # Windows 下需先关闭文件才能执行 os.replace。
            ) as temporary_file:  # 自动关闭临时文件句柄。
                temporary_path = Path(temporary_file.name)  # 保存实际生成的临时路径。
                json.dump(payload, temporary_file, ensure_ascii=False, indent=2)  # 以易读格式完整写入候选数据。
                temporary_file.write("\n")  # 在文件结尾添加标准换行。
                temporary_file.flush()  # 将 Python 缓冲区内容交给操作系统。
                os.fsync(temporary_file.fileno())  # 请求操作系统把内容真正刷到磁盘。
            os.replace(temporary_path, self._path)  # 用完整临时文件原子替换正式文件。
        except (OSError, TypeError, ValueError) as exc:  # 捕获文件系统和意外序列化失败。
            if temporary_path is not None:  # 仅在临时文件已经创建时尝试清理。
                try:  # 清理失败不能掩盖原始保存错误。
                    temporary_path.unlink(missing_ok=True)  # 删除未完成的临时文件。
                except OSError:  # 忽略清理阶段的次要磁盘错误。
                    pass  # 保留并继续抛出最初的保存失败。
            raise SessionWriteError(f"无法保存 Session 文件 {self._path}: {exc}") from exc  # 向上层提供清晰错误。

    def _commit(self, candidate: dict[str, Session]) -> None:  # 先落盘再更新 Store 内存状态。
        self._save(candidate)  # 保存失败会抛错，因此不会执行下一行。
        self._sessions = candidate  # 只有磁盘成功后才切换到新状态。

    def _next_timestamp(self) -> str:  # 生成严格晚于 Store 现有更新时间的新时间。
        current = datetime.now(timezone.utc)  # 先读取真实 UTC 时钟。
        if self._sessions:  # 只有已存在 Session 时才需要检查时间碰撞。
            latest_text = max(session.updated_at for session in self._sessions.values())  # 找出磁盘状态中的最大更新时间。
            latest = datetime.fromisoformat(latest_text.replace("Z", "+00:00"))  # 把最大时间解析为可比较对象。
            if current <= latest:  # Windows 时钟分辨率可能让连续操作得到相同甚至不前进的时间。
                current = latest + timedelta(microseconds=1)  # 最少增加一微秒，保证“最近更新”排序稳定。
        return current.isoformat().replace("+00:00", "Z")  # 返回与持久化格式一致的 UTC 文本。

    def create(self, title: str = "新会话") -> Session:  # 创建并持久化一个空 Session。
        now = self._next_timestamp()  # 同一次创建使用严格递增且一致的创建和更新时间。
        session = Session(  # 构造新 Session 数据模型。
            session_id=str(uuid4()),  # 生成跨重启稳定且几乎不冲突的 UUID。
            title=_validate_title(title),  # 校验并规范化用户标题。
            messages=[],  # 新 Session 从空的 user/assistant 历史开始。
            created_at=now,  # 保存创建时刻。
            updated_at=now,  # 初始更新时间等于创建时间。
        )  # 结束 Session 构造。
        candidate = dict(self._sessions)  # 复制当前索引，避免保存失败污染内存。
        candidate[session.session_id] = session  # 只修改候选状态。
        self._commit(candidate)  # 原子保存后再提交到内存。
        return session.copy()  # 返回防御性副本，防止调用者绕过 Store 修改。

    def list(self) -> list[Session]:  # 列出全部 Session，最近更新的排在前面。
        ordered = sorted(self._sessions.values(), key=lambda item: item.updated_at, reverse=True)  # 按 ISO UTC 时间降序排列。
        return [session.copy() for session in ordered]  # 返回副本列表保护 Store 状态。

    def get(self, session_id: str) -> Session:  # 按稳定 ID 查询单个 Session。
        session = self._sessions.get(session_id)  # 从内存索引快速查找。
        if session is None:  # ID 不存在时不能创建或猜测替代项。
            raise SessionNotFoundError(f"Session 不存在：{session_id}")  # 返回可读错误。
        return session.copy()  # 返回防御性副本。

    def append_message(self, session_id: str, role: str, content: str) -> Session:  # 向指定 Session 追加一条消息。
        session = self.get(session_id)  # 先验证 ID 并取得独立副本。
        validated_message = _validate_messages([{"role": role, "content": content}])[0]  # 复用统一消息校验。
        session.messages.append(validated_message)  # 只修改副本中的历史。
        session.updated_at = self._next_timestamp()  # 每次消息变化都使用严格递增的更新时间。
        candidate = dict(self._sessions)  # 复制索引形成候选状态。
        candidate[session_id] = session  # 用修改后的副本替换候选项。
        self._commit(candidate)  # 原子保存全部候选数据。
        return session.copy()  # 返回保存后的 Session 快照。

    def rename(self, session_id: str, title: str) -> Session:  # 修改指定 Session 标题。
        session = self.get(session_id)  # 验证 ID 并取得副本。
        session.title = _validate_title(title)  # 校验并写入新标题。
        session.updated_at = self._next_timestamp()  # 标题变化也使用严格递增的更新时间。
        candidate = dict(self._sessions)  # 创建候选状态。
        candidate[session_id] = session  # 替换候选 Session。
        self._commit(candidate)  # 保存成功后提交。
        return session.copy()  # 返回新标题的安全快照。

    def delete(self, session_id: str) -> None:  # 永久删除指定 Session。
        self.get(session_id)  # 先验证 ID，确保无效删除会清晰报错。
        candidate = dict(self._sessions)  # 创建不影响当前内存的候选索引。
        del candidate[session_id]  # 仅从候选状态移除目标项。
        self._commit(candidate)  # 原子保存删除结果后再更新内存。
