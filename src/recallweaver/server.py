"""Asynchronous FastAPI service for RecallWeaver and DeepSeek."""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Query, Request
from openai import AsyncOpenAI, OpenAIError
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from recallweaver.api import RecallWeaverAPI
from recallweaver.errors import DatabaseError, ValidationError
from recallweaver.models import MemoryOut
from recallweaver.observability.logging import get_logger, get_trace_id

logger = get_logger(__name__)

_ALLERGY_PATTERN = re.compile(
    r"(?:我|本人)?对(?P<item>[^，。！？,.!?;；\s]+)过敏"
)
_RESIDENCE_PATTERN = re.compile(
    r"(?:我)?(?:以前|现在|最近)?(?:住在|搬到了|搬到|搬去了|搬去|迁往|迁到)"
    r"(?P<place>[^，。！？,.!?;；\s]+)"
)
_SYSTEM_PROMPT = """你是一个拥有长期记忆的私人助手。
以下是你记得关于用户的事实：
{recalled_memories}
请结合上述记忆回答用户。若无相关记忆，请直接回答。"""


class ServerSettings(BaseSettings):
    """Environment-backed settings used by the HTTP service."""

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )

    deepseek_api_key: str = Field(
        default="",
        validation_alias="DEEPSEEK_API_KEY",
    )
    db_path: str = Field(
        default="recallweaver.db",
        validation_alias="RECALLWEAVER_DB_PATH",
    )
    deepseek_base_url: str = "https://api.deepseek.com"
    request_timeout_seconds: float = Field(default=30.0, gt=0, le=300)


