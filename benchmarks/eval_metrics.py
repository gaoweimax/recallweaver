"""Precision, recall, and F1 metrics for retrieval evaluations."""

from __future__ import annotations

from typing import TypeAlias

MetricValue: TypeAlias = float | int | list[str]


def calculate_metrics(
    retrieved_ids: list[str],
    ground_truth_ids: list[str],
) -> dict[str, MetricValue]:
    """Calculate set-based precision, recall, and F1 for one query.

    Duplicate IDs are counted once so repeated results cannot inflate either
    true positives or false positives.

    Args:
        retrieved_ids: IDs returned by the retriever.
        ground_truth_ids: IDs labeled relevant for the query.

    Returns:
        Counts, scores, and the IDs responsible for false positives and false
        negatives. Undefined precision or recall denominators produce 0.0.

    Raises:
        TypeError: If either argument is not a list of strings.
        ValueError: If an ID is empty or contains only whitespace.
    """
    for parameter_name, identifiers in (
        ("retrieved_ids", retrieved_ids),
        ("ground_truth_ids", ground_truth_ids),
    ):
        if not isinstance(identifiers, list) or any(
            not isinstance(identifier, str) for identifier in identifiers
        ):
            raise TypeError(f"{parameter_name} 必须是字符串列表")
        if any(not identifier.strip() for identifier in identifiers):
            raise ValueError(f"{parameter_name} 不能包含空 ID")

    retrieved_set = set(retrieved_ids)
    ground_truth_set = set(ground_truth_ids)
    true_positive_ids = retrieved_set & ground_truth_set
    false_positive_ids = retrieved_set - ground_truth_set
    false_negative_ids = ground_truth_set - retrieved_set

    true_positive = len(true_positive_ids)
    false_positive = len(false_positive_ids)
    false_negative = len(false_negative_ids)
    precision = (
        true_positive / (true_positive + false_positive)
        if true_positive + false_positive
        else 0.0
    )
    recall = (
        true_positive / (true_positive + false_negative)
        if true_positive + false_negative
        else 0.0
    )
    f1_score = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )

    return {
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": precision,
        "recall": recall,
        "f1_score": f1_score,
        "false_positive_ids": sorted(false_positive_ids),
        "false_negative_ids": sorted(false_negative_ids),
    }
