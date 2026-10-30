"""Click-based command-line interface for RecallWeaver."""

import json

import click

from recallweaver.api import RecallWeaverAPI
from recallweaver.config import settings
from recallweaver.errors import DatabaseError, ValidationError


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
        if not _service().remember_triple(*parts):
            raise DatabaseError("事实未能写入数据库")
    except ValidationError as exc:
        _fail_with_code(exc)
    except DatabaseError as exc:
        _fail_with_code(exc)

    click.echo("事实已保存")


@cli.command("recall")
@click.argument("query")
@click.option("--limit", type=int, default=5, show_default=True)
def recall_command(query: str, limit: int) -> None:
    """Search text memories and graph paths for QUERY."""
    try:
        results = _service().recall(query, limit=limit)
    except ValidationError as exc:
        _fail_with_code(exc)
    except DatabaseError as exc:
        _fail_with_code(exc)

    click.echo(
        json.dumps(
            [result.model_dump(mode="json") for result in results],
            ensure_ascii=False,
            indent=2,
        )
    )


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
        click.echo("未找到事实历史")
        return

    for fact in history:
        state = "[已失效]" if fact["valid_to"] is not None else "[当前有效]"
        click.echo(
            f"{state} {fact['subject']} {fact['predicate']} {fact['object']} "
            f"| valid_from={fact['valid_from']} | valid_to={fact['valid_to']}"
        )


# Keep the prior command spelling as a compatibility alias.
cli.add_command(add_command, name="remember")


def main() -> None:
    """Run the Click command group as a Python module."""
    cli()


if __name__ == "__main__":
    main()
