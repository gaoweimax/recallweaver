"""单元测试 LLM 三元组抽取与响应容错。"""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from recallweaver.errors import ExtractionError
from recallweaver.extraction.llm_extractor import LLMExtractor, SYSTEM_PROMPT


@pytest.fixture
def mock_client():
    """替换 OpenAI 客户端，确保测试不会发出网络请求。"""
    with patch("recallweaver.extraction.llm_extractor.OpenAI") as openai_mock:
        client = openai_mock.return_value
        yield openai_mock, client


def _mock_response(content: str):
    """构造与 Chat Completions SDK 兼容的最小响应对象。"""
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
            )
        ]
    )


def test_extract_valid_json(mock_client) -> None:
    """标准 JSON 数组应被解析成标准三元组字典。"""
    _, client = mock_client
    expected = [
        {"subject": "张三", "predicate": "住在", "object_": "北京"},
        {"subject": "李四", "predicate": "认识", "object_": "王五"},
    ]
    client.chat.completions.create.return_value = _mock_response(
        json.dumps(expected, ensure_ascii=False)
    )
    extractor = LLMExtractor(
        api_key="test-key",
        base_url="https://api.example.test/v1",
    )

    assert extractor.extract("张三住在北京，李四认识王五。") == expected

    request = client.chat.completions.create.call_args.kwargs
    assert request["response_format"] == {"type": "json_object"}
    assert request["messages"][0]["content"] == SYSTEM_PROMPT
    assert request["messages"][1]["content"] == "张三住在北京，李四认识王五。"


def test_extract_with_markdown_wrapper(mock_client) -> None:
    """带有 JSON Markdown 代码围栏的输出应在解析前清理。"""
    _, client = mock_client
    client.chat.completions.create.return_value = _mock_response(
        """```json
[
  {"subject": "张三", "predicate": "认识", "object_": "李四"}
]
```"""
    )
    extractor = LLMExtractor(
        api_key="test-key",
        base_url="https://api.example.test/v1",
    )

    assert extractor.extract("张三认识李四") == [
        {"subject": "张三", "predicate": "认识", "object_": "李四"}
    ]


def test_extract_invalid_json_raises_extraction_error(mock_client) -> None:
    """无法解析的模型响应应转换成 ExtractionError，而非泄漏 JSON 异常。"""
    _, client = mock_client
    client.chat.completions.create.return_value = _mock_response(
        "这段内容没有任何 JSON 结构。"
    )
    extractor = LLMExtractor(
        api_key="test-key",
        base_url="https://api.example.test/v1",
    )

    with pytest.raises(ExtractionError, match="JSON"):
        extractor.extract("请抽取事实")


def test_extract_empty_array_returns_empty_list(mock_client) -> None:
    """模型确认没有事实时返回空列表，不构造虚假三元组。"""
    _, client = mock_client
    client.chat.completions.create.return_value = _mock_response("[]")
    extractor = LLMExtractor(
        api_key="test-key",
        base_url="https://api.example.test/v1",
    )

    assert extractor.extract("今天天气不错。") == []


def test_extract_timeout_is_translated(mock_client) -> None:
    """请求超时应转换为 ExtractionError，且不泄漏 SDK 异常类型。"""
    _, client = mock_client
    from openai import APITimeoutError

    client.chat.completions.create.side_effect = APITimeoutError(
        request=SimpleNamespace()
    )
    extractor = LLMExtractor(
        api_key="test-key",
        base_url="https://api.example.test/v1",
    )

    with pytest.raises(ExtractionError, match="超时"):
        extractor.extract("张三住在北京")
