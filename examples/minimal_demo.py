"""Demonstrate extraction, temporal conflict resolution, and hybrid recall."""

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from recallweaver.api import RecallWeaverAPI
from recallweaver.config import settings
from recallweaver.extraction import LLMExtractor


def _mock_completion(content: str) -> SimpleNamespace:
    """Build the small response shape consumed by the OpenAI SDK client.

    Args:
        content: JSON text to return as the mocked assistant message.

    Returns:
        An object compatible with the extractor's response access pattern.
    """
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _extract_and_store(api: RecallWeaverAPI, extractor: LLMExtractor, text: str) -> None:
    """Extract facts from text and persist each fact through the public API.

    Args:
        api: Initialized RecallWeaver API.
        extractor: LLM extractor, real or mocked.
        text: User utterance to process.
    """
    triples = extractor.extract(text)
    if not triples:
        print(f"ℹ️ 未从输入中提取到事实：{text}")
        return

    for triple in triples:
        api.remember_triple(**triple)
        print(
            "🧩 已抽取并保存："
            f"{triple['subject']} {triple['predicate']} {triple['object_']}"
        )


def _print_history(api: RecallWeaverAPI) -> None:
    """Print the address timeline with current/expired labels.

    Args:
        api: Initialized RecallWeaver API.
    """
    print("\n🕰️ 张三的居住地时间线")
    for fact in api.get_history("张三", "住在"):
        state = "[已失效]" if fact["valid_to"] is not None else "[当前有效]"
        print(
            f"  {state} {fact['object']}"
            f" | 生效：{fact['valid_from']}"
            f" | 失效：{fact['valid_to'] or '—'}"
        )


def _set_current_fact_to_yesterday(api: RecallWeaverAPI) -> None:
    """Make the first address fact appear one day old for the demo timeline.

    Args:
        api: Initialized RecallWeaver API.
    """
    yesterday = (
        datetime.now(timezone.utc) - timedelta(days=1)
    ).isoformat(timespec="microseconds").replace("+00:00", "Z")
    with api.database_manager.get_connection() as connection:
        connection.execute(
            """
            UPDATE edges
            SET valid_from = ?
            WHERE tenant_id = ? AND predicate = ? AND valid_to IS NULL
              AND subject_id = (
                  SELECT id FROM entities
                  WHERE tenant_id = ? AND name = ?
              )
            """,
            (yesterday, "default", "住在", "default", "张三"),
        )


def _run_demo(database_path: Path) -> None:
    """Run the full demo with either DeepSeek or a deterministic local mock.

    Args:
        database_path: Path to the disposable demo database.
    """
    print("🚀 RecallWeaver 端到端演示")
    api = RecallWeaverAPI(str(database_path))

    api_key = settings.deepseek_api_key or os.getenv("DEEPSEEK_API_KEY", "")
    if api_key:
        extractor = LLMExtractor(
            api_key=api_key,
            base_url="https://api.deepseek.com",
            model="deepseek-chat",
        )
        print("🤖 抽取器：DeepSeek API")
        _extract_and_store(api, extractor, "我张三住在北京")
        _set_current_fact_to_yesterday(api)
        _extract_and_store(api, extractor, "我搬到上海了")
    else:
        print("🧪 未配置 DEEPSEEK_API_KEY，使用 Mock 响应，不发起网络请求")
        mocked_responses = [
            json.dumps(
                [
                    {
                        "subject": "张三",
                        "predicate": "住在",
                        "object_": "北京",
                    }
                ],
                ensure_ascii=False,
            ),
            json.dumps(
                [
                    {
                        "subject": "张三",
                        "predicate": "住在",
                        "object_": "上海",
                    }
                ],
                ensure_ascii=False,
            ),
        ]
        with patch(
            "recallweaver.extraction.llm_extractor.OpenAI"
        ) as openai_constructor:
            mocked_create = (
                openai_constructor.return_value.chat.completions.create
            )
            mocked_create.side_effect = [
                _mock_completion(mocked_responses[0]),
                _mock_completion(mocked_responses[1]),
            ]
            extractor = LLMExtractor(
                api_key="local-demo-key",
                base_url="https://api.deepseek.com",
                model="deepseek-chat",
            )
            _extract_and_store(api, extractor, "我张三住在北京")
            _set_current_fact_to_yesterday(api)
            _extract_and_store(api, extractor, "我搬到上海了")

    _print_history(api)

    long_text = (
        "张三最近整理了自己的生活计划。他过去住在北京，后来搬到上海。"
        "他希望记忆系统能够保留地址变更的历史，同时在询问“张三住在哪”时"
        "优先召回当前事实，并提供来源文本、实时衰减得分和写入时间。"
    )
    memory_id = api.add_memory(long_text)
    print(f"\n📝 已保存用于全文检索的长文本记忆：{memory_id}")

    print("\n🔎 混合检索：张三住在哪")
    results = api.recall("张三住在哪", limit=5)
    if not results:
        print("  未找到相关记忆或图谱关系")
    for result in results:
        print(
            f"  类型：{result.result_type}"
            f" | 得分：{result.score:.4f}"
            f" | 时间戳：{result.valid_from or result.created_at}"
        )
        if result.content:
            print(f"  内容：{result.content}")
        elif result.subject and result.predicate and result.object:
            print(
                f"  事实：{result.subject} {result.predicate} {result.object}"
            )

    print(f"\n✅ 演示完成，数据库位于：{database_path}")


def main() -> None:
    """Run the demo in a temporary directory to keep user data untouched."""
    with tempfile.TemporaryDirectory(prefix="recallweaver-demo-") as directory:
        _run_demo(Path(directory) / "recallweaver-demo.db")


if __name__ == "__main__":
    main()
