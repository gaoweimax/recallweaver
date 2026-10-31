"""Generate a deterministic, high-volume conversational memory corpus.

The corpus contains 500 isolated user tenants, structured profile facts,
versioned residence changes, and unrelated group-chat noise. Records are
streamed to JSONL so generation does not require holding the dataset in memory.
"""

from __future__ import annotations

import argparse
import json
import random
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator


USER_COUNT = 500
CORE_FACTS_PER_USER = 4
MOVES_PER_USER = 3
TOTAL_RECORDS = 50_000
NOISE_TENANT = "group-chat"
DEFAULT_OUTPUT_PATH = (
    Path(__file__).resolve().parent / "datasets" / "complex_data.jsonl"
)


@dataclass(frozen=True)
class ComplexMemoryRecord:
    """One typed memory row and its optional fact-version metadata.

    Attributes:
        memory_id: Stable UUID for repeatable imports.
        user_id: Logical user represented by the record.
        tenant_id: Isolated user tenant or shared group-chat tenant.
        kind: ``fact``, ``residence_change``, or ``noise``.
        content: Natural-language memory body indexed by SQLite FTS5.
        base_weight: Relative importance used by the retrieval scorer.
        created_at: Unix timestamp when the synthetic event was created.
        valid_from: Unix timestamp when the fact version became effective.
        valid_to: End timestamp for superseded residence facts, if any.
        predicate: Structured fact relation, when applicable.
        object: Structured fact value, when applicable.
        status: Whether the fact version is current or historical.
    """

    memory_id: str
    user_id: str
    tenant_id: str
    kind: str
    content: str
    base_weight: float
    created_at: int
    valid_from: int
    valid_to: int | None
    predicate: str | None
    object: str | None
    status: str


_PROFESSIONS = ("教师", "软件工程师", "护士", "建筑师", "厨师", "设计师")
_ALLERGENS = ("海鲜", "牛奶", "鸡蛋", "芒果", "花生")
_FOODS = ("番茄", "面条", "豆腐", "苹果", "米饭", "咖喱")
_CITIES = ("北京", "上海", "广州", "成都", "杭州", "深圳", "南京", "厦门")
_CHAT_TEMPLATES = (
    "群聊闲谈：今天天气晴朗，适合出门散步，大家下午都有什么安排。",
    "群聊闲谈：刚刚看到一部有趣的电影，周末可以找时间一起看。",
    "群聊闲谈：附近新开了一家咖啡店，装修简单，排队的人不多。",
    "群聊闲谈：今天路上有点堵，公交晚了几分钟，终于到办公室了。",
    "群聊闲谈：午饭吃了炒饭和青菜，味道还不错，分量也很足。",
    "群聊闲谈：周末想去公园走走，顺便买些水果和日用品。",
    "群聊闲谈：最近听到一首旋律很轻松的歌，已经加入播放列表。",
    "群聊闲谈：窗外开始下雨了，记得回家时带上伞，路面有些湿。",
    "群聊闲谈：刚整理完书桌和文件，房间看起来清爽了不少。",
    "群聊闲谈：今天的比赛刚结束，最后几分钟的比分变化很精彩。",
    "群聊闲谈：快递已经放在前台，方便的时候记得去取一下。",
    "群聊闲谈：晚饭还没决定，可能会做简单的汤和蔬菜。",
)


def _record(
    index: int,
    *,
    user_id: str,
    tenant_id: str,
    kind: str,
    content: str,
    base_weight: float,
    created_at: int,
    valid_from: int,
    valid_to: int | None = None,
    predicate: str | None = None,
    object_: str | None = None,
    status: str = "active",
) -> ComplexMemoryRecord:
    """Create one deterministic record with a stable import identifier.

    Args:
        index: Globally unique corpus row number.
        user_id: Logical owner of the record.
        tenant_id: Database tenant used for isolation.
        kind: Record category.
        content: Searchable memory text.
        base_weight: Importance weight.
        created_at: Event ingestion time.
        valid_from: Fact start time.
        valid_to: Optional fact end time.
        predicate: Optional structured relation.
        object_: Optional structured fact value.
        status: Current or historical record state.

    Returns:
        An immutable JSONL-ready memory record.
    """
    stable_name = f"recallweaver-complex-corpus:{index}"
    return ComplexMemoryRecord(
        memory_id=str(uuid.uuid5(uuid.NAMESPACE_URL, stable_name)),
        user_id=user_id,
        tenant_id=tenant_id,
        kind=kind,
        content=content,
        base_weight=base_weight,
        created_at=created_at,
        valid_from=valid_from,
        valid_to=valid_to,
        predicate=predicate,
        object=object_,
        status=status,
    )


