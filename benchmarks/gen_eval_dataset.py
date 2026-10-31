"""Generate deterministic retrieval-quality evaluation cases."""

from __future__ import annotations

import argparse
import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from rich.console import Console

DEFAULT_CASE_COUNT = 100
NOISE_PER_CASE = 20
FACTS_PER_CASE = 3
DEFAULT_OUTPUT_PATH = (
    Path(__file__).resolve().parent
    / "datasets"
    / "retrieval_quality_eval.json"
)

_NOISE_TEMPLATES = (
    "今天天气不错，适合出门散步。",
    "股票今天涨了几个点，先继续观察。",
    "午饭吃了番茄炒蛋，味道还不错。",
    "周末准备去公园走走，顺便买些水果。",
    "通勤路上有点堵，公交晚点了几分钟。",
    "刚看完一部电影，配乐和画面都很好。",
    "快递已经放在前台，有空记得取一下。",
    "窗外开始下雨了，回家记得带伞。",
    "晚上打算整理书桌和收拾房间。",
    "朋友分享了一首歌，旋律听起来很轻松。",
)
_ALLERGENS = ("花生", "牛奶", "虾", "芒果", "鸡蛋")
_CITIES = ("杭州", "成都", "南京", "厦门", "苏州")
_PROFESSIONS = ("教师", "软件工程师", "护士", "建筑师", "设计师")


@dataclass(frozen=True)
class EvaluationCase:
    """One isolated query with its noise corpus and relevant fact IDs.

    Attributes:
        case_id: Stable identifier for this evaluation case.
        tenant_id: Isolated tenant used to scope its SQLite records.
        noise_history: Unrelated conversational memories.
        core_facts: The three relevant fact strings.
        query: Query intended to retrieve all three core facts.
        ground_truth_ids: Stable IDs corresponding to ``core_facts``.
    """

    case_id: str
    tenant_id: str
    noise_history: list[str]
    core_facts: list[str]
    query: str
    ground_truth_ids: list[str]


def generate_dataset(
    case_count: int = DEFAULT_CASE_COUNT,
) -> list[EvaluationCase]:
    """Build deterministic cases containing 20 noise and three core facts.

    Args:
        case_count: Number of isolated cases to generate. Must be positive.

    Returns:
        Evaluation cases with deterministic core-memory IDs.

    Raises:
        ValueError: If ``case_count`` is not a positive integer.
    """
    if (
        isinstance(case_count, bool)
        or not isinstance(case_count, int)
        or case_count <= 0
    ):
        raise ValueError("case_count 必须是正整数")

    dataset: list[EvaluationCase] = []
    for case_number in range(1, case_count + 1):
        case_id = f"case_{case_number:03d}"
        tenant_id = f"eval_{case_id}"
        subject = f"用户{case_number:03d}"
        allergen = _ALLERGENS[(case_number - 1) % len(_ALLERGENS)]
        city = _CITIES[(case_number - 1) % len(_CITIES)]
        profession = _PROFESSIONS[(case_number - 1) % len(_PROFESSIONS)]

        core_facts = [
            f"{subject}对{allergen}过敏，点餐时应避开{allergen}。",
            f"{subject}目前居住在{city}。",
            f"{subject}的职业是{profession}。",
        ]
        ground_truth_ids = [
            str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"recallweaver-eval:{case_id}:core:{fact_index}",
                )
            )
            for fact_index in range(FACTS_PER_CASE)
        ]
        noise_history = [
            (
                f"群聊{noise_number + 1:02d}："
                f"{_NOISE_TEMPLATES[(case_number + noise_number) % len(_NOISE_TEMPLATES)]}"
            )
            for noise_number in range(NOISE_PER_CASE)
        ]
        dataset.append(
            EvaluationCase(
                case_id=case_id,
                tenant_id=tenant_id,
                noise_history=noise_history,
                core_facts=core_facts,
                # FTS5 trigram ignores CJK runs shorter than three characters.
                # The unique subject key matches all three facts without
                # diluting the query with unrelated phrase trigrams.
                query=subject,
                ground_truth_ids=ground_truth_ids,
            )
        )
    return dataset


def write_dataset(
    dataset: list[EvaluationCase],
    file_path: str | Path = DEFAULT_OUTPUT_PATH,
) -> Path:
    """Serialize evaluation cases as a UTF-8 JSON document.

    Args:
        dataset: Cases to serialize.
        file_path: Destination JSON path.

    Returns:
        The resolved path of the written file.

    Raises:
        OSError: If the parent directory or output file cannot be written.
    """
    output_path = Path(file_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            [asdict(case) for case in dataset],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return output_path


def main() -> None:
    """Generate the default 100-case dataset or a requested JSON export."""
    parser = argparse.ArgumentParser(
        description="生成 RecallWeaver Precision/Recall 评测数据集"
    )
    parser.add_argument(
        "--count",
        type=int,
        default=DEFAULT_CASE_COUNT,
        help="数据组数（默认：100）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="JSON 输出路径",
    )
    arguments = parser.parse_args()
    dataset = generate_dataset(arguments.count)
    output_path = write_dataset(dataset, arguments.output)
    Console().print(
        f"已生成 {len(dataset)} 组评测数据：{output_path} "
        f"（每组 {NOISE_PER_CASE} 条噪音、{FACTS_PER_CASE} 条核心事实）"
    )


if __name__ == "__main__":
    main()
