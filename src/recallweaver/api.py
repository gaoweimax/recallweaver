"""依赖注入式 RecallWeaver API 与 Pydantic 契约模型。"""

from typing import Any, NoReturn, TypeVar

from pydantic import BaseModel, ValidationError as PydanticValidationError

from recallweaver.config import settings
from recallweaver.db import Database
from recallweaver.decay_engine import DecayEngine
from recallweaver.errors import DatabaseError, ValidationError
from recallweaver.graph import GraphManager
from recallweaver.memory_manager import MemoryManager
from recallweaver.models import (
    DatabasePathIn,
    HistoryIn,
    HistoryOut,
    MemoryIdOut,
    MemoryOut,
    RecallIn,
    SuccessOut,
    TextMemoryIn,
    TripleIn,
)
from recallweaver.retrieval import Retriever

ModelT = TypeVar("ModelT", bound=BaseModel)


def _validate_input(model_type: type[ModelT], **values: Any) -> ModelT:
    """Validate an input model and translate Pydantic errors to API errors.

    Args:
        model_type: Pydantic model class used to validate the input.
        **values: Input fields passed to the model.

    Returns:
        A validated instance of ``model_type``.

    Raises:
        ValidationError: If any input value violates the API contract.
    """
    try:
        return model_type.model_validate(values)
    except PydanticValidationError as exc:
        raise ValidationError(str(exc)) from exc


def _raise_database_error(operation: str, exc: Exception) -> NoReturn:
    """Translate lower-level storage exceptions at the public API boundary.

    Args:
        operation: Human-readable operation name for the error message.
        exc: The exception raised by an injected component.

    Raises:
        DatabaseError: Always, with the original exception chained.
    """
    if isinstance(exc, DatabaseError):
        raise exc
    raise DatabaseError(f"{operation} failed: {exc}") from exc