def generate_records(seed: int = 20261031) -> Iterator[ComplexMemoryRecord]:
    """Yield exactly 50,000 structured facts, moves, and unrelated chatter.

    Each user receives an occupation, allergy, favorite food, and initial
    residence fact, followed by three chronologically contiguous moves. Noise
    records are assigned to a separate shared tenant and contain no user IDs,
    preventing unrelated chat from accidentally matching a user's query.

    Args:
        seed: Seed for reproducible selection of profile values and chatter.

    Yields:
        Corpus records in chronological fact-then-noise order.

    Raises:
        AssertionError: If the configured corpus composition is inconsistent.
    """
    randomizer = random.Random(seed)
    now = int(time.time())
    index = 0

    def create_record(
        *,
        user_id: str,
        tenant_id: str,
        kind: str,
        content: str,
        base_weight: float,
        created_at: int,
        valid_from: int,
        valid_to: int | None = None,
        predicate: str | None = None,
        object_: str | None = None,
        status: str = "active",
    ) -> ComplexMemoryRecord:
        """Bind the next deterministic row number to a record."""
        nonlocal index
        record = _record(
            index,
            user_id=user_id,
            tenant_id=tenant_id,
            kind=kind,
            content=content,
            base_weight=base_weight,
            created_at=created_at,
            valid_from=valid_from,
            valid_to=valid_to,
            predicate=predicate,
            object_=object_,
            status=status,
        )
        index += 1
        return record

    for user_number in range(1, USER_COUNT + 1):
        user_id = f"user_{user_number}"
        profession = randomizer.choice(_PROFESSIONS)
        allergen = (
            "花生"
            if user_number == 88
            else randomizer.choice(_ALLERGENS)
        )
        favorite_food = randomizer.choice(_FOODS)
        initial_city = randomizer.choice(_CITIES)
        profile_time = now - (user_number % 30) * 86_400

        yield create_record(
            user_id=user_id,
            tenant_id=user_id,
            kind="fact",
            content=f"职业：{profession}。",
            base_weight=1.0,
            created_at=now,
            valid_from=profile_time,
            predicate="职业",
            object_=profession,
        )
        yield create_record(
            user_id=user_id,
            tenant_id=user_id,
            kind="fact",
            content=f"{user_id} 对{allergen}过敏。",
            base_weight=2.0 if user_number == 88 else 1.0,
            created_at=now,
            valid_from=profile_time,
            predicate="过敏源",
            object_=allergen,
        )
        yield create_record(
            user_id=user_id,
            tenant_id=user_id,
            kind="fact",
            content=f"喜欢的食物：{favorite_food}。",
            base_weight=1.0,
            created_at=now,
            valid_from=profile_time,
            predicate="喜欢的食物",
            object_=favorite_food,
        )

        residence_versions = [initial_city]
        while len(residence_versions) < MOVES_PER_USER + 1:
            next_city = randomizer.choice(_CITIES)
            if next_city != residence_versions[-1]:
                residence_versions.append(next_city)

        residence_start = now - 4 * 365 * 86_400
        version_starts = [
            residence_start + move_index * 365 * 86_400
            for move_index in range(MOVES_PER_USER + 1)
        ]
        for version_index, city in enumerate(residence_versions):
            valid_to = (
                version_starts[version_index + 1]
                if version_index < MOVES_PER_USER
                else None
            )
            yield create_record(
                user_id=user_id,
                tenant_id=user_id,
                kind="fact" if version_index == 0 else "residence_change",
                content=(
                    f"居住地：{city}。"
                    if version_index == 0
                    else (
                        f"搬家记录：从{residence_versions[version_index - 1]}"
                        f"搬到{city}。"
                    )
                ),
                base_weight=1.2,
                created_at=now,
                valid_from=version_starts[version_index],
                valid_to=valid_to,
                predicate="居住地",
                object_=city,
                status="expired" if valid_to is not None else "active",
            )

    factual_records = USER_COUNT * (
        CORE_FACTS_PER_USER + MOVES_PER_USER
    )
    expected_noise_records = TOTAL_RECORDS - factual_records
    for noise_index in range(expected_noise_records):
        content = (
            randomizer.choice(_CHAT_TEMPLATES)
            + f" 群聊消息编号 {noise_index + 1}。"
        )
        yield create_record(
            user_id="group-chat",
            tenant_id=NOISE_TENANT,
            kind="noise",
            content=content,
            base_weight=0.1,
            created_at=now,
            valid_from=now,
        )

    if index != TOTAL_RECORDS:
        raise AssertionError(
            f"预期生成 {TOTAL_RECORDS} 条，实际生成 {index} 条"
        )


def write_jsonl(
    output_path: str | Path,
    seed: int = 20261031,
) -> int:
    """Stream the complete synthetic corpus to a UTF-8 JSON Lines file.

    Args:
        output_path: Destination JSONL path. Parent directories are created.
        seed: Seed forwarded to :func:`generate_records`.

    Returns:
        Number of serialized memory records.

    Raises:
        OSError: If the destination cannot be created or written.
        AssertionError: If generation does not produce exactly 50,000 rows.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as output_file:
        for record in generate_records(seed=seed):
            output_file.write(
                json.dumps(asdict(record), ensure_ascii=False) + "\n"
            )
            count += 1

    if count != TOTAL_RECORDS:
        raise AssertionError(
            f"预期写入 {TOTAL_RECORDS} 条，实际写入 {count} 条"
        )
    return count


def main(argv: list[str] | None = None) -> int:
    """Run the JSONL generator from the command line.

    Args:
        argv: Optional command-line arguments, primarily for testing.

    Returns:
        Process exit code; zero indicates successful generation.
    """
    parser = argparse.ArgumentParser(
        description="Generate the 50,000-row RecallWeaver complex corpus."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="JSONL output path (default: benchmarks/datasets/complex_data.jsonl)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=20261031,
        help="Seed used for reproducible profile and chatter selection.",
    )
    args = parser.parse_args(argv)
    count = write_jsonl(args.output, seed=args.seed)
    print(f"Generated {count:,} records: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
