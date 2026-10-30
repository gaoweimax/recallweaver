"""Natural-language extraction interfaces and implementations."""

from recallweaver.extraction.base import BaseExtractor
from recallweaver.extraction.llm_extractor import LLMExtractor

__all__ = ["BaseExtractor", "LLMExtractor"]