"""Measure benchmark information density and fact-conflict coverage.

The report is intentionally explicit about heuristic measurements and the
difference between deterministic schema-shaped fallback data and independently
curated industry benchmarks. It is written under ``benchmarks/datasets``.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = PROJECT_ROOT / "benchmarks"
DATASET_DIR = BENCHMARK_DIR / "datasets"
for import_path in (str(PROJECT_ROOT), str(BENCHMARK_DIR)):
    if import_path not in sys.path:
        sys.path.insert(0, import_path)

from dataset_loaders import (
    DatasetLoadError,
    FactConflictLoader,
    FactConflictRecord,
    LongMemEvalLoader,
    LongMemEvalSample,
    generate_mock_fact_conflicts,
    generate_mock_longmemeval_record,
    write_json_dataset,
)

LONGMEMEVAL_FILE = DATASET_DIR / "longmemeval_mock.json"
FACT_CONFLICT_FILE = DATASET_DIR / "fact_conflicts_mock.json"
REPORT_FILE = DATASET_DIR / "DATA_QUALITY_REPORT.md"
ENTITY_PATTERN = re.compile(
    r"\b[A-Z][a-z]{2,}(?:[ ,]+[A-Z][a-z]{2,})+\b"
    r"|(?:A公司|[一-龥]{2,4}(?:公司|集团|大学|医院))"
)


class DataQualityMetrics(BaseModel):
    """Validated aggregate dataset quality measurements.

    Attributes:
        information_density: Share of history/fact units with a valid entity.
        conflict_coverage: Share of conflict records that change the value.
        history_message_count: Number of LongMemEval history messages inspected.
        entity_bearing_units: Number of history or fact units with an entity.
        conflict_record_count: Number of fact-transition records inspected.
        valid_conflict_count: Number of transitions with distinct old/new values.
    """

    model_config = ConfigDict(extra="forbid")

    information_density: float = Field(ge=0.0, le=1.0)
    conflict_coverage: float = Field(ge=0.0, le=1.0)
    history_message_count: int = Field(ge=0)
    entity_bearing_units: int = Field(ge=0)
    conflict_record_count: int = Field(ge=0)
    valid_conflict_count: int = Field(ge=0)


def calculate_data_quality(
    long_samples: list[LongMemEvalSample],
    conflicts: list[FactConflictRecord],
) -> DataQualityMetrics:
    """Calculate entity-bearing unit density and fact-change coverage.

    A history unit is considered entity-bearing when the conservative,
    dependency-free entity pattern recognizes a proper-name span. A validated
    conflict record contributes one entity-bearing unit because its subject
    and fact values passed the loader's non-empty Pydantic contract.

    Args:
        long_samples: Validated conversation/question/answer tuples.
        conflicts: Validated fact-conflict records.

    Returns:
        Aggregate metrics bounded to the inclusive interval ``[0, 1]``.
    """
    history_message_count = sum(len(messages) for messages, _, _ in long_samples)
    entity_bearing_messages = sum(
        1
        for messages, _, _ in long_samples
        for message in messages
        if ENTITY_PATTERN.search(message["content"]) is not None
    )
    transition_count = len(conflicts)
    valid_conflict_count = sum(
        record.old_object.casefold() != record.new_object.casefold()
        for record in conflicts
    )

    total_units = history_message_count + transition_count
    entity_bearing_units = entity_bearing_messages + transition_count
    information_density = (
        entity_bearing_units / total_units if total_units else 0.0
    )
    conflict_coverage = (
        valid_conflict_count / transition_count if transition_count else 0.0
    )
    return DataQualityMetrics(
        information_density=information_density,
        conflict_coverage=conflict_coverage,
        history_message_count=history_message_count,
        entity_bearing_units=entity_bearing_units,
        conflict_record_count=transition_count,
        valid_conflict_count=valid_conflict_count,
    )


def _ensure_mock_data() -> None:
    """Create fallback source files when official or local datasets are absent."""
    try:
        DATASET_DIR.mkdir(parents=True, exist_ok=True)
        if not LONGMEMEVAL_FILE.exists():
            write_json_dataset(
                LONGMEMEVAL_FILE,
                [generate_mock_longmemeval_record(turns=60, token_budget=200_000)],
            )
        if not FACT_CONFLICT_FILE.exists():
            write_json_dataset(
                FACT_CONFLICT_FILE,
                generate_mock_fact_conflicts(count=4),
            )
    except (OSError, DatasetLoadError) as exc:
        raise RuntimeError(f"无法创建质量评估 Mock 数据：{exc}") from exc


def render_markdown_report(metrics: DataQualityMetrics) -> str:
    """Render a concise, auditable Markdown assessment.

    Args:
        metrics: Validated aggregate measurements.

    Returns:
        Markdown report documenting metrics, methodology and benchmark gaps.
    """
    return f"""# RecallWeaver 基准数据质量报告

