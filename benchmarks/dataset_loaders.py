"""Validated loaders and deterministic fallback generators for memory benchmarks.

The loaders accept local JSON exports from public benchmark repositories.
Network access is deliberately opt-in: benchmark runs remain reproducible and
usable offline, while callers can fetch an official Hugging Face file using
``download_huggingface_dataset`` and fall back to generated data on failure.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TypeAlias
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

JsonObject: TypeAlias = dict[str, object]
HistoryMessage: TypeAlias = dict[str, str]
LongMemEvalSample: TypeAlias = tuple[list[HistoryMessage], str, str]


class DatasetLoadError(ValueError):
    """Raised when a benchmark dataset cannot be read or validated."""


class DatasetDownloadError(RuntimeError):
    """Raised when an official dataset cannot be downloaded safely."""


class _HistoryMessage(BaseModel):
    """Canonical validated conversation message."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    role: str = Field(min_length=1, max_length=40)
    content: str = Field(min_length=1)


class _LongMemEvalRecord(BaseModel):
    """Validated subset of LongMemEval fields used by the benchmark."""

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    question_id: str | None = None


class FactConflictRecord(BaseModel):
    """Validated atomic change to a subject-predicate fact.

    Attributes:
        subject: Entity whose fact changes.
        predicate: Relationship that changes.
        old_object: Previous fact value.
        new_object: Replacement fact value.
        timestamp: ISO 8601 timestamp for the change.
    """

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    subject: str = Field(min_length=1, max_length=300)
    predicate: str = Field(min_length=1, max_length=300)
    old_object: str = Field(min_length=1, max_length=1000)
    new_object: str = Field(min_length=1, max_length=1000)
    timestamp: str = Field(min_length=1, max_length=100)

    @field_validator("timestamp")
    @classmethod
    def validate_iso_timestamp(cls, value: str) -> str:
        """Require an ISO-8601-like timestamp with a parseable calendar date.

        Args:
            value: Timestamp string from the dataset record.

        Returns:
            The normalized original string.

        Raises:
            ValueError: If the value is not a parseable ISO timestamp.
        """
        from datetime import datetime

        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("timestamp 必须是 ISO 8601 日期时间") from exc
        if parsed.tzinfo is None:
            raise ValueError("timestamp 必须包含时区偏移")
        return value


def _read_json(file_path: str | Path) -> object:
    """Read one UTF-8 JSON file and translate I/O/parser failures.

    Args:
        file_path: Dataset file path.

    Returns:
        The decoded JSON value.

    Raises:
        DatasetLoadError: If reading, decoding, or parsing fails.
    """
    path = Path(file_path)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DatasetLoadError(f"无法读取数据集 {path}: {exc}") from exc


