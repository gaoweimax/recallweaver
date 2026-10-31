"""Evaluate retriever precision and recall on isolated synthetic cases."""

from __future__ import annotations

import sys
from pathlib import Path
import tempfile
import time
import logging
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
for import_path in (PROJECT_ROOT, PROJECT_ROOT / "src"):
    resolved_import_path = str(import_path)
    if resolved_import_path not in sys.path:
        sys.path.insert(0, resolved_import_path)

from rich.console import Console
from rich.markdown import Markdown

from benchmarks.eval_metrics import calculate_metrics
from benchmarks.gen_eval_dataset import (
    FACTS_PER_CASE,
    NOISE_PER_CASE,
    EvaluationCase,
    generate_dataset,
)
from recallweaver.db import Database
from recallweaver.retrieval import Retriever

TOP_K = 5
CASE_COUNT = 100
PRECISION_TARGET = 0.8
RECALL_TARGET = 0.9


def _configure_utf8_output() -> None:
    """Configure console streams to render the Chinese Markdown report.

    Windows may default to a legacy code page that cannot encode Rich's
    Unicode table and bullet characters.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def _insert_dataset(
    database: Database,
    dataset: list[EvaluationCase],
) -> int:
    """Insert every case's noise and core memories into its isolated tenant.

    Args:
        database: Initialized temporary SQLite database.
        dataset: Generated evaluation cases.

    Returns:
        Number of inserted memory records.
    """
    now = int(time.time())
    row_count = 0
    with database.get_connection() as connection:
        for case in dataset:
            connection.execute(
                """
                INSERT INTO tenants (id, name, created_at)
                VALUES (?, ?, ?)
                """,
                (case.tenant_id, case.case_id, now),
            )
            records: list[tuple[str, str, float, int]] = []
            records.extend(
                (
                    f"{case.case_id}:noise:{index:02d}",
                    content,
                    0.5,
                    now,
                )
                for index, content in enumerate(case.noise_history)
            )
            records.extend(
                (memory_id, content, 1.5, now)
                for memory_id, content in zip(
                    case.ground_truth_ids,
                    case.core_facts,
                    strict=True,
                )
            )
            connection.executemany(
                """
                INSERT INTO memories (
                    id, tenant_id, content, base_weight, decay_lambda,
                    retrieval_count, last_decay_at, decayed_weight,
                    valid_from, tx_time, status, created_at
                )
                VALUES (?, ?, ?, ?, 0.0, 0, ?, ?, ?, ?, 'active', ?)
                """,
                [
                    (
                        memory_id,
                        case.tenant_id,
                        content,
                        base_weight,
                        created_at,
                        base_weight,
                        created_at,
                        created_at,
                        created_at,
                    )
                    for memory_id, content, base_weight, created_at in records
                ],
            )
            row_count += len(records)

        persisted_count = int(
            connection.execute(
                "SELECT count(*) FROM memories"
            ).fetchone()[0]
        )
    if persisted_count != row_count:
        raise AssertionError(
            f"数据写入数量不匹配：预期 {row_count}，实际 {persisted_count}"
        )
    expected_count = len(dataset) * (NOISE_PER_CASE + FACTS_PER_CASE)
    if row_count != expected_count:
        raise AssertionError(
            f"评测数据数量不匹配：预期 {expected_count}，实际 {row_count}"
        )
    return row_count


def _metric_number(
    metrics: dict[str, float | int | list[str]],
    key: str,
) -> float:
    """Read one numeric metric value with an explicit type guard.

    Args:
        metrics: Per-query metrics mapping.
        key: Numeric metric name.

    Returns:
        Requested value as a float.

    Raises:
        TypeError: If the metric is missing or is not numeric.
    """
    value = metrics.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"指标 {key} 缺失或不是数值")
    return float(value)


def _format_failure_table(
    title: str,
    cases: list[dict[str, Any]],
    count_key: str,
    ids_key: str,
) -> list[str]:
    """Format the three largest false-positive or false-negative cases.

    Args:
        title: Markdown section title.
        cases: Per-query evaluation records.
        count_key: Error-count metric used to rank cases.
        ids_key: List of offending IDs to display.

    Returns:
        Markdown lines for the sorted failure table.
    """
    failures = [
        case for case in cases
        if int(case["metrics"][count_key]) > 0
    ]
    failures.sort(
        key=lambda case: (
            int(case["metrics"][count_key]),
            case["case_id"],
        ),
        reverse=True,
    )
    lines = [f"### {title}", "", "| Case | Query | Count | IDs |", "|---|---|---:|---|"]
    if not failures:
        lines.append("| - | 无失败案例 | 0 | - |")
        return lines
    for case in failures[:3]:
        identifiers = ", ".join(case["metrics"][ids_key])
        lines.append(
            f"| {case['case_id']} | {case['query']} | "
            f"{case['metrics'][count_key]} | {identifiers or '-'} |"
        )
    return lines


def run_evaluation(case_count: int = CASE_COUNT) -> dict[str, Any]:
    """Generate, ingest, and evaluate a collection of retrieval cases.

    Args:
        case_count: Number of cases to evaluate.

    Returns:
        Aggregate scores, record count, and per-case failure details.
    """
    started_at = time.perf_counter()
    logging.getLogger("recallweaver.db").setLevel(logging.WARNING)
    dataset = generate_dataset(case_count)
    with tempfile.TemporaryDirectory(
        prefix="recallweaver-quality-eval-"
    ) as temporary_directory:
        database = Database(
            str(Path(temporary_directory) / "quality-eval.sqlite3")
        )
        database.init_db(verbose=False)
        record_count = _insert_dataset(database, dataset)
        retriever = Retriever(database=database)

        evaluations: list[dict[str, Any]] = []
        for case in dataset:
            retrieved_rows = retriever.search(
                case.query,
                limit=TOP_K,
                tenant_id=case.tenant_id,
            )
            metrics = calculate_metrics(
                [str(row["id"]) for row in retrieved_rows],
                case.ground_truth_ids,
            )
            evaluations.append(
                {
                    "case_id": case.case_id,
                    "query": case.query,
                    "metrics": metrics,
                }
            )

    mean_precision = sum(
        _metric_number(case["metrics"], "precision")
        for case in evaluations
    ) / len(evaluations)
    mean_recall = sum(
        _metric_number(case["metrics"], "recall")
        for case in evaluations
    ) / len(evaluations)
    mean_f1 = sum(
        _metric_number(case["metrics"], "f1_score")
        for case in evaluations
    ) / len(evaluations)

    report_lines = [
        "# RecallWeaver 检索质量评测报告",
        "",
        f"- 评测用例：{len(dataset)}",
        f"- 数据记录：{record_count:,}（每组 {NOISE_PER_CASE} 条噪音 + "
        f"{FACTS_PER_CASE} 条核心事实）",
        f"- 检索深度：Top-{TOP_K}",
        f"- 总耗时：{time.perf_counter() - started_at:.3f} 秒",
        "",
        "| 指标 | 平均值 | 目标 | 状态 |",
        "|---|---:|---:|---|",
        f"| Precision | {mean_precision:.4f} | > {PRECISION_TARGET:.2f} | "
        f"{'通过' if mean_precision > PRECISION_TARGET else '未通过'} |",
        f"| Recall | {mean_recall:.4f} | > {RECALL_TARGET:.2f} | "
        f"{'通过' if mean_recall > RECALL_TARGET else '未通过'} |",
        f"| F1-Score | {mean_f1:.4f} | - | - |",
        "",
    ]
    report_lines.extend(
        _format_failure_table(
            "假阴性最多的 Top 3 案例",
            evaluations,
            "false_negative",
            "false_negative_ids",
        )
    )
    report_lines.append("")
    report_lines.extend(
        _format_failure_table(
            "假阳性最多的 Top 3 案例",
            evaluations,
            "false_positive",
            "false_positive_ids",
        )
    )
    report = "\n".join(report_lines)
    Console().print(Markdown(report))

    if mean_precision <= PRECISION_TARGET or mean_recall <= RECALL_TARGET:
        raise AssertionError(
            "检索质量未达到门槛："
            f"Precision={mean_precision:.4f}（需 > {PRECISION_TARGET:.2f}），"
            f"Recall={mean_recall:.4f}（需 > {RECALL_TARGET:.2f}）"
        )

    return {
        "case_count": len(dataset),
        "record_count": record_count,
        "mean_precision": mean_precision,
        "mean_recall": mean_recall,
        "mean_f1_score": mean_f1,
        "evaluations": evaluations,
    }


if __name__ == "__main__":
    _configure_utf8_output()
    run_evaluation()
