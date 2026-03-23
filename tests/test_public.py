"""
tests/test_public.py
Tests for public QR endpoints (no auth required).
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from ..main import app
from ..models import (
    FeedbackSurvey, FeedbackQuestion, FeedbackResponse,
    FeedbackAnswer, FeedbackConfig,
)

client = TestClient(app)


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _mock_survey(qr_token="test-token-abc123", is_active=True):
    survey = MagicMock(spec=FeedbackSurvey)
    survey.id = 1
    survey.organization_id = 3
    survey.name = "Encuesta de satisfacción"
    survey.qr_token = qr_token
    survey.thank_you_msg = "¡Gracias!"
    survey.is_active = is_active
    return survey


def _mock_question(qid=1, q_type="stars"):
    q = MagicMock(spec=FeedbackQuestion)
    q.id = qid
    q.survey_id = 1
    q.text = "¿Cómo fue tu experiencia?"
    q.type = q_type
    q.sort_order = 1
    q.is_active = True
    return q


def _setup_db_mock(db_mock, survey=None, questions=None, config=None):
    """Configure the mock DB session to return appropriate data."""
    survey = survey or _mock_survey()
    questions = questions or [_mock_question()]

    def query_side_effect(model):
        mock_query = MagicMock()

        if model == FeedbackSurvey:
            mock_filter = MagicMock()
            mock_filter.first.return_value = survey
            mock_query.filter.return_value = mock_filter
            return mock_query

        if model == FeedbackConfig:
            mock_filter = MagicMock()
            mock_filter.first.return_value = config
            mock_query.filter.return_value = mock_filter
            return mock_query

        if model == FeedbackQuestion:
            # For active questions query
            mock_filter = MagicMock()
            mock_order = MagicMock()
            mock_order.all.return_value = questions
            mock_filter.order_by.return_value = mock_order
            mock_query.filter.return_value = mock_filter
            return mock_query

        if model == FeedbackQuestion.id:
            # For valid question IDs check
            mock_filter = MagicMock()
            mock_filter.all.return_value = [(q.id,) for q in questions]
            mock_query.filter.return_value = mock_filter
            return mock_query

        return mock_query

    db_mock.query.side_effect = query_side_effect

    # Mock execute for raw SQL queries (org name, branches)
    def execute_side_effect(stmt, params=None):
        result = MagicMock()
        query_str = str(stmt) if hasattr(stmt, 'text') else str(stmt)
        if "organizations" in query_str:
            result.first.return_value = ("Nova Moda",)
        elif "branches" in query_str and "SELECT id, name" in query_str:
            result.fetchall.return_value = [(1, "Tienda Centro"), (2, "Tienda Norte")]
        elif "branches" in query_str and "SELECT 1" in query_str:
            result.first.return_value = (1,)
        else:
            result.first.return_value = None
            result.fetchall.return_value = []
        return result

    db_mock.execute.side_effect = execute_side_effect


# ── Tests ────────────────────────────────────────────────────────────────────

@patch("feedback.dependencies.get_db")
def test_get_public_survey_valid_token(mock_get_db):
    """GET /api/v1/public/feedback/{token} with valid token returns 200."""
    db = MagicMock()
    mock_get_db.return_value = iter([db])
    _setup_db_mock(db)

    # Override the dependency
    app.dependency_overrides[__import__("feedback.dependencies", fromlist=["get_db"]).get_db] = lambda: db

    response = client.get("/api/v1/public/feedback/test-token-abc123")

    # Cleanup
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["survey_id"] == 1
    assert data["survey_name"] == "Encuesta de satisfacción"
    assert "questions" in data
    assert "organization" in data


@patch("feedback.dependencies.get_db")
def test_get_public_survey_invalid_token(mock_get_db):
    """GET /api/v1/public/feedback/invalid-token returns 404."""
    db = MagicMock()
    mock_get_db.return_value = iter([db])

    # Survey not found
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.first.return_value = None
    mock_query.filter.return_value = mock_filter
    db.query.return_value = mock_query

    from ..dependencies import get_db as real_get_db
    app.dependency_overrides[real_get_db] = lambda: db

    response = client.get("/api/v1/public/feedback/invalid-token")

    app.dependency_overrides.clear()

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@patch("feedback.dependencies.get_db")
@patch("feedback.services.limits.check_response_limit")
@patch("feedback.services.analytics.compute_response_score")
def test_submit_response_valid(mock_score, mock_limit, mock_get_db):
    """POST /api/v1/public/feedback/{token}/responses with valid data returns 201."""
    db = MagicMock()
    mock_get_db.return_value = iter([db])

    survey = _mock_survey()
    questions = [_mock_question(qid=10, q_type="stars")]
    _setup_db_mock(db, survey=survey, questions=questions)

    # Mock flush to assign ID
    def flush_side_effect():
        pass
    db.flush.side_effect = flush_side_effect

    # Mock the FeedbackResponse creation
    mock_response = MagicMock()
    mock_response.id = 42
    db.refresh.side_effect = lambda obj: setattr(obj, 'id', 42)

    mock_score.return_value = 75.0
    mock_limit.return_value = None

    from ..dependencies import get_db as real_get_db
    app.dependency_overrides[real_get_db] = lambda: db

    response = client.post(
        "/api/v1/public/feedback/test-token-abc123/responses",
        json={
            "branch_id": 1,
            "device_type": "mobile",
            "answers": [
                {"question_id": 10, "value_num": 4.0}
            ],
        },
    )

    app.dependency_overrides.clear()

    assert response.status_code == 201
    data = response.json()
    assert "response_id" in data
    assert data["message"] == "Respuesta registrada. ¡Gracias!"
