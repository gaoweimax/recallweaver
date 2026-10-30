"""使用 OpenAI 兼容聊天补全 API 抽取知识图谱三元组。"""

import json
import re
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from pydantic import BaseModel, ConfigDict, ValidationError as PydanticValidationError
from pydantic import field_validator

from recallweaver.errors import ExtractionError
from recallweaver.extraction.base import BaseExtractor

SYSTEM_PROMPT = (
    "你是一个知识图谱抽取助手。请从用户的输入中提取事实关系。"
    "必须只输出合法的 JSON 数组，不要包含任何 Markdown 标记"
    "（如 ```json）或解释性文字。"
    '格式示例：[{"subject": "张三", "predicate": "住在", "object_": "北京"}]'
)


class _Triple(BaseModel):
    """单条抽取结果的严格结构。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    subject: str
    predicate: str
    object_: str

    @field_validator("subject", "predicate", "object_")
    @classmethod
    def require_non_empty_value(cls, value: str) -> str:
        """拒绝空白实体或关系字段。"""
        if not value.strip():
            raise ValueError("三元组字段不能为空")
        return value.strip()


class LLMExtractor(BaseExtractor):
    """通过兼容 OpenAI Chat Completions 协议的大语言模型抽取事实。

    Args:
        api_key: 服务端 API 密钥。
        base_url: 兼容 OpenAI 的 API 根 URL。
        model: 要调用的模型名称。
        timeout: 单次请求的超时秒数。

    Raises:
        ExtractionError: 客户端初始化配置不合法时抛出。
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str = "deepseek-chat",
        timeout: float = 30.0,
    ) -> None:
        """初始化 OpenAI 兼容客户端。

        Args:
            api_key: 服务端 API 密钥。
            base_url: 服务端 API 根 URL。
            model: 要调用的模型名称。
            timeout: 网络请求超时时间，单位为秒。

        Raises:
            ExtractionError: API 密钥、URL 或模型参数为空或超时值无效时抛出。
        """
        if not all(
            isinstance(value, str) and value.strip()
            for value in (api_key, base_url, model)
        ):
            raise ExtractionError("api_key、base_url 和 model 均不能为空")
        if timeout <= 0:
            raise ExtractionError("timeout 必须大于 0")

        self.model = model.strip()
        try:
            self.client = OpenAI(
                api_key=api_key.strip(),
                base_url=base_url.strip(),
                timeout=timeout,
            )
        except Exception as exc:
            raise ExtractionError(f"初始化 LLM 客户端失败：{exc}") from exc

    @staticmethod
    def _parse_triples(content: str) -> list[dict[str, str]]:
        """清理响应包裹并校验三元组 JSON。

        Args:
            content: 模型返回的原始消息文本。

        Returns:
            校验通过的三元组字典列表；合法空数组返回空列表。

        Raises:
            ExtractionError: 响应不是有效 JSON 数组或字段不符合契约。
        """
        cleaned = content.strip()
        fenced_match = re.fullmatch(
            r"```(?:json)?\s*(.*?)\s*```",
            cleaned,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if fenced_match:
            cleaned = fenced_match.group(1).strip()

        # 某些兼容 API 会在 JSON 外附加说明文字，尽量只解析完整数组/对象。
        if not cleaned.startswith(("[", "{")):
            array_start = cleaned.find("[")
            object_start = cleaned.find("{")
            starts = [index for index in (array_start, object_start) if index >= 0]
            if not starts:
                raise ExtractionError("模型响应中未找到 JSON 内容")
            cleaned = cleaned[min(starts):]

        try:
            payload: Any = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            # 兼容尾随说明文本，但不尝试猜测或修补不完整 JSON。
            decoder = json.JSONDecoder()
            start_positions = [
                position
                for position in (cleaned.find("["), cleaned.find("{"))
                if position >= 0
            ]
            try:
                payload, _ = decoder.raw_decode(cleaned[min(start_positions):])
            except (json.JSONDecodeError, ValueError) as parse_exc:
                raise ExtractionError(
                    f"模型响应不是合法 JSON：{parse_exc}"
                ) from exc

        if isinstance(payload, dict):
            if {"subject", "predicate", "object_"}.issubset(payload):
                payload = [payload]
            else:
                payload = payload.get(
                    "triples",
                    payload.get("relations", payload.get("data")),
                )
        if not isinstance(payload, list):
            raise ExtractionError("模型响应必须是 JSON 三元组数组")

        triples: list[dict[str, str]] = []
        try:
            for item in payload:
                triple = _Triple.model_validate(item)
                triples.append(triple.model_dump())
        except (PydanticValidationError, TypeError) as exc:
            raise ExtractionError(f"模型输出的三元组格式无效：{exc}") from exc

        return triples

    def extract(self, text: str) -> list[dict[str, str]]:
        """抽取输入文本中的事实关系。

        Args:
            text: 待抽取的自然语言文本。

        Returns:
            标准三元组列表；模型正确返回空数组时返回 ``[]``。

        Raises:
            ExtractionError: 输入为空、网络请求超时/失败或响应 JSON 无效时抛出。
        """
        if not isinstance(text, str) or not text.strip():
            raise ExtractionError("待抽取文本不能为空")

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": text.strip()},
                ],
            )
        except APITimeoutError as exc:
            raise ExtractionError(f"LLM 请求超时：{exc}") from exc
        except APIConnectionError as exc:
            raise ExtractionError(f"LLM 网络连接失败：{exc}") from exc
        except APIStatusError as exc:
            raise ExtractionError(
                f"LLM 服务返回错误状态 {exc.status_code}：{exc}"
            ) from exc
        except Exception as exc:
            raise ExtractionError(f"LLM 请求失败：{exc}") from exc

        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, TypeError) as exc:
            raise ExtractionError("LLM 响应缺少有效的消息内容") from exc
        if not isinstance(content, str):
            raise ExtractionError("LLM 响应内容必须是字符串")

        return self._parse_triples(content)