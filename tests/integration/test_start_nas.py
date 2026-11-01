"""Tests for the offline NAS startup check."""

from unittest.mock import patch

import pytest

from scripts import start_nas


def test_nas_missing_key_exits_cleanly_without_starting_server(
    monkeypatch, capsys,
) -> None:
    """Missing API key reports an error and exits before Uvicorn starts."""
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
