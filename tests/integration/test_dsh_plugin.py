"""Verify that the Node.js DSH plugin can invoke the installed Python CLI."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from recallweaver.api import RecallWeaverAPI


PLUGIN_INDEX = (
    Path(__file__).resolve().parents[2]
    / "dsh-plugin-recallweaver"
    / "index.js"
)


def test_node_plugin_invokes_python_cli_recall(tmp_path: Path) -> None:
    """Node starts the Python CLI with a full Unicode query and returns results."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to exercise the DSH plugin bridge.")

    database_path = tmp_path / "dsh-plugin.sqlite3"
    memory = "大肥鱼的名字叫小明"
    RecallWeaverAPI(str(database_path)).add_memory(memory)

    script = (
        "const plugin = await import(process.env.RECALLWEAVER_PLUGIN_INDEX);"
        "process.stdout.write(plugin.recallWithCli("
        "process.env.RECALLWEAVER_TEST_QUERY));"
    )
    env = os.environ.copy()
    env.update(
        {
            "DB_PATH": str(database_path),
            "RECALLWEAVER_PLUGIN_INDEX": PLUGIN_INDEX.as_uri(),
            "RECALLWEAVER_PYTHON": sys.executable,
            "RECALLWEAVER_TEST_QUERY": memory,
        }
    )

    result = subprocess.run(
        [node, "--input-type=module", "-e", script],
        capture_output=True,
        check=False,
        encoding="utf-8",
        env=env,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "RecallWeaver 记忆检索结果" in result.stdout
    assert "小明" in result.stdout