## 当前数据集指标

| 指标 | 结果 | 口径 |
|---|---:|---|
| 信息密度（有效实体占比） | {metrics.information_density:.2%} | 在对话消息与事实冲突记录中，包含可识别实体或通过事实 schema 校验的单元占比。对话实体使用保守正则启发式识别，不等同于人工标注 NER。 |
| 冲突覆盖率 | {metrics.conflict_coverage:.2%} | `old_object` 与 `new_object` 不同的事实演变记录占全部已校验冲突记录的比例。 |
| 对话历史消息数 | {metrics.history_message_count} | 从 LongMemEval 兼容记录展平得到。 |
| 含实体单元数 | {metrics.entity_bearing_units} | 含可识别实体的对话消息加有效 schema 冲突记录数。 |
| 有效冲突记录数 | {metrics.valid_conflict_count}/{metrics.conflict_record_count} | 两个版本值不同且必需字段通过 Pydantic 校验的记录。 |

## 数据来源与差距

- **支持的外部标准数据**：Hugging Face `xiaowu0162/longmemeval-cleaned` 的 `longmemeval_s_cleaned.json`；事实演变解析器支持 `FactConsolidation` 风格 JSON，下载源和文件名可由基准命令显式配置。
- **离线回退数据**：当前缺少有效官方文件时使用 schema-compatible Mock Fallback。LongMemEval fallback 包含 60 轮对话和约 200,000 个空格分词上下文 token；事实 fallback 包含同一主体 CEO 连续变更序列；生活流测试使用多类别中文日常闲聊模板。
- **与旧自造 10 万条基准的差距**：旧数据主要由“用户编号 + 事项编号”模板构成，适合测量批量写入和基础 SQLite 查询，不包含真实问答证据、长程干扰对话、参考答案、有效时间版本链、时序边界或多样生活流噪音，因此不能单独代表语义召回和事实冲突质量。
- **与业界标注基准的差距**：Mock 数据由规则生成，没有第三方人工标注、真实用户分布、独立测试集、人工实体链接或标准答案审计；启发式信息密度不能替代 benchmark 的官方评测协议。发布结论应在导入并校验官方数据后复跑，并报告数据集版本、commit/hash、样本数和评测配置。

## 解释限制

本报告只衡量结构和覆盖率，不代表 RecallWeaver 已达到特定准确率或延迟 SLA。检索延迟由 `benchmarks/bench_real_world.py` 在隔离内存 SQLite 中单独测量；官方数据不可用时，其结果必须标注为合成回退结果。
"""


def evaluate(
    longmemeval_path: Path = LONGMEMEVAL_FILE,
    fact_conflict_path: Path = FACT_CONFLICT_FILE,
    report_path: Path = REPORT_FILE,
) -> DataQualityMetrics:
    """Load datasets, calculate metrics, and persist the Markdown report.

    Args:
        longmemeval_path: LongMemEval-compatible source JSON path.
        fact_conflict_path: FactConsolidation-compatible source JSON path.
        report_path: Destination Markdown report path.

    Returns:
        The computed aggregate quality measurements.

    Raises:
        DatasetLoadError: If a dataset fails parsing/validation or report output
            cannot be written.
    """
    long_samples = LongMemEvalLoader().load(str(longmemeval_path))
    conflicts = FactConflictLoader().load(str(fact_conflict_path))
    metrics = calculate_data_quality(long_samples, conflicts)
    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            render_markdown_report(metrics),
            encoding="utf-8",
        )
    except OSError as exc:
        raise DatasetLoadError(
            f"无法写入数据质量报告 {report_path}: {exc}"
        ) from exc
    return metrics


def main(argv: list[str] | None = None) -> int:
    """Run the data-quality assessment and print the report location."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--longmemeval", type=Path, default=LONGMEMEVAL_FILE)
    parser.add_argument("--fact-conflicts", type=Path, default=FACT_CONFLICT_FILE)
    parser.add_argument("--output", type=Path, default=REPORT_FILE)
    args = parser.parse_args(argv)
    try:
        _ensure_mock_data()
        metrics = evaluate(args.longmemeval, args.fact_conflicts, args.output)
    except (DatasetLoadError, RuntimeError) as exc:
        print(f"数据质量评估失败：{exc}", file=sys.stderr)
        return 1
    print(f"信息密度：{metrics.information_density:.2%}")
    print(f"冲突覆盖率：{metrics.conflict_coverage:.2%}")
    print(f"质量报告：{args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
