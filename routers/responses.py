from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from models import FeedbackResponse, FeedbackAnswer, FeedbackQuestion
from schemas import ResponseOut, ResponseListOut, AnswerOut, AnalyticsOut
from dependencies import get_db, get_current_user, require_org_access, get_user_branch_ids, CurrentUser
from services.analytics import get_analytics, compute_response_score

router = APIRouter(prefix="/organizations/{org_id}/feedback", tags=["Feedback · Responses"])


@router.get("/responses", response_model=ResponseListOut)
def list_responses(
    org_id: int,
    survey_id: Optional[int] = Query(None),
    branch_id: Optional[int] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_org_access(current_user, org_id)
    allowed_branches = get_user_branch_ids(current_user, org_id, db)

    org_survey_ids = [
        r[0] for r in db.execute(
            text("SELECT id FROM feedback_surveys WHERE organization_id=:oid"),
            {"oid": org_id}
        ).fetchall()
    ]
    if survey_id:
        org_survey_ids = [s for s in org_survey_ids if s == survey_id]

    query = db.query(FeedbackResponse).filter(
        FeedbackResponse.survey_id.in_(org_survey_ids)
    )

    if branch_id:
        query = query.filter(FeedbackResponse.branch_id == branch_id)
    if allowed_branches is not None:
        query = query.filter(FeedbackResponse.branch_id.in_(allowed_branches))
    if start_date:
        query = query.filter(FeedbackResponse.created_at >= start_date)
    if end_date:
        query = query.filter(FeedbackResponse.created_at <= end_date + " 23:59:59")

    total = query.count()
    responses = (
        query.order_by(FeedbackResponse.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    result = []
    for resp in responses:
        answers = (
            db.query(FeedbackAnswer, FeedbackQuestion)
            .join(FeedbackQuestion, FeedbackQuestion.id == FeedbackAnswer.question_id)
            .filter(FeedbackAnswer.response_id == resp.id)
            .all()
        )
        score = compute_response_score(db, resp.id)

        branch_name = None
        if resp.branch_id:
            row = db.execute(
                text("SELECT name FROM branches WHERE id=:id"),
                {"id": resp.branch_id}
            ).first()
            if row:
                branch_name = row[0]

        result.append(ResponseOut(
            id=resp.id,
            branch_name=branch_name,
            created_at=resp.created_at,
            device_type=resp.device_type,
            satisfaction_score=score,
            answers=[
                AnswerOut(
                    question_id=a.question_id,
                    question_text=q.text,
                    type=q.type,
                    value_num=float(a.value_num) if a.value_num is not None else None,
                    value_text=a.value_text,
                )
                for a, q in answers
            ]
        ))

    return ResponseListOut(total=total, page=page, per_page=per_page, responses=result)


@router.get("/analytics", response_model=AnalyticsOut)
def get_analytics_endpoint(
    org_id: int,
    survey_id: Optional[int] = Query(None),
    branch_id: Optional[int] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    granularity: str = Query("daily"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_org_access(current_user, org_id)
    allowed_branches = get_user_branch_ids(current_user, org_id, db)
    branch_ids = [branch_id] if branch_id else allowed_branches

    sd = date.fromisoformat(start_date) if start_date else date.today().replace(day=1)
    ed = date.fromisoformat(end_date) if end_date else date.today()

        try:
        return get_analytics(db, org_id, survey_id, branch_ids, sd, ed, granularity)
    except Exception as e:
        return {
            "total_responses": 0,
            "responses_today": 0,
            "active_surveys": 0,
            "satisfaction_score": None,
            "by_question": [],
            "by_branch": [],
            "stars_distribution": {"1":0,"2":0,"3":0,"4":0,"5":0},
            "time_series": []
        }
    except Exception:
        from schemas import AnalyticsOut
        return AnalyticsOut(
            total_responses=0,
            responses_today=0,
            active_surveys=0,
            satisfaction_score=None,
            by_question=[],
            by_branch=[],
            stars_distribution={1:0,2:0,3:0,4:0,5:0},
            time_series=[],
        )

