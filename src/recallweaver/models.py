"""公开 API 的 Pydantic 输入与输出模型。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _NonEmptyInput(BaseModel):
    """所有公开写入和查询输入的共同校验规则。"""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def require_non_empty_strings(cls, value: object) -> object:
        """拒绝空白字符串，并避免把非字符串值隐式转换为文本。"""
        if isinstance(value, str) and not value.strip():
            raise ValueError("值不能为空")
        return value


class TripleIn(_NonEmptyInput):
    """需要写入图谱的主语、谓词、宾语及租户。"""

    subject: str
    predicate: str
    object_: str
    tenant_id: str = "default"


class TextMemoryIn(_NonEmptyInput):
    """需要持久化的纯文本记忆及其租户。"""

    content: str
    tenant_id: str = "default"


class RecallIn(_NonEmptyInput):
    """混合检索请求及返回记录上限。"""

    query: str
    limit: int = Field(default=5, ge=0)
    tenant_id: str = "default"


class HistoryIn(_NonEmptyInput):
    """事实历史查询的主语、谓词。"""

    subject: str
    predicate: str


class DatabasePathIn(_NonEmptyInput):
    """Filesystem path for the service database."""

    db_path: str


class MemoryIdOut(BaseModel):
    """Validated identifier returned after writing text memory."""

    memory_id: str


class SuccessOut(BaseModel):
    """Validated boolean result of a graph fact write."""

    success: bool


class MemoryOut(BaseModel):
    """文本记忆或图谱召回的规范化结果。"""

    model_config = ConfigDict(extra="forbid")

    memory_id: str | None = None
    result_type: Literal["memory", "graph"]
    content: str | None = None
    subject: str | None = None
    predicate: str | None = None
    object: str | None = None
    start_name: str | None = None
    entity_name: str | None = None
    relation: str | None = None
    depth: int | None = None
    tenant_id: str | None = None
    score: float
    valid_from: str | int | None = None
    valid_to: str | int | None = None
    created_at: int | None = None


class HistoryOut(BaseModel):
    """Validated row from the temporal fact-history query."""

    model_config = ConfigDict(extra="forbid")

    id: str
    tenant_id: str
    subject_id: str
    subject: str
    predicate: str
    object_id: str
    object: str
    valid_from: str
    valid_to: str | None = None
    confidence: float | None = None
    memory_id: str | None = None
    created_at: int