def _record_list(payload: object) -> list[object]:
    """Normalize common JSON top-level dataset container shapes.

    Args:
        payload: Decoded JSON array or object.

    Returns:
        Dataset records from an array or a conventional container property.

    Raises:
        DatasetLoadError: If no supported record collection is present.
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "records", "examples", "samples", "questions"):
            records = payload.get(key)
            if isinstance(records, list):
                return records
    raise DatasetLoadError("JSON 顶层必须是记录数组或包含 records/data 的对象")


def _extract_message_content(message: object) -> HistoryMessage | None:
    """Convert a common chat-message representation into canonical form.

    Args:
        message: Dataset message dictionary.

    Returns:
        Validated role/content dictionary, or ``None`` for unsupported shapes.
    """
    if isinstance(message, str):
        return {"role": "user", "content": message}
    if not isinstance(message, dict):
        return None

    role = message.get("role", message.get("speaker", message.get("from", "user")))
    content = message.get(
        "content",
        message.get("text", message.get("value", message.get("message"))),
    )
    if isinstance(content, (dict, list)):
        content = json.dumps(content, ensure_ascii=False)
    if not isinstance(role, str) or not isinstance(content, str):
        return None
    try:
        validated = _HistoryMessage(role=role, content=content)
    except ValidationError:
        return None
    return validated.model_dump()


def _history_messages(record: dict[str, object]) -> list[HistoryMessage]:
    """Flatten LongMemEval history sessions while preserving message order.

    Args:
        record: One source LongMemEval record.

    Returns:
        Normalized ordered messages from direct history or session arrays.

    Raises:
        DatasetLoadError: If no valid history messages are present.
    """
    messages: list[HistoryMessage] = []
    direct_history = record.get("history_messages", record.get("messages"))
    if isinstance(direct_history, list):
        for message in direct_history:
            normalized = _extract_message_content(message)
            if normalized is not None:
                messages.append(normalized)

    sessions = record.get(
        "haystack_sessions",
        record.get("sessions", record.get("history")),
    )
    if isinstance(sessions, list):
        for session in sessions:
            if isinstance(session, dict):
                session_messages = session.get(
                    "messages",
                    session.get("conversation", session.get("dialogue", [])),
                )
            else:
                session_messages = session
            if isinstance(session_messages, list):
                for message in session_messages:
                    normalized = _extract_message_content(message)
                    if normalized is not None:
                        messages.append(normalized)

    if not messages:
        raise DatasetLoadError("LongMemEval 记录没有可识别的 history_messages")
    return messages


class LongMemEvalLoader:
    """Load LongMemEval JSON records as history/question/answer triples.

    The loader handles the public ``longmemeval_s_cleaned.json`` layout
    (``haystack_sessions``, ``question`` and ``answer``) and common flattened
    equivalents used by re-serialized exports.
    """

    def load(self, file_path: str) -> list[LongMemEvalSample]:
        """Parse a LongMemEval JSON file into canonical sample triples.

        Args:
            file_path: Path to the official or compatible JSON export.

        Returns:
            Samples shaped as ``(history_messages, target_question,
            ground_truth)``.

        Raises:
            DatasetLoadError: If the file contains invalid or empty records.
        """
        records = _record_list(_read_json(file_path))
        samples: list[LongMemEvalSample] = []
        for index, raw_record in enumerate(records):
            if not isinstance(raw_record, dict):
                raise DatasetLoadError(f"第 {index} 条 LongMemEval 记录不是对象")
            answer_value = raw_record.get(
                "ground_truth",
                raw_record.get("answer", raw_record.get("answer_text")),
            )
            try:
                record = _LongMemEvalRecord(
                    question=raw_record.get(
                        "target_question",
                        raw_record.get("question"),
                    ),
                    answer=answer_value,
                    question_id=raw_record.get("question_id"),
                )
                messages = _history_messages(raw_record)
            except ValidationError as exc:
                raise DatasetLoadError(
                    f"第 {index} 条 LongMemEval 记录校验失败: {exc}"
                ) from exc
            except DatasetLoadError as exc:
                raise DatasetLoadError(
                    f"第 {index} 条 LongMemEval 记录校验失败: {exc}"
                ) from exc
            samples.append((messages, record.question, record.answer))

        if not samples:
            raise DatasetLoadError("LongMemEval 数据集为空")
        return samples


class FactConflictLoader:
    """Parse fact-consolidation and fact-evolution records.

    Canonical records require ``subject``, ``predicate``, ``old_object``,
    ``new_object`` and ``timestamp``. Common nested ``old_fact`` /
    ``new_fact`` dictionaries are also accepted.
    """

    def load(self, file_path: str) -> list[FactConflictRecord]:
        """Load and validate fact-conflict records from a JSON file.

        Args:
            file_path: JSON export from a consolidation/conflict benchmark.

        Returns:
            Validated records with old and replacement fact values.

        Raises:
            DatasetLoadError: If the data is unreadable or has invalid records.
        """
        records = _record_list(_read_json(file_path))
        validated_records: list[FactConflictRecord] = []
        for index, raw_record in enumerate(records):
            if not isinstance(raw_record, dict):
                raise DatasetLoadError(f"第 {index} 条冲突记录不是对象")
            normalized = dict(raw_record)
            old_fact = normalized.get("old_fact")
            new_fact = normalized.get("new_fact")
            if isinstance(old_fact, dict):
                normalized.setdefault("subject", old_fact.get("subject"))
                normalized.setdefault("predicate", old_fact.get("predicate"))
                normalized.setdefault("old_object", old_fact.get("object"))
            if isinstance(new_fact, dict):
                normalized.setdefault("subject", new_fact.get("subject"))
                normalized.setdefault("predicate", new_fact.get("predicate"))
                normalized.setdefault("new_object", new_fact.get("object"))
            if "timestamp" not in normalized:
                normalized["timestamp"] = normalized.get(
                    "time",
                    normalized.get("valid_from"),
                )
            try:
                validated_records.append(FactConflictRecord.model_validate(normalized))
            except ValidationError as exc:
                raise DatasetLoadError(
                    f"第 {index} 条冲突记录校验失败: {exc}"
                ) from exc

        if not validated_records:
            raise DatasetLoadError("事实冲突数据集为空")
        return validated_records


def generate_mock_longmemeval_record(
    *,
    turns: int = 60,
    token_budget: int = 200_000,
) -> dict[str, object]:
    """Create an offline LongMemEval-shaped history with a needle fact.

    Args:
        turns: Number of user/assistant conversation turns.
        token_budget: Approximate whitespace-token count for history content.

    Returns:
        A JSON-compatible record containing many distractor messages and one
        answer-bearing memory in standard LongMemEval-style fields.

    Raises:
        ValueError: If the turn count or token budget is non-positive.
    """
    if turns < 1 or token_budget < 1:
        raise ValueError("turns 和 token_budget 必须为正整数")

    tokens_per_message = max(token_budget // (turns * 2), 1)
    sessions: list[list[HistoryMessage]] = []
    for turn in range(turns):
        filler = " ".join(
            f"context{turn}_{token_index}"
            for token_index in range(tokens_per_message)
        )
        user_content = f"Conversation turn {turn}: routine project update. {filler}"
        assistant_content = f"Noted routine update {turn}. {filler}"
        if turn == turns - 1:
            assistant_content += (
                " Important personal fact: the user's favorite city is "
                "Reykjavik, Iceland."
            )
        sessions.append(
            [
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": assistant_content},
            ]
        )
    return {
        "question_id": "mock-longmemeval-needle-001",
        "question_type": "single-session-user",
        "question": "Which city is the user's favorite city?",
        "answer": "Reykjavik, Iceland",
        "haystack_sessions": sessions,
    }


def generate_mock_fact_conflicts(count: int = 12) -> list[dict[str, str]]:
    """Generate time-ordered FactConsolidation-style fact changes.

    Args:
        count: Number of distinct subject-predicate conflict records.

    Returns:
        Schema-compliant fact-conflict dictionaries suitable for JSON export.

    Raises:
        ValueError: If ``count`` is less than one.
    """
    if count < 1:
        raise ValueError("count 必须至少为 1")
    executives = [
        "CEO甲",
        "CEO乙",
        "CEO丙",
        "CEO丁",
        "CEO戊",
        "CEO己",
        "CEO庚",
        "CEO辛",
        "CEO壬",
        "CEO癸",
        "CEO子",
        "CEO丑",
    ]
    records: list[dict[str, str]] = []
    for index in range(count):
        executive_index = index % (len(executives) - 1)
        records.append(
            {
                "subject": "A公司",
                "predicate": "CEO",
                "old_object": executives[executive_index],
                "new_object": executives[executive_index + 1],
                "timestamp": f"2024-01-{index + 2:02d}T09:00:00Z",
            }
        )
    return records


def generate_daily_chatter_corpus() -> list[str]:
    """Return realistic short Chinese daily-life distractor utterances.

    Returns:
        Distinct everyday utterances spanning weather, work, commuting, and
        market chatter for offline noise-resistance scenarios.
    """
    return [
        "今天早高峰地铁比平时拥挤，路上多花了十分钟。",
        "下午天气预报说可能下雨，出门记得带伞。",
        "今天的股票指数跌了一点，先不看盘了。",
        "午饭吃了番茄鸡蛋面，味道还不错。",
        "周末想去公园散步，看看最近开的花。",
        "刚整理完收件箱，还有几封邮件需要回复。",
        "今天咖啡有点苦，下次换一家店试试。",
        "晚上准备早点休息，最近睡眠不太规律。",
        "路边新开了一家书店，周末有空去逛逛。",
        "会议比计划提前结束，接下来整理一下笔记。",
        "窗外风挺大，阳台上的衣服已经收进来了。",
        "今天新闻里在讨论市场波动，信息量有点大。",
        "通勤路上听完了一期播客，讲的是城市生活。",
        "冰箱里还有蔬菜，今晚简单做个晚饭。",
        "最近温度变化挺快，早晚出门要多穿一件。",
        "手机系统更新完成，暂时没有发现异常。",
    ]


def write_json_dataset(file_path: str | Path, payload: object) -> Path:
    """Persist a generated or downloaded-format dataset atomically.

    Args:
        file_path: Destination JSON path.
        payload: JSON-serializable dataset content.

    Returns:
        Resolved path of the committed file.

    Raises:
        DatasetLoadError: If serialization or a filesystem operation fails.
    """
    path = Path(file_path)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(payload, ensure_ascii=False, indent=2)
        temporary_path.write_text(encoded + "\n", encoding="utf-8")
        temporary_path.replace(path)
        return path.resolve()
    except (OSError, TypeError, ValueError) as exc:
        cleanup_error: OSError | None = None
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError as cleanup_exc:
            cleanup_error = cleanup_exc
        detail = f"无法写入数据集 {path}: {exc}"
        if cleanup_error is not None:
            detail += f"；临时文件清理失败：{cleanup_error}"
        raise DatasetLoadError(detail) from exc


def download_huggingface_dataset(
    dataset_id: str,
    filename: str,
    target_path: str | Path,
    *,
    timeout: float = 10.0,
    retries: int = 2,
) -> Path:
    """Download one public dataset file from its Hugging Face repository.

    Args:
        dataset_id: Repository identifier, for example
            ``xiaowu0162/longmemeval-cleaned``.
        filename: Repository-relative JSON file path.
        target_path: Local path where the verified JSON file will be stored.
        timeout: Per-attempt network timeout in seconds.
        retries: Number of retries after the first request.

    Returns:
        Resolved path to the downloaded JSON dataset.

    Raises:
        DatasetDownloadError: If arguments are invalid, the request fails, or
            the response is not valid JSON.
    """
    if (
        not dataset_id.strip()
        or not filename.strip()
        or timeout <= 0
        or retries < 0
    ):
        raise DatasetDownloadError("数据集标识、文件名、超时或重试参数无效")

    encoded_filename = quote(filename.lstrip("/"), safe="/")
    url = (
        f"https://huggingface.co/datasets/{dataset_id.strip()}"
        f"/resolve/main/{encoded_filename}"
    )
    request = Request(url, headers={"User-Agent": "RecallWeaver-Benchmark/1.0"})
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        temporary_path = Path(target_path).with_suffix(
            Path(target_path).suffix + ".download"
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read()
            json.loads(body.decode("utf-8"))
            destination = Path(target_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary_path.write_bytes(body)
            temporary_path.replace(destination)
            return destination.resolve()
        except (HTTPError, URLError, TimeoutError, OSError, UnicodeError, json.JSONDecodeError) as exc:
            last_error = exc
            cleanup_error: OSError | None = None
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError as cleanup_exc:
                cleanup_error = cleanup_exc
            if cleanup_error is not None:
                last_error = OSError(
                    f"{exc}；下载临时文件清理失败：{cleanup_error}"
                )
            if attempt < retries:
                time.sleep(min(0.25 * (attempt + 1), 1.0))

    raise DatasetDownloadError(
        f"下载 Hugging Face 数据集失败：{dataset_id}/{filename}: {last_error}"
    ) from last_error
