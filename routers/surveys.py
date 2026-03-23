from typing import Optional, List, Literal
"""
feedback/routers/surveys.py
CRUD endpoints for surveys and questions.
"""

import secrets
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from models import FeedbackSurvey, FeedbackQuestion
from schemas import (
    SurveyCreate, SurveyUpdate, SurveyOut, SurveyDetail,
    QuestionCreate, QuestionUpdate, QuestionOut,
)
from dependencies import (
    get_db, get_current_user, require_role,
    require_org_access, CurrentUser,
)

router = APIRouter(prefix="/organizations/{org_id}/feedback", tags=["Feedback · Surveys"])

FEEDBACK_BASE_URL = "https://democba.niage.es/feedback"   # move to settings


# ── Helper ────────────────────────────────────────────────────────────────────

def _generate_qr_token() -> str:
    """Generate a cryptographically secure, URL-safe 32-char token."""
    return secrets.token_urlsafe(24)[:32]


def _survey_or_404(db: Session, survey_id: int, org_id: int) -> FeedbackSurvey:
    survey = db.query(FeedbackSurvey).filter(
        FeedbackSurvey.id == survey_id,
        FeedbackSurvey.organization_id == org_id,
    ).first()
    if not survey:
        raise HTTPException(status_code=404, detail="Survey not found")
    return survey


def _build_qr_url(token: str) -> str:
    return f"{FEEDBACK_BASE_URL}/{token}"


def _satisfaction_score(db: Session, survey_id: int) -> Optional[float]:
    """Calculate overall satisfaction score (0-100) for a survey."""
    from models import FeedbackAnswer, FeedbackQuestion as Q
    rows = (
        db.query(Q.type, FeedbackAnswer.value_num)
        .join(FeedbackAnswer, FeedbackAnswer.question_id == Q.id)
        .filter(Q.survey_id == survey_id, Q.type.in_(["stars", "nps", "yesno"]))
        .all()
    )
    if not rows:
        return None
    scores = []
    for q_type, val in rows:
        if val is None:
            continue
        if q_type == "stars":
            scores.append((float(val) - 1) / 4 * 100)
        elif q_type == "nps":
            scores.append(float(val) / 10 * 100)
        elif q_type == "yesno":
            scores.append(float(val) * 100)
    return round(sum(scores) / len(scores), 1) if scores else None


# ── Survey endpoints ──────────────────────────────────────────────────────────

