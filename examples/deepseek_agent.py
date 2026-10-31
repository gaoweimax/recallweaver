"""Demonstrate a DeepSeek chat agent grounded in RecallWeaver memory.

The example stores each utterance, extracts a small set of personal facts with
rules, recalls filtered memories, and then sends a context-rich prompt to
DeepSeek. When no API key is configured or a provider request fails, a
deterministic local response keeps the example usable without a network call.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
import unicodedata
from pathlib import Path

from openai import OpenAI, OpenAIError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from recallweaver.api import RecallWeaverAPI

SYSTEM_PROMPT_TEMPLATE = """你是一个拥有长期记忆的私人助手。以下是你记得关于用户的事实：
{recalled_memories}
请结合上述记忆回答用户。若无相关记忆，请直接回答。"""

_ALLERGY_PATTERN = re.compile(
    r"(?:我|本人)?对(?P<item>[^，。！？,.!?;；\s]+)过敏"
)
_RESIDENCE_PATTERN = re.compile(
    r"(?:我|本人)?住在(?P<location>[^，。！？,.!?;；\s]+)"
)
_FOOD_REQUEST_KEYWORDS = ("零食", "食物", "吃什么", "推荐吃")


class AgentInputError(ValueError):
    """Raised when an incoming user message violates the demo input contract."""


class AgentProviderError(RuntimeError):
    """Raised for malformed or unusable responses from the language provider."""


class AgentConfigurationError(ValueError):
    """Raised when injected agent configuration has an invalid runtime type."""


class ChatInput(BaseModel):
    """Validated shape and safety limits for one user message.

    The example accepts ordinary Unicode text but rejects blank input, terminal
    control characters, and excessively long messages before touching storage
    or making an external request.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    user_input: str = Field(min_length=1, max_length=4000)

    @field_validator("user_input")
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        """Reject control characters that could corrupt logs or prompt output.

        Args:
            value: Whitespace-trimmed user text from the request model.

        Returns:
            The validated user text.

        Raises:
            ValueError: If the text contains a control character other than
                newline or tab.
        """
        if any(
            unicodedata.category(character) == "Cc"
            and character not in {"\n", "\t"}
            for character in value
        ):
            raise ValueError("用户输入不能包含非法控制字符")
        return value


class PersonalFact(BaseModel):
    """Pydantic-validated fact extracted from a user utterance."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    subject: str = Field(min_length=1, max_length=100)
    predicate: str = Field(min_length=1, max_length=100)
    object_: str = Field(min_length=1, max_length=300)


class ProviderReply(BaseModel):
    """Non-empty assistant response accepted from the DeepSeek API."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    content: str = Field(min_length=1, max_length=12000)


class AgentConfiguration(BaseModel):
    """Validated provider key configuration; an absent key enables fallback."""

    model_config = ConfigDict(strict=True, extra="forbid")

    api_key: str | None = Field(default=None, max_length=1024)

    @field_validator("api_key")
    @classmethod
    def normalize_api_key(cls, value: str | None) -> str | None:
        """Normalize an optional key and reject unsafe control characters.

        Args:
            value: Explicit key or value read from ``DEEPSEEK_API_KEY``.

        Returns:
            A trimmed key, or ``None`` for absent/blank configuration.

        Raises:
            ValueError: If the key contains a control character.
        """
        if value is None:
            return None
        normalized_value = value.strip()
        if not normalized_value:
            return None
        if any(unicodedata.category(character) == "Cc" for character in value):
            raise ValueError("DEEPSEEK_API_KEY 不能包含控制字符")
        return normalized_value


