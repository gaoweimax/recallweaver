"""Integration tests for the DSH adapter and offline NAS startup checks."""

from pathlib import Path
from unittest.mock import patch

import pytest

from plugins.dsh_adapter import DSHMemoryAdapter
from recallweaver.api import RecallWeaverAPI
from scripts import start_nas


def test_process_message_persists_memory_and_returns_system_prompt(
    tmp_path: Path,
) -> None:
    """The DSH event entrypoint persists memory and returns a prompt string."""
    db_path = str(tmp_path / "dsh-adapter.sqlite3")
    api = RecallWeaverAPI(db_path)
    adapter = DSHMemoryAdapter(api=api)

    # This adapter only prepares memory context; it must not make model requests.
    with patch("recallweaver.server.AsyncOpenAI") as openai_client:
        prompt = adapter.on_message("user", "测试")

    with api.database_manager.get_connection() as connection:
        stored = connection.execute(
            """
            SELECT content, tenant_id
            FROM memories
            WHERE tenant_id = ?
            """,
            ("user",),
        ).fetchall()

    openai_client.assert_not_called()
    assert isinstance(prompt, str)
    assert len(stored) == 1
    assert stored[0]["content"] == "测试"
    assert "测试" in prompt
    assert "以下是你记得关于用户的事实" in prompt


def test_nas_missing_key_exits_cleanly_without_starting_server(
    monkeypatch, capsys,
) -> None:
    """Missing API key prints a red warning and exits before Uvicorn starts."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with (
        patch.object(start_nas, "console") as rich_console,
        patch.object(start_nas.subprocess, "run") as subprocess_run,
    ):
        with pytest.raises(SystemExit) as exit_info:
            start_nas.main()

    warning = rich_console.print.call_args.args[0]
    assert "[bold red]" in warning
    assert "未设置 DEEPSEEK_API_KEY" in warning
    assert exit_info.value.code == 1
    subprocess_run.assert_not_called()
    assert "Traceback" not in capsys.readouterr().err
