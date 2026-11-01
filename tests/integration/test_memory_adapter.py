"""Tests for the framework-neutral Python memory adapter example."""

from pathlib import Path

from plugins.memory_adapter import MemoryPromptAdapter
from recallweaver import RecallWeaverAPI


def test_memory_adapter_scopes_prompt_memories_by_tenant(
    tmp_path: Path,
) -> None:
    api = RecallWeaverAPI(str(tmp_path / "memory-adapter.sqlite3"))
    adapter = MemoryPromptAdapter(api=api)
    adapter.remember("user-a", "用户住在杭州")
    adapter.remember("user-b", "用户住在上海")

    prompt = adapter.build_system_prompt("user-a", "用户住在哪里？")

    assert "杭州" in prompt
    assert "上海" not in prompt
