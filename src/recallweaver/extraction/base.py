"""抽取器接口定义。"""

from abc import ABC, abstractmethod


class BaseExtractor(ABC):
    """自然语言事实抽取器的统一接口。"""

    @abstractmethod
    def extract(self, text: str) -> list[dict[str, str]]:
        """从输入文本抽取主体、谓词和客体关系。

        Args:
            text: 需要分析的自然语言文本。

        Returns:
            三元组字典列表，每项包含 ``subject``、``predicate`` 和
            ``object_`` 三个非空字符串字段。
        """
        raise NotImplementedError