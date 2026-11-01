"""Framework-neutral example for adding RecallWeaver memories to a prompt."""

from recallweaver import RecallWeaverAPI


class MemoryPromptAdapter:
    """Save user-provided facts and build a prompt from relevant memories."""

    def __init__(
        self,
        db_path: str = "recallweaver.db",
        *,
        api: RecallWeaverAPI | None = None,
    ) -> None:
        self.api = api or RecallWeaverAPI(db_path)

    def remember(self, tenant_id: str, content: str) -> str:
        """Persist a memory for one user or agent."""
        return self.api.add_memory(content, tenant_id=tenant_id)

    def build_system_prompt(self, tenant_id: str, query: str) -> str:
        """Return a system-prompt section containing matching memories."""
        recalled = self.api.recall(query, limit=5, tenant_id=tenant_id)
        facts = list(
            dict.fromkeys(
                result.content
                or " ".join(
                    part
                    for part in (
                        result.subject,
                        result.predicate,
                        result.object,
                    )
                    if part
                )
                for result in recalled
            )
        )
        facts = [fact for fact in facts if fact]
        memory_context = (
            "\n".join(f"- {fact}" for fact in facts)
            if facts
            else "- No relevant memories found."
        )
        return (
            "Relevant long-term memories:\n"
            f"{memory_context}\n"
            "Use these memories only when relevant to the user's request."
        )