class RecallWeaverAPI:
    """Expose validated memory, graph, hybrid-recall, and history operations.

    Args:
        db_path: Filesystem path of the SQLite database to use.

    All engines share the injected database manager so a single API instance
    never reads from or writes to the process-global database by accident.
    """

    def __init__(self, db_path: str) -> None:
        """Create and initialize all engines for one SQLite database.

        Args:
            db_path: Path to the database file.

        Raises:
            DatabaseError: If the database cannot be initialized.
            ValidationError: If ``db_path`` is empty.
        """
        database_path = _validate_input(DatabasePathIn, db_path=db_path)
        self.database_manager = Database(database_path.db_path)
        self.decay_engine = DecayEngine()
        self.memory_manager = MemoryManager(database=self.database_manager)
        self.graph_manager = GraphManager(database=self.database_manager)
        self.retriever = Retriever(
            database=self.database_manager,
            decay_engine=self.decay_engine,
        )
        try:
            self.database_manager.init_db(verbose=False)
        except Exception as exc:
            _raise_database_error("database initialization", exc)

    def remember_triple(
        self,
        subject: str,
        predicate: str,
        object_: str,
        tenant_id: str = "default",
    ) -> bool:
        """Insert or resolve a time-versioned graph fact.

        Args:
            subject: Entity that owns the fact.
            predicate: Relationship name.
            object_: Related entity or value.
            tenant_id: Tenant namespace for all created records.

        Returns:
            ``True`` when the fact is stored or is already current.

        Raises:
            ValidationError: If a fact field or tenant ID is empty or invalid.
            DatabaseError: If persistence or conflict resolution fails.
        """
        request = _validate_input(
            TripleIn,
            subject=subject,
            predicate=predicate,
            object_=object_,
            tenant_id=tenant_id,
        )
        try:
            result = self.memory_manager.remember_with_conflict_resolution(
                subject=request.subject,
                predicate=request.predicate,
                object_=request.object_,
                tenant_id=request.tenant_id,
            )
            return SuccessOut(success=result).success
        except PydanticValidationError as exc:
            raise ValidationError(str(exc)) from exc
        except Exception as exc:
            _raise_database_error("remember triple", exc)

    def add_memory(
        self,
        content: str,
        tenant_id: str = "default",
    ) -> str:
        """Persist validated plain text without creating graph edges.

        Args:
            content: Text content to store.
            tenant_id: Tenant namespace for the memory.

        Returns:
            The unique ID assigned to the new memory.

        Raises:
            ValidationError: If content or tenant ID is empty or invalid.
            DatabaseError: If the memory cannot be persisted.
        """
        request = _validate_input(
            TextMemoryIn,
            content=content,
            tenant_id=tenant_id,
        )
        try:
            memory_id = self.memory_manager.remember(
                request.content,
                tenant_id=request.tenant_id,
            )
            return MemoryIdOut(memory_id=memory_id).memory_id
        except PydanticValidationError as exc:
            raise ValidationError(str(exc)) from exc
        except Exception as exc:
            _raise_database_error("add memory", exc)

    def recall(
        self,
        query: str,
        limit: int = 5,
        tenant_id: str = "default",
    ) -> list[MemoryOut]:
        """Merge text and graph recall, validate, deduplicate, and rank results.

        Args:
            query: Text query or exact graph entity name.
            limit: Maximum number of returned results; must be non-negative.
            tenant_id: Tenant namespace to search.

        Returns:
            Results as validated ``MemoryOut`` Pydantic models, sorted by
            current decay score in descending order.

        Raises:
            ValidationError: If query, limit, or tenant ID is invalid.
            DatabaseError: If any retrieval or scoring operation fails.
        """
        request = _validate_input(
            RecallIn,
            query=query,
            limit=limit,
            tenant_id=tenant_id,
        )
        if request.limit == 0:
            return []

        try:
            text_rows = self.retriever.search(
                request.query,
                request.limit,
                tenant_id=request.tenant_id,
            )
            graph_rows = self.graph_manager.query_multi_hop(
                request.query,
                tenant_id=request.tenant_id,
            )

            results: list[MemoryOut] = []
            seen_memory_ids: set[str] = set()
            seen_graph_paths: set[tuple[Any, ...]] = set()

            for row in text_rows:
                memory_id = str(row["id"])
                if memory_id in seen_memory_ids:
                    continue
                seen_memory_ids.add(memory_id)
                score = self.decay_engine.calculate_score(
                    base_weight=float(row["base_weight"]),
                    decay_lambda=float(row["decay_lambda"]),
                    last_decay_at=int(row["last_decay_at"]),
                    retrieval_count=int(row["retrieval_count"]),
                )
                results.append(
                    MemoryOut(
                        memory_id=memory_id,
                        result_type="memory",
                        content=str(row["content"]),
                        tenant_id=request.tenant_id,
                        score=score,
                        valid_from=row["valid_from"],
                        valid_to=row["valid_to"],
                        created_at=int(row["created_at"]),
                    )
                )

            for row in graph_rows:
                memory_id_value = row.get("memory_id")
                memory_id = str(memory_id_value) if memory_id_value else None
                if memory_id is not None:
                    if memory_id in seen_memory_ids:
                        continue
                    seen_memory_ids.add(memory_id)
                    memory = self.memory_manager.get_memory(memory_id)
                    score = self.decay_engine.calculate_score(
                        base_weight=float(memory["base_weight"]),
                        decay_lambda=float(memory["decay_lambda"]),
                        last_decay_at=int(memory["last_decay_at"]),
                        retrieval_count=int(memory["retrieval_count"]),
                    )
                    created_at = int(memory["created_at"])
                else:
                    graph_key = (
                        row.get("start_id"),
                        row.get("entity_id"),
                        row.get("relation"),
                        row.get("depth"),
                    )
                    if graph_key in seen_graph_paths:
                        continue
                    seen_graph_paths.add(graph_key)
                    score = 0.0
                    created_at = None

                results.append(
                    MemoryOut(
                        memory_id=memory_id,
                        result_type="graph",
                        subject=row.get("start_name"),
                        predicate=row.get("relation"),
                        object=row.get("entity_name"),
                        entity_name=row.get("entity_name"),
                        relation=row.get("relation"),
                        depth=row.get("depth"),
                        tenant_id=request.tenant_id,
                        score=score,
                        valid_from=row.get("valid_from"),
                        created_at=created_at,
                    )
                )

            results.sort(key=lambda result: result.score, reverse=True)
            return results[: request.limit]
        except PydanticValidationError as exc:
            raise ValidationError(str(exc)) from exc
        except Exception as exc:
            _raise_database_error("recall", exc)

    def get_history(self, subject: str, predicate: str) -> list[dict[str, Any]]:
        """Return all current and expired versions of a subject-predicate fact.

        Args:
            subject: Subject entity name.
            predicate: Relationship name.

        Returns:
            Dictionaries containing the object and both validity timestamps.

        Raises:
            ValidationError: If subject or predicate is empty.
            DatabaseError: If the history query fails.
        """
        request = _validate_input(
            HistoryIn,
            subject=subject,
            predicate=predicate,
        )
        try:
            with self.database_manager.get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT edge.id, edge.tenant_id, edge.subject_id,
                           subject.name AS subject, edge.predicate,
                           edge.object_id, object.name AS object,
                           edge.valid_from, edge.valid_to, edge.confidence,
                           edge.memory_id, edge.created_at
                    FROM edges AS edge
                    JOIN entities AS subject
                      ON subject.id = edge.subject_id
                     AND subject.tenant_id = edge.tenant_id
                    JOIN entities AS object
                      ON object.id = edge.object_id
                     AND object.tenant_id = edge.tenant_id
                    WHERE edge.tenant_id = ?
                      AND subject.name = ?
                      AND edge.predicate = ?
                    ORDER BY edge.valid_from, edge.created_at, edge.id
                    """,
                    ("default", request.subject, request.predicate),
                ).fetchall()
            history = [
                HistoryOut.model_validate(dict(row)).model_dump()
                for row in rows
            ]
            return history
        except PydanticValidationError as exc:
            raise ValidationError(str(exc)) from exc
        except Exception as exc:
            _raise_database_error("get history", exc)


RecallWeaver = RecallWeaverAPI

_default_instance: RecallWeaverAPI | None = None


def _get_default_instance() -> RecallWeaverAPI:
    """Return the lazily initialized default API for legacy function callers.

    Returns:
        The singleton API connected to the configured default database.
    """
    global _default_instance
    if _default_instance is None:
        _default_instance = RecallWeaverAPI(settings.db_path)
    return _default_instance


def remember(content: str, base_weight: float = 1.0) -> str:
    """Persist plain text through the legacy module-level function.

    Args:
        content: Text memory to persist.
        base_weight: Base importance weight.

    Returns:
        The generated memory identifier.
    """
    try:
        request = TextMemoryIn(content=content)
        return _get_default_instance().memory_manager.remember(
            request.content,
            base_weight=base_weight,
        )
    except PydanticValidationError as exc:
        raise ValidationError(str(exc)) from exc
    except (ValidationError, DatabaseError):
        raise
    except Exception as exc:
        _raise_database_error("remember", exc)


def recall(
    query: str,
    limit: int = 5,
) -> list[MemoryOut]:
    """Search the configured default database through the legacy function.

    Args:
        query: Search term or entity name.
        limit: Maximum number of results.

    Returns:
        Validated, ranked memory and graph results.
    """
    return _get_default_instance().recall(query, limit)


__all__ = ["MemoryOut", "RecallWeaver", "RecallWeaverAPI", "recall", "remember"]
