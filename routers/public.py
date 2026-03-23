"""
feedback/routers/public.py
Public endpoints — no authentication required.
These serve the QR page that end customers see on their mobile devices.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from models import (
    FeedbackSurvey, FeedbackQuestion, FeedbackResponse,
    FeedbackAnswer, FeedbackConfig,
)
from schemas import (
    PublicSurveyOut, PublicBrandingOut, PublicBranchOut, PublicQuestionOut,
    ResponseCreate, ResponseCreatedOut,
)
from dependencies import get_db
from services.analytics import compute_response_score

router = APIRouter(prefix="/public/feedback", tags=["Feedback · Public QR"])


def _get_survey_by_token(db: Session, qr_token: str) -> FeedbackSurvey:
    survey = db.query(FeedbackSurvey).filter(
        FeedbackSurvey.qr_token == qr_token,
        FeedbackSurvey.is_active == True,
    ).first()
    if not survey:
        raise HTTPException(
            status_code=404,
            detail="Survey not found or inactive"
        )
    return survey


@router.get("/{qr_token}", response_model=PublicSurveyOut)
def get_public_survey(qr_token: str, db: Session = Depends(get_db)):
    """
    Returns everything the QR page needs to render:
    - Survey info and thank-you message
    - Organization branding (color, name, welcome message)
    - Active branches (so the customer can pick their location)
    - Active questions in sorted order

    No authentication required — this is the public customer-facing page.
    """
    survey = _get_survey_by_token(db, qr_token)

    # Get branding config for this org (fallback to defaults if not configured)
    config = db.query(FeedbackConfig).filter(
        FeedbackConfig.organization_id == survey.organization_id
    ).first()

    # Get org name from existing organizations table
    from sqlalchemy import text
    org_row = db.execute(
        text("SELECT name FROM organizations WHERE id = :id"),
        {"id": survey.organization_id}
    ).first()
    org_name = config.brand_name if config and config.brand_name else (org_row[0] if org_row else "")

    branding = PublicBrandingOut(
        name=org_name,
        brand_color=config.brand_color if config else "#FAD51B",
        welcome_msg=config.welcome_msg if config else "Tu opinión nos importa. Solo tardas 30 segundos.",
        show_powered_by=config.show_powered_by if config else True,
    )

    # Get all active branches for this org
    # Only show branches assigned to this survey (if any assigned, otherwise show all)
    assigned = db.execute(
        text("""
            SELECT b.id, b.name FROM feedback_survey_branches sb
            JOIN branches b ON b.id = sb.branch_id
            WHERE sb.survey_id = :sid AND b.is_active = true
            ORDER BY b.name
        """),
        {"sid": survey.id}
    ).fetchall()
    if assigned:
        branches = [PublicBranchOut(id=r[0], name=r[1]) for r in assigned]
    else:
        branches_rows = db.execute(
            text("SELECT id, name FROM branches WHERE organization_id = :org_id AND is_active = true ORDER BY name"),
            {"org_id": survey.organization_id}
        ).fetchall()
        branches = [PublicBranchOut(id=r[0], name=r[1]) for r in branches_rows]

    # Get active questions sorted by sort_order
    questions = (
        db.query(FeedbackQuestion)
        .filter(
            FeedbackQuestion.survey_id == survey.id,
            FeedbackQuestion.is_active == True,
        )
        .order_by(FeedbackQuestion.sort_order)
        .all()
    )

    return PublicSurveyOut(
        survey_id=survey.id,
        survey_name=survey.name,
        thank_you_msg=survey.thank_you_msg,
        organization=branding,
        branches=branches,
        questions=[
            PublicQuestionOut(
                id=q.id,
                text=q.text,
                type=q.type,
                sort_order=q.sort_order,
            )
            for q in questions
        ],
    )


@router.post("/{qr_token}/responses", response_model=ResponseCreatedOut, status_code=status.HTTP_201_CREATED)
def submit_response(
    qr_token: str,
    body: ResponseCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Save an anonymous survey response.
    PRIVACY: We only store device_type and branch_id — never IP or user-agent.
    """
    survey = _get_survey_by_token(db, qr_token)

    # Validate question IDs belong to this survey
    valid_q_ids = {
        q.id for q in db.query(FeedbackQuestion.id).filter(
            FeedbackQuestion.survey_id == survey.id,
            FeedbackQuestion.is_active == True,
        ).all()
    }
    for ans in body.answers:
        if ans.question_id not in valid_q_ids:
            raise HTTPException(
                status_code=422,
                detail=f"Question {ans.question_id} does not belong to this survey"
            )

    # Validate branch_id belongs to this org if provided
    if body.branch_id is not None:
        from sqlalchemy import text
        branch_exists = db.execute(
            text("SELECT 1 FROM branches WHERE id = :id AND organization_id = :org_id"),
            {"id": body.branch_id, "org_id": survey.organization_id}
        ).first()
        if not branch_exists:
            raise HTTPException(status_code=422, detail="Invalid branch_id")

    # Freemium rate limit check
    from services.limits import check_response_limit
    check_response_limit(db, survey.organization_id)

    # Create response session (anonymous — no PII stored)
    response = FeedbackResponse(
        survey_id=survey.id,
        branch_id=body.branch_id,
        device_type=body.device_type,
        # Intentionally NOT storing: IP, user-agent, session ID, any PII
    )
    db.add(response)
    db.flush()  # get response.id before inserting answers

    # Save individual answers
    for ans in body.answers:
        answer = FeedbackAnswer(
            response_id=response.id,
            question_id=ans.question_id,
            value_num=ans.value_num,
            value_text=ans.value_text,
        )
        db.add(answer)

    db.commit()
    db.refresh(response)

    # Calculate score for this specific response
    score = compute_response_score(db, response.id)

    return ResponseCreatedOut(
        response_id=response.id,
        message="Respuesta registrada. ¡Gracias!",
        satisfaction_score=score,
    )
