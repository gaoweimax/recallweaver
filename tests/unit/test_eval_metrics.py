"""Unit tests for retrieval precision, recall, and F1 metrics."""

from __future__ import annotations

import pytest

from benchmarks.eval_metrics import calculate_metrics


def test_perfect_retrieval_has_perfect_precision_recall_and_f1() -> None:
    """A complete, noise-free result set scores 1.0 for every metric."""
    ground_truth_ids = ["fact-1", "fact-2", "fact-3"]

    metrics = calculate_metrics(
        ["fact-1", "fact-2", "fact-3"],
        ground_truth_ids,
    )

    assert metrics["precision"] == pytest.approx(1.0)
    assert metrics["recall"] == pytest.approx(1.0)
    assert metrics["f1_score"] == pytest.approx(1.0)
    assert metrics["true_positive"] == 3
    assert metrics["false_positive"] == 0
    assert metrics["false_negative"] == 0


def test_all_noise_results_have_zero_precision() -> None:
    """Retrieving only irrelevant memories records only false positives."""
    metrics = calculate_metrics(
        ["noise-1", "noise-2"],
        ["fact-1", "fact-2"],
    )

    assert metrics["precision"] == 0.0
    assert metrics["recall"] == 0.0
    assert metrics["false_positive"] == 2
    assert metrics["false_negative"] == 2


def test_missing_core_fact_reduces_recall() -> None:
    """Omitting any relevant memory yields a recall below one."""
    metrics = calculate_metrics(
        ["fact-1", "noise-1"],
        ["fact-1", "fact-2"],
    )

    assert metrics["recall"] < 1.0
    assert metrics["recall"] == pytest.approx(0.5)
    assert metrics["false_negative"] == 1
    assert metrics["false_positive"] == 1


def test_duplicate_retrieval_ids_do_not_inflate_metrics() -> None:
    """Repeated copies of one relevant ID count only once."""
    metrics = calculate_metrics(
        ["fact-1", "fact-1"],
        ["fact-1", "fact-2"],
    )

    assert metrics["true_positive"] == 1
    assert metrics["precision"] == pytest.approx(1.0)
    assert metrics["recall"] == pytest.approx(0.5)