class _NonEmptyRequest(BaseModel):
    """Shared strict input handling for the service's JSON request models."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("*", mode="before")
    @classmethod
    def reject_blank_strings(cls, value: object) -> object:
        """Reject blank strings rather than treating them as useful input."""
        if isinstance(value, str) and not value.strip():
            raise ValueError("值不能为空")
        return value


class ChatRequest(_NonEmptyRequest):
    """Chat message and tenant identity supplied by a client."""

    user_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=10_000)


class ChatResponse(BaseModel):
    """Reply, recalled context, and processing time for a chat request."""

    reply: str
    recalled_facts: list[str]
    latency_ms: float


class MemoryAddRequest(_NonEmptyRequest):
    """Manual text-memory write request."""

    user_id: str = Field(default="default", min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=10_000)


class MemoryAddResponse(BaseModel):
    """Identifier of a newly stored text memory."""

    memory_id: str


class MemorySearchResponse(BaseModel):
    """Debug search response with trace metadata."""

    trace_id: str
    results: list[MemoryOut]


def _extract_explicit_facts(message: str) -> list[tuple[str, str]]:
    """Extract only directly stated allergy and residence facts.

    Args:
        message: User-provided message text.

    Returns:
        Predicate-object facts. The caller supplies the tenant-specific
        subject. Ambiguous references such as "I moved" without a destination
        are deliberately ignored.
    """
    facts: list[tuple[str, str]] = []
    for match in _ALLERGY_PATTERN.finditer(message):
        facts.append(("过敏", match.group("item")))
    for match in _RESIDENCE_PATTERN.finditer(message):
        facts.append(("住在", match.group("place")))
    return facts


def _memory_text(memory: MemoryOut) -> str:
    """Convert a text or graph recall result into concise prompt context."""
    if memory.content:
        return memory.content
    parts = (memory.subject, memory.predicate, memory.object)
    return " ".join(part for part in parts if part)


def create_app(
    *,
    api: RecallWeaverAPI | None = None,
    openai_client: Any | None = None,
    service_settings: ServerSettings | None = None,
) -> FastAPI:
    """Create the service app with reusable API and OpenAI dependencies.

    Args:
        api: Optional existing memory API. When omitted, the app creates one
            during lifespan startup.
        openai_client: Optional async OpenAI-compatible client, typically
            injected by tests. A provided client remains caller-owned.
        service_settings: Optional settings object for dependency injection.

    Returns:
        A configured FastAPI application.
    """
    selected_settings = service_settings or ServerSettings()
    owns_openai_client = openai_client is None

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        """Initialize shared resources once and close owned resources."""
        application.state.recallweaver_api = api or RecallWeaverAPI(
            selected_settings.db_path
        )
        application.state.openai_client = openai_client
        if (
            application.state.openai_client is None
            and selected_settings.deepseek_api_key.strip()
        ):
            application.state.openai_client = AsyncOpenAI(
                api_key=selected_settings.deepseek_api_key.strip(),
                base_url=selected_settings.deepseek_base_url,
                timeout=selected_settings.request_timeout_seconds,
                max_retries=2,
            )
        try:
            yield
        finally:
            if owns_openai_client and application.state.openai_client is not None:
                await application.state.openai_client.close()

    application = FastAPI(
        title="RecallWeaver API",
        version="1.0.0",
        description="Long-term memory and DeepSeek chat service.",
        lifespan=lifespan,
    )
    application.state.logger = logger

    @application.get("/health")
    async def health_check() -> dict[str, str]:
        """Return a lightweight liveness response."""
        return {"status": "ok"}

    @application.middleware("http")
    async def add_trace_id(request: Request, call_next: Any) -> Any:
        """Attach a request-scoped trace ID to logs and response headers."""
        from recallweaver.observability.logging import trace_context

        with trace_context() as trace_id:
            logger.info(
                "HTTP request received",
                extra={
                    "action": "http_request",
                    "details": {
                        "method": request.method,
                        "path": request.url.path,
                    },
                },
            )
            response = await call_next(request)
            response.headers["X-Trace-ID"] = trace_id
            return response

    @application.exception_handler(DatabaseError)
    async def database_exception_handler(
        request: Request,
        exc: DatabaseError,
    ) -> Any:
        """Log storage failures and return a non-sensitive service error."""
        logger.error(
            "RecallWeaver database operation failed",
            exc_info=(type(exc), exc, exc.__traceback__),
            extra={
                "action": "database_error",
                "details": {"path": request.url.path},
            },
        )
        return _error_response(
            status_code=503,
            message="Memory storage is temporarily unavailable.",
        )

    @application.exception_handler(ValidationError)
    async def recallweaver_validation_exception_handler(
        request: Request,
        exc: ValidationError,
    ) -> Any:
        """Translate underlying RecallWeaver input errors into HTTP 422."""
        logger.warning(
            "RecallWeaver rejected an operation",
            extra={
                "action": "validation_error",
                "details": {"path": request.url.path},
            },
        )
        return _error_response(status_code=422, message=str(exc))

    @application.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request,
        exc: Exception,
    ) -> Any:
        """Log unexpected failures while avoiding internal detail disclosure."""
        logger.error(
            "Unhandled service exception",
            exc_info=(type(exc), exc, exc.__traceback__),
            extra={
                "action": "unhandled_exception",
                "details": {
                    "path": request.url.path,
                    "error_type": type(exc).__name__,
                },
            },
        )
        return _error_response(
            status_code=500,
            message="An internal service error occurred.",
        )

    @application.post("/api/v1/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest, http_request: Request) -> ChatResponse:
        """Recall tenant facts, persist the turn, and request a DeepSeek reply."""
        started_at = time.perf_counter()
        trace_id = get_trace_id()
        tenant_id = request.user_id
        logger.info(
            "Chat request accepted",
            extra={
                "action": "chat_start",
                "details": {"user_id": tenant_id, "trace_id": trace_id},
            },
        )
        memory_api: RecallWeaverAPI = http_request.app.state.recallweaver_api
        client: AsyncOpenAI | None = http_request.app.state.openai_client

        await asyncio.to_thread(
            memory_api.add_memory,
            request.message,
            tenant_id,
        )
        current_facts: list[str] = []
        for predicate, object_ in _extract_explicit_facts(request.message):
            await asyncio.to_thread(
                memory_api.remember_triple,
                tenant_id,
                predicate,
                object_,
                tenant_id,
            )
            current_facts.append(f"{tenant_id} {predicate} {object_}")

        recalled = await asyncio.to_thread(
            memory_api.recall,
            request.message,
            3,
            tenant_id,
        )
        recalled_facts = list(
            dict.fromkeys(
                [
                    text
                    for item in recalled
                    if (text := _memory_text(item))
                ]
                + current_facts
            )
        )

        if client is None:
            logger.error(
                "DeepSeek client is not configured",
                extra={
                    "action": "deepseek_not_configured",
                    "details": {"trace_id": trace_id},
                },
            )
            raise HTTPException(
                status_code=503,
                detail="DeepSeek API is not configured.",
            )

        system_prompt = _SYSTEM_PROMPT.format(
            recalled_memories=(
                "\n".join(f"- {fact}" for fact in recalled_facts)
                if recalled_facts
                else "(暂无相关记忆)"
            )
        )
        try:
            completion = await client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": request.message},
                ],
                stream=False,
                timeout=selected_settings.request_timeout_seconds,
            )
        except OpenAIError as exc:
            logger.error(
                "DeepSeek request failed",
                exc_info=(type(exc), exc, exc.__traceback__),
                extra={
                    "action": "deepseek_error",
                    "details": {"error_type": type(exc).__name__},
                },
            )
            raise HTTPException(
                status_code=500,
                detail="The language model is temporarily unavailable.",
            ) from exc

        reply = completion.choices[0].message.content
        if not isinstance(reply, str):
            logger.error(
                "DeepSeek returned an empty or invalid reply",
                extra={"action": "deepseek_empty_reply", "details": {}},
            )
            raise HTTPException(
                status_code=500,
                detail="The language model returned an invalid response.",
            )

        latency_ms = (time.perf_counter() - started_at) * 1_000
        logger.info(
            "Chat request completed",
            extra={
                "action": "chat_complete",
                "details": {
                    "latency_ms": round(latency_ms, 3),
                    "recalled_count": len(recalled_facts),
                },
            },
        )
        return ChatResponse(
            reply=reply,
            recalled_facts=recalled_facts,
            latency_ms=latency_ms,
        )

    @application.get(
        "/api/v1/memory/search",
        response_model=MemorySearchResponse,
    )
    async def search_memory(
        http_request: Request,
        query: Annotated[str, Query(min_length=1, max_length=10_000)],
        user_id: Annotated[str, Query(min_length=1, max_length=128)] = "default",
        limit: Annotated[int, Query(ge=1, le=100)] = 10,
    ) -> MemorySearchResponse:
        """Return ranked memory matches for debugging and inspection."""
        normalized_query = query.strip()
        if not normalized_query:
            raise HTTPException(status_code=422, detail="query must not be blank")
        trace_id = get_trace_id()
        logger.info(
            "Memory search requested",
            extra={
                "action": "memory_search",
                "details": {
                    "user_id": user_id,
                    "query": normalized_query,
                    "trace_id": trace_id,
                },
            },
        )
        memory_api: RecallWeaverAPI = http_request.app.state.recallweaver_api
        results = await asyncio.to_thread(
            memory_api.recall,
            normalized_query,
            limit,
            user_id,
        )
        return MemorySearchResponse(trace_id=trace_id, results=results)

    @application.post(
        "/api/v1/memory/add",
        response_model=MemoryAddResponse,
    )
    async def add_memory(
        request: MemoryAddRequest,
        http_request: Request,
    ) -> MemoryAddResponse:
        """Persist a client-supplied text memory in its tenant namespace."""
        trace_id = get_trace_id()
        logger.info(
            "Manual memory write requested",
            extra={
                "action": "memory_add",
                "details": {
                    "user_id": request.user_id,
                    "trace_id": trace_id,
                },
            },
        )
        memory_api: RecallWeaverAPI = http_request.app.state.recallweaver_api
        memory_id = await asyncio.to_thread(
            memory_api.add_memory,
            request.content,
            request.user_id,
        )
        return MemoryAddResponse(memory_id=memory_id)

    return application


def _error_response(*, status_code: int, message: str) -> Any:
    """Build a consistent JSON error response with the request trace ID."""
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=status_code,
        content={
            "detail": message,
            "trace_id": get_trace_id(),
        },
    )


app = create_app()