@router.get("/surveys", response_model=list[SurveyOut])
def list_surveys(
    org_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_org_access(current_user, org_id)
    surveys = (
        db.query(FeedbackSurvey)
        .filter(FeedbackSurvey.organization_id == org_id)
        .order_by(FeedbackSurvey.created_at.desc())
        .all()
    )
    result = []
    for s in surveys:
        q_count = db.query(func.count(FeedbackQuestion.id)).filter(
            FeedbackQuestion.survey_id == s.id,
            FeedbackQuestion.is_active == True,
        ).scalar()
        from models import FeedbackResponse
        r_count = db.query(func.count(FeedbackResponse.id)).filter(
            FeedbackResponse.survey_id == s.id
        ).scalar()
        result.append(SurveyOut(
            **{c.name: getattr(s, c.name) for c in s.__table__.columns},
            qr_url=_build_qr_url(s.qr_token),
            questions_count=q_count or 0,
            responses_count=r_count or 0,
            satisfaction_score=_satisfaction_score(db, s.id),
        ))
    return result


@router.post("/surveys", response_model=SurveyOut, status_code=status.HTTP_201_CREATED)
def create_survey(
    org_id: int,
    body: SurveyCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_role(current_user, ["ADMIN", "SUPERADMIN"])
    require_org_access(current_user, org_id)

    # Freemium check — max 1 active survey
    from services.limits import check_survey_limit
    check_survey_limit(db, org_id)

    token = _generate_qr_token()
    survey = FeedbackSurvey(
        organization_id=org_id,
        name=body.name,
        qr_token=token,
        thank_you_msg=body.thank_you_msg or "¡Gracias por tu opinión!",
    )
    db.add(survey)
    db.commit()
    db.refresh(survey)

    return SurveyOut(
        **{c.name: getattr(survey, c.name) for c in survey.__table__.columns},
        qr_url=_build_qr_url(token),
        questions_count=0,
        responses_count=0,
    )


@router.get("/surveys/{survey_id}", response_model=SurveyDetail)
def get_survey(
    org_id: int,
    survey_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_org_access(current_user, org_id)
    survey = _survey_or_404(db, survey_id, org_id)
    questions = (
        db.query(FeedbackQuestion)
        .filter(FeedbackQuestion.survey_id == survey_id)
        .order_by(FeedbackQuestion.sort_order)
        .all()
    )
    cols = {c.name: getattr(survey, c.name) for c in survey.__table__.columns}
    return SurveyDetail(
        **cols,
        qr_url=_build_qr_url(survey.qr_token),
        questions_count=sum(1 for q in questions if q.is_active),
        responses_count=0,
        questions=[QuestionOut(
            id=q.id, survey_id=q.survey_id, text=q.text,
            type=q.type, sort_order=q.sort_order,
            is_active=q.is_active, created_at=q.created_at
        ) for q in questions],
    )


@router.put("/surveys/{survey_id}", response_model=SurveyOut)
def update_survey(
    org_id: int,
    survey_id: int,
    body: SurveyUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_role(current_user, ["ADMIN", "MANAGER", "SUPERADMIN"])
    require_org_access(current_user, org_id)
    survey = _survey_or_404(db, survey_id, org_id)

    if body.name is not None:
        survey.name = body.name
    if body.thank_you_msg is not None:
        survey.thank_you_msg = body.thank_you_msg
    if body.is_active is not None:
        survey.is_active = body.is_active

    db.commit()
    db.refresh(survey)
    return SurveyOut(
        **{c.name: getattr(survey, c.name) for c in survey.__table__.columns},
        qr_url=_build_qr_url(survey.qr_token),
    )


@router.delete("/surveys/{survey_id}", status_code=status.HTTP_200_OK)
def deactivate_survey(
    org_id: int,
    survey_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_role(current_user, ["ADMIN", "SUPERADMIN"])
    require_org_access(current_user, org_id)
    survey = _survey_or_404(db, survey_id, org_id)
    survey.is_active = False
    db.commit()
    return {"message": "Survey deactivated"}


# ── Question endpoints ────────────────────────────────────────────────────────

@router.get("/surveys/{survey_id}/questions", response_model=list[QuestionOut])
def list_questions(
    org_id: int,
    survey_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_org_access(current_user, org_id)
    _survey_or_404(db, survey_id, org_id)
    return (
        db.query(FeedbackQuestion)
        .filter(FeedbackQuestion.survey_id == survey_id)
        .order_by(FeedbackQuestion.sort_order)
        .all()
    )


@router.post(
    "/surveys/{survey_id}/questions",
    response_model=QuestionOut,
    status_code=status.HTTP_201_CREATED,
)
def add_question(
    org_id: int,
    survey_id: int,
    body: QuestionCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_role(current_user, ["ADMIN", "MANAGER", "SUPERADMIN"])
    require_org_access(current_user, org_id)
    _survey_or_404(db, survey_id, org_id)

    if body.sort_order is None:
        max_order = db.query(func.max(FeedbackQuestion.sort_order)).filter(
            FeedbackQuestion.survey_id == survey_id
        ).scalar() or 0
        sort_order = max_order + 1
    else:
        sort_order = body.sort_order

    question = FeedbackQuestion(
        survey_id=survey_id,
        text=body.text,
        type=body.type,
        sort_order=sort_order,
    )
    db.add(question)
    db.commit()
    db.refresh(question)
    return question


@router.put("/surveys/{survey_id}/questions/{question_id}", response_model=QuestionOut)
def update_question(
    org_id: int,
    survey_id: int,
    question_id: int,
    body: QuestionUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_role(current_user, ["ADMIN", "MANAGER", "SUPERADMIN"])
    require_org_access(current_user, org_id)
    _survey_or_404(db, survey_id, org_id)

    question = db.query(FeedbackQuestion).filter(
        FeedbackQuestion.id == question_id,
        FeedbackQuestion.survey_id == survey_id,
    ).first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    if body.text       is not None: question.text       = body.text
    if body.type       is not None: question.type       = body.type
    if body.sort_order is not None: question.sort_order = body.sort_order
    if body.is_active  is not None: question.is_active  = body.is_active

    db.commit()
    db.refresh(question)
    return question


@router.delete("/surveys/{survey_id}/questions/{question_id}", status_code=status.HTTP_200_OK)
def delete_question(
    org_id: int,
    survey_id: int,
    question_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_role(current_user, ["ADMIN", "MANAGER", "SUPERADMIN"])
    require_org_access(current_user, org_id)
    _survey_or_404(db, survey_id, org_id)

    question = db.query(FeedbackQuestion).filter(
        FeedbackQuestion.id == question_id,
        FeedbackQuestion.survey_id == survey_id,
    ).first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    question.is_active = False
    db.commit()
    return {"message": "Question deactivated"}


@router.get("/surveys/{survey_id}/branches")
def get_survey_branches(org_id: int, survey_id: int, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    from sqlalchemy import text as sqla_text
    require_org_access(current_user, org_id)
    _survey_or_404(db, survey_id, org_id)
    assigned = db.execute(sqla_text("SELECT b.id, b.name FROM feedback_survey_branches sb JOIN branches b ON b.id=sb.branch_id WHERE sb.survey_id=:sid ORDER BY b.name"), {"sid": survey_id}).fetchall()
    available = db.execute(sqla_text("SELECT id, name FROM branches WHERE organization_id=:oid ORDER BY name"), {"oid": org_id}).fetchall()
    aids = [r[0] for r in assigned]
    return {"survey_id": survey_id, "assigned": [{"id": r[0], "name": r[1]} for r in assigned], "available": [{"id": r[0], "name": r[1]} for r in available], "assigned_ids": aids}

@router.put("/surveys/{survey_id}/branches")
def update_survey_branches(org_id: int, survey_id: int, body: dict, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    from sqlalchemy import text as sqla_text
    require_role(current_user, ["ADMIN", "MANAGER", "SUPERADMIN"])
    require_org_access(current_user, org_id)
    _survey_or_404(db, survey_id, org_id)
    branch_ids = body.get("branch_ids", [])
    db.execute(sqla_text("DELETE FROM feedback_survey_branches WHERE survey_id=:sid"), {"sid": survey_id})
    for bid in branch_ids:
        db.execute(sqla_text("INSERT INTO feedback_survey_branches (survey_id, branch_id) VALUES (:sid,:bid) ON CONFLICT DO NOTHING"), {"sid": survey_id, "bid": bid})
    db.commit()
    return {"survey_id": survey_id, "branch_ids": branch_ids}

@router.put("/surveys/{survey_id}/branches")
def update_survey_branches(
    org_id: int,
    survey_id: int,
    body: dict,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Assign branches to a survey. Replaces existing assignment."""
    require_role(current_user, ["ADMIN", "MANAGER", "SUPERADMIN"])
    require_org_access(current_user, org_id)
    _survey_or_404(db, survey_id, org_id)

    branch_ids = body.get("branch_ids", [])
    db.execute(
        text("DELETE FROM feedback_survey_branches WHERE survey_id=:sid"),
        {"sid": survey_id}
    )
    for bid in branch_ids:
        db.execute(
            text("INSERT INTO feedback_survey_branches (survey_id, branch_id) VALUES (:sid,:bid) ON CONFLICT DO NOTHING"),
            {"sid": survey_id, "bid": bid}
        )
    db.commit()
    return {"survey_id": survey_id, "branch_ids": branch_ids, "message": "Branches updated"}