class DeepSeekAgent:
    """Connect DeepSeek chat completion to persistent RecallWeaver memory.

    Args:
        api: Initialized RecallWeaver API used to store and recall memories.
        api_key: Optional DeepSeek key. If omitted, the agent reads
            ``DEEPSEEK_API_KEY`` from the process environment.
        client: Optional OpenAI-compatible client, useful for controlled tests.

    Notes:
        DeepSeek's OpenAI-compatible endpoint is configured with a 30-second
        timeout and two automatic retries. A missing key or provider failure
        uses a local fallback answer instead of terminating the demo.
    """

    def __init__(
        self,
        api: RecallWeaverAPI,
        api_key: str | None = None,
        client: OpenAI | None = None,
    ) -> None:
        """Initialize the provider client and retain the injected memory API.

        Args:
            api: Initialized API instance; it must point at the desired
                RecallWeaver database.
            api_key: DeepSeek API key. Environment configuration is used when
                this argument is omitted.
            client: Optional preconfigured client. When supplied, it replaces
                construction of a client from ``api_key``.

        Raises:
            AgentConfigurationError: If ``api`` or ``api_key`` has an invalid
                runtime type.
        """
        if not isinstance(api, RecallWeaverAPI):
            raise AgentConfigurationError("api 必须是 RecallWeaverAPI 实例")

        self.api = api
        configured_api_key = (
            api_key if api_key is not None else os.getenv("DEEPSEEK_API_KEY")
        )
        try:
            resolved_api_key = AgentConfiguration(
                api_key=configured_api_key
            ).api_key
        except ValidationError as exc:
            raise AgentConfigurationError(
                f"DEEPSEEK_API_KEY 配置无效：{exc}"
            ) from exc
        self.client = client
        if self.client is None and resolved_api_key and resolved_api_key.strip():
            self.client = OpenAI(
                api_key=resolved_api_key,
                base_url="https://api.deepseek.com",
                timeout=30.0,
                max_retries=2,
            )

    @staticmethod
    def _extract_fact(user_input: str) -> PersonalFact | None:
        """Extract a supported personal fact using safe, deterministic rules.

        Args:
            user_input: Validated utterance supplied by the user.

        Returns:
            A validated allergy or residence fact, or ``None`` if neither
            pattern matches. Allergy facts take precedence when both match.

        Raises:
            ValidationError: If a matched value violates the fact model.
        """
        allergy_match = _ALLERGY_PATTERN.search(user_input)
        if allergy_match is not None:
            return PersonalFact(
                subject="用户",
                predicate="过敏",
                object_=allergy_match.group("item"),
            )

        residence_match = _RESIDENCE_PATTERN.search(user_input)
        if residence_match is not None:
            return PersonalFact(
                subject="用户",
                predicate="住在",
                object_=residence_match.group("location"),
            )
        return None

    @staticmethod
    def _is_food_request(user_input: str) -> bool:
        """Return whether the request appears to concern food or snacks.

        Args:
            user_input: Validated message to classify with simple keywords.

        Returns:
            ``True`` when a food-related keyword occurs in the message.
        """
        return any(keyword in user_input for keyword in _FOOD_REQUEST_KEYWORDS)

    def _recall_relevant_memories(
        self,
        user_input: str,
        extracted_fact: PersonalFact | None,
    ) -> list[str]:
        """Recall query matches and narrowly scoped personal graph facts.

        Args:
            user_input: Current user message, used as the primary recall query.
            extracted_fact: Fact just extracted from this message, if any.

        Returns:
            Human-readable memory lines suitable for the system prompt.

        Notes:
            The current utterance is stored as a raw episode, but it is omitted
            from its own prompt to avoid echoing transient chatter. For a food
            request, the graph is queried for the user's facts and only allergy
            relations are included as safety-relevant context.
        """
        # 依照演示流程先用原始用户输入查询，公开 API 会校验并过滤低分记忆。
        recalled = self.api.recall(user_input, limit=3)
        if extracted_fact is not None or self._is_food_request(user_input):
            recalled.extend(self.api.recall("用户", limit=3))

        memories: list[str] = []
        seen: set[str] = set()
        for memory in recalled:
            if memory.result_type == "graph":
                if (
                    self._is_food_request(user_input)
                    and memory.predicate != "过敏"
                ):
                    continue
                if not memory.subject or not memory.predicate or not memory.object:
                    continue
                rendered = (
                    f"- {memory.subject} {memory.predicate}：{memory.object}"
                )
            else:
                # 不将刚写入的原始对话再次作为事实塞回提示词。
                if not memory.content or memory.content.strip() == user_input:
                    continue
                rendered = f"- {memory.content}"

            if rendered not in seen:
                seen.add(rendered)
                memories.append(rendered)
        return memories

    @staticmethod
    def _fallback_response(
        user_input: str,
        recalled_memories: list[str],
    ) -> str:
        """Create a safe local response when the external service is unavailable.

        Args:
            user_input: Validated current user message.
            recalled_memories: Context already selected for the system prompt.

        Returns:
            A deterministic response that preserves relevant allergy context.
        """
        allergy = next(
            (
                memory.partition("：")[2]
                for memory in recalled_memories
                if " 过敏：" in memory
            ),
            None,
        )
        if allergy and DeepSeekAgent._is_food_request(user_input):
            return (
                f"我记得你对{allergy}过敏。可以考虑选择明确标注不含"
                f"{allergy}、且配料表清晰的零食；购买前请核对包装信息。"
            )
        return "我目前无法连接 DeepSeek，但已安全保存这条对话。请稍后再试。"

    def chat(self, user_input: str) -> str:
        """Store, recall, and answer one message using long-term context.

        Args:
            user_input: Non-empty user message of at most 4,000 characters.

        Returns:
            The DeepSeek answer, or a context-aware local fallback if the
            API key is absent or the provider request fails.

        Raises:
            AgentInputError: If the user input is blank, malformed, or contains
                forbidden control characters.
            ValidationError: If a matched fact cannot satisfy its Pydantic
                validation contract.
            RecallWeaver business exceptions: Storage/API errors are
                propagated with their explicit project exception types.
        """
        try:
            request = ChatInput(user_input=user_input)
        except ValidationError as exc:
            raise AgentInputError(f"用户输入无效：{exc}") from exc

        # 第一阶段保存原始话语；它不会自动成为系统提示词中的核心事实。
        self.api.add_memory(request.user_input)

        # 第二阶段只将规则明确识别出的长期个人事实写入图谱。
        fact = self._extract_fact(request.user_input)
        if fact is not None:
            self.api.remember_triple(
                subject=fact.subject,
                predicate=fact.predicate,
                object_=fact.object_,
            )

        # 第三阶段先按用户输入召回，再按任务需要补充相关的图谱事实。
        recalled_memories = self._recall_relevant_memories(
            request.user_input,
            fact,
        )
        recalled_text = "\n".join(recalled_memories)

        # 第四阶段严格使用长期记忆提示词模板。
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            recalled_memories=recalled_text
        )
        print(f"\n=== System Prompt ===\n{system_prompt}")
        print(f"\n=== User Input ===\n{request.user_input}")

        # 第五阶段请求 DeepSeek；SDK 自带有限重试，失败时回退到本地回复。
        if self.client is None:
            print("未配置 DEEPSEEK_API_KEY，使用本地安全回退回复。")
            answer = self._fallback_response(
                request.user_input,
                recalled_memories,
            )
        else:
            try:
                completion = self.client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": request.user_input},
                    ],
                    temperature=0.7,
                    max_tokens=1024,
                )
                if not completion.choices:
                    raise AgentProviderError("DeepSeek 返回了空 choices")
                answer = ProviderReply(
                    content=completion.choices[0].message.content
                ).content
            except (OpenAIError, AgentProviderError, ValidationError) as exc:
                print(f"DeepSeek 请求失败，已启用安全回退：{exc}")
                answer = self._fallback_response(
                    request.user_input,
                    recalled_memories,
                )

        print(f"\n=== Assistant ===\n{answer}")
        return answer


def main() -> None:
    """Run the requested stock-noise, allergy-fact, and snack-query script.

    A temporary database prevents demo data from altering the user's normal
    RecallWeaver database. Set ``DEEPSEEK_API_KEY`` to use the live service;
    otherwise, the local fallback still demonstrates the recalled context.
    """
    # Windows 终端可能使用本地代码页，显式 UTF-8 可避免中文提示词乱码。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    with tempfile.TemporaryDirectory(prefix="recallweaver-deepseek-") as directory:
        database_path = Path(directory) / "recallweaver-demo.db"
        api = RecallWeaverAPI(str(database_path))
        agent = DeepSeekAgent(api)

        for message in (
            "今天股票绿了",
            "我对花生过敏",
            "推荐点零食",
        ):
            agent.chat(message)


if __name__ == "__main__":
    main()
