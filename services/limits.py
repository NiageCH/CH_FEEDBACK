"""
feedback/services/limits.py
Freemium plan limit checks.
Raises HTTP 403/429 with structured error bodies when a limit is exceeded.
"""

import os
from datetime import date
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func, extract

from models import FeedbackSurvey, FeedbackResponse

FREEMIUM_SURVEYS_LIMIT   = int(os.getenv("FEEDBACK_FREEMIUM_SURVEYS_LIMIT", 1))
FREEMIUM_RESPONSES_LIMIT = int(os.getenv("FEEDBACK_FREEMIUM_RESPONSE_LIMIT", 100))
FREEMIUM_USERS_LIMIT     = int(os.getenv("FEEDBACK_FREEMIUM_USERS_LIMIT", 2))


def _get_org_plan(db: Session, org_id: int) -> str:
    """
    Get the current plan for an organization.
    Reads from your existing organizations/tenants table.
    Replace with your actual plan field.
    """
    from sqlalchemy import text
    row = db.execute(
        text("SELECT plan FROM organizations WHERE id = :id"),
        {"id": org_id}
    ).first()
    return row[0] if row else "freemium"


def check_survey_limit(db: Session, org_id: int) -> None:
    """Raise 403 if the org has reached its active survey limit."""
    plan = _get_org_plan(db, org_id)
    if plan != "freemium":
        return   # paid plan — no limit

    active_count = db.query(func.count(FeedbackSurvey.id)).filter(
        FeedbackSurvey.organization_id == org_id,
        FeedbackSurvey.is_active == True,
    ).scalar() or 0

    if active_count >= FREEMIUM_SURVEYS_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "PLAN_LIMIT_SURVEYS",
                "message": f"Freemium plan allows {FREEMIUM_SURVEYS_LIMIT} active survey(s).",
                "used": active_count,
                "limit": FREEMIUM_SURVEYS_LIMIT,
            }
        )


def check_response_limit(db: Session, org_id: int) -> None:
    """Raise 429 if the org has reached its monthly response limit."""
    plan = _get_org_plan(db, org_id)
    if plan != "freemium":
        return

    today = date.today()
    monthly_count = (
        db.query(func.count(FeedbackResponse.id))
        .join(FeedbackSurvey, FeedbackSurvey.id == FeedbackResponse.survey_id)
        .filter(
            FeedbackSurvey.organization_id == org_id,
            extract("year",  FeedbackResponse.created_at) == today.year,
            extract("month", FeedbackResponse.created_at) == today.month,
        )
        .scalar() or 0
    )

    if monthly_count >= FREEMIUM_RESPONSES_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "PLAN_LIMIT_RESPONSES",
                "message": f"Freemium plan allows {FREEMIUM_RESPONSES_LIMIT} responses/month.",
                "used": monthly_count,
                "limit": FREEMIUM_RESPONSES_LIMIT,
            }
        )


def check_user_limit(db: Session, org_id: int) -> None:
    """Raise 403 if the org has reached its user limit."""
    plan = _get_org_plan(db, org_id)
    if plan != "freemium":
        return

    from sqlalchemy import text
    user_count = db.execute(
        text("SELECT COUNT(*) FROM users WHERE organization_id = :org_id AND is_active = true"),
        {"org_id": org_id}
    ).scalar() or 0

    if user_count >= FREEMIUM_USERS_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "PLAN_LIMIT_USERS",
                "message": f"Freemium plan allows {FREEMIUM_USERS_LIMIT} users.",
                "used": user_count,
                "limit": FREEMIUM_USERS_LIMIT,
            }
        )
