"""Rich-enhanced Click command-line interface for RecallWeaver."""

import click
from rich.console import Console
from rich.panel import Panel
from rich.style import Style
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from recallweaver.api import RecallWeaverAPI
from recallweaver.config import settings
from recallweaver.errors import DatabaseError, StorageError, ValidationError

console = Console()


def _service() -> RecallWeaverAPI:
    """Create the API service using the configured database path.

    Returns:
        An initialized API instance.
    """
    return RecallWeaverAPI(settings.db_path)


def _fail_with_code(error: Exception) -> None:
    """Print a stable CLI error code and exit unsuccessfully.

    Args:
        error: A translated public API exception.

    Raises:
        click.exceptions.Exit: Always, with exit status one.
    """
    if isinstance(error, ValidationError):
        error_code = "RW-VALIDATION"
    else:
        error_code = "RW-DATABASE"
    click.echo(f"Error [{error_code}]: {error}", err=True)
    raise click.exceptions.Exit(1)


def _current_fact_id(
    api: RecallWeaverAPI,
    subject: str,
    predicate: str,
    object_: str,
) -> str:
    """Fetch the identifier of a just-written current graph fact.

    Args:
        api: Initialized API whose database contains the fact.
        subject: Subject entity name.
        predicate: Fact predicate.
        object_: Object entity name.

    Returns:
        The current graph edge identifier.

    Raises:
        DatabaseError: If the written current edge cannot be found.
    """
    try:
        with api.database_manager.get_connection() as connection:
            row = connection.execute(
                """
                SELECT edge.id
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
                  AND object.name = ?
                  AND edge.valid_to IS NULL
                ORDER BY edge.valid_from DESC
                LIMIT 1
                """,
                ("default", subject, predicate, object_),
            ).fetchone()
    except StorageError as exc:
        raise DatabaseError(f"读取新事实 ID 失败：{exc}") from exc
    if row is None:
        raise DatabaseError("事实已写入，但未找到对应的当前有效记录")
    return str(row["id"])


@click.group()
def cli() -> None:
    """Manage local memories, graph facts, and temporal history."""


@cli.command("add")
@click.argument("triple", nargs=-1, required=True)
def add_command(triple: tuple[str, ...]) -> None:
    """Store a graph fact from SUBJECT PREDICATE OBJECT.

    OBJECT accepts multiple whitespace-separated words. A quoted single
    argument such as ``"张三 认识 李四"`` is also accepted.
    """
    parts = " ".join(triple).split(maxsplit=2)
    if len(parts) != 3:
        _fail_with_code(ValidationError("请提供主语、谓词和宾语"))

    try:
        api = _service()
        with console.status(
            "正在写入记忆...",
            spinner="dots",
            spinner_style="blue",
        ):
            if not api.remember_triple(*parts):
                raise DatabaseError("事实未能写入数据库")
            fact_id = _current_fact_id(api, *parts)
    except ValidationError as exc:
        _fail_with_code(exc)
    except DatabaseError as exc:
        _fail_with_code(exc)

    console.print(
        f"✅ 成功: 记忆已写入，ID: {fact_id}",
        style="green",
    )
    click.echo("事实已保存")


@cli.command("recall")
@click.argument("query")
@click.option("--limit", type=int, default=5, show_default=True)
def recall_command(query: str, limit: int) -> None:
    """Search text memories and graph paths for QUERY."""
    try:
        with console.status(
            "⚡ 正在扫描时空图谱...",
            spinner="dots",
            spinner_style="blue",
        ):
            results = _service().recall(query, limit=limit)
    except ValidationError as exc:
        _fail_with_code(exc)
    except DatabaseError as exc:
        _fail_with_code(exc)

    table = Table(title="RecallWeaver 记忆检索结果")
    table.add_column("得分(渐变)", justify="right")
    table.add_column("Trace ID", style="bright_blue")
    table.add_column("记忆内容", style="white", overflow="fold")
    table.add_column("生效时间", style="magenta")
    for result in results:
        content = result.content
        if not content:
            content = " ".join(
                str(part)
                for part in (result.subject, result.predicate, result.object)
                if part
            )
        normalized_score = min(max(result.score, 0.0), 1.0)
        red = round(255 * (1.0 - normalized_score))
        green = round(180 * normalized_score + 40)
        table.add_row(
            Text(
                f"{result.score:.3f}",
                style=Style(color=f"rgb({red},{green},40)"),
            ),
            result.trace_id or "-",
            content,
            str(result.valid_from or "-"),
        )
    console.print(table)


@cli.command("history")
@click.argument("subject")
@click.argument("predicate")
def history_command(subject: str, predicate: str) -> None:
    """Show every known version for SUBJECT and PREDICATE."""
    try:
        history = _service().get_history(subject, predicate)
    except ValidationError as exc:
        _fail_with_code(exc)
    except DatabaseError as exc:
        _fail_with_code(exc)

    if not history:
        console.print("未找到事实历史")
        return

    tree = Tree(f"🧭 {subject} · {predicate}")
    for fact in history:
        state = (
            Text("[❌ 失效]", style="red")
            if fact["valid_to"] is not None
            else Text("[✅ 有效]", style="green")
        )
        line = Text()
        line.append_text(state)
        line.append(
            f" {fact['object']} | valid_from={fact['valid_from']} "
            f"| valid_to={fact['valid_to']}"
        )
        tree.add(line)
    console.print(Panel(tree, title="事实时间线", border_style="cyan"))


# Keep the prior command spelling as a compatibility alias.
cli.add_command(add_command, name="remember")


def main() -> None:
    """Run the Click command group as a Python module."""
    cli()


if __name__ == "__main__":
    main()
