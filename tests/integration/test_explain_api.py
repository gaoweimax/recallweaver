"""Integration tests for the memory-recall explanation endpoint."""

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from recallweaver.api import RecallWeaverAPI
from recallweaver.server import ServerSettings, create_app


def test_explain_api_returns_memory_score_and_hit_reason(
    tmp_path: Path,
) -> None:
    """Explain returns its score and retrieval reason without external services."""
    db_path = str(tmp_path / "explain-api.sqlite3")
    api = RecallWeaverAPI(db_path)
    api.add_memory("大肥鱼今天很开心", tenant_id="default")
    app = create_app(
        api=api,
        service_settings=ServerSettings(db_path=db_path),
    )

    with patch("recallweaver.server.AsyncOpenAI") as openai_client:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/memory/explain",
                params={"query": "大肥鱼"},
            )

    openai_client.assert_not_called()
    assert response.status_code == 200
    results = response.json()
    assert results
    assert "大肥鱼" in results[0]["content"]
    assert isinstance(results[0]["score"], (int, float))
    assert "hit_reason" in results[0]
    assert "FTS5" in results[0]["hit_reason"]
    assert results[0]["valid_to"] is None
