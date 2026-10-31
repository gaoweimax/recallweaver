"""Integration tests for the validated API and Click command-line surface."""

from click.testing import CliRunner
import pytest

from recallweaver.api import RecallWeaverAPI
from recallweaver.cli import cli
from recallweaver.config import settings
from recallweaver.errors import ValidationError
from recallweaver.models import MemoryOut


def test_api_hybrid_recall_ranks_text_and_graph_results(tmp_path) -> None:
    """Hybrid recall includes both result types and orders by live decay score."""
    api = RecallWeaverAPI(str(tmp_path / "hybrid.db"))
    api.remember_triple("张三", "认识", "李四")
    high_id = api.add_memory("张三 重要项目")
    low_id = api.add_memory("张三 普通备注")

    with api.database_manager.get_connection() as connection:
        connection.execute(
            "UPDATE memories SET base_weight = ? WHERE id = ?",
            (10.0, high_id),
        )
        connection.execute(
            "UPDATE memories SET base_weight = ? WHERE id = ?",
            (1.0, low_id),
        )

    results = api.recall("张三", limit=10)

    assert results
    assert all(isinstance(result, MemoryOut) for result in results)
    assert {result.result_type for result in results} == {"memory", "graph"}
    text_results = [result for result in results if result.result_type == "memory"]
    assert text_results[0].memory_id == high_id
    assert text_results[1].memory_id == low_id
    assert text_results[0].score > text_results[1].score
    assert all(result.valid_from is not None for result in results)
    assert [result.score for result in results] == sorted(
        (result.score for result in results),
        reverse=True,
    )


def test_cli_execution(tmp_path, monkeypatch) -> None:
    """CLI commands persist facts and render rich recall and history views."""
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "cli.db"))
    runner = CliRunner()

    add_result = runner.invoke(cli, ["add", "张三 住在 北京"])
    assert add_result.exit_code == 0
    assert "✅ 成功: 记忆已写入，ID:" in add_result.output
    assert "事实已保存" in add_result.output

    recall_result = runner.invoke(cli, ["recall", "张三"])
    assert recall_result.exit_code == 0
    assert "得分(渐变)" in recall_result.output
    assert "Trace ID" in recall_result.output
    assert "记忆内容" in recall_result.output
    assert "生效时间" in recall_result.output

    update_result = runner.invoke(cli, ["add", "张三 住在 上海"])
    assert update_result.exit_code == 0

    history_result = runner.invoke(cli, ["history", "张三", "住在"])
    assert history_result.exit_code == 0
    assert "[❌ 失效]" in history_result.output
    assert "[✅ 有效]" in history_result.output
    assert "valid_from=" in history_result.output
    assert "valid_to=" in history_result.output

    invalid_result = runner.invoke(cli, ["add", "不完整事实"])
    assert invalid_result.exit_code == 1
    assert "Error [RW-VALIDATION]:" in invalid_result.output

    invalid_limit = runner.invoke(cli, ["recall", "张三", "--limit", "-1"])
    assert invalid_limit.exit_code == 1
    assert "Error [RW-VALIDATION]:" in invalid_limit.output


def test_api_validation_error(tmp_path) -> None:
    """Empty graph fields are translated to the project validation exception."""
    api = RecallWeaverAPI(str(tmp_path / "validation.db"))

    with pytest.raises(ValidationError):
        api.remember_triple("", "认识", "李四")
