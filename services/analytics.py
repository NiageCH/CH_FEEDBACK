"""
feedback/services/analytics.py
Satisfaction score calculation logic.

Formula:
  stars  → (value - 1) / 4 * 100   [1★ = 0%,  5★ = 100%]
  nps    → value / 10 * 100         [0  = 0%,  10  = 100%]
  yesno  → value * 100              [0  = 0%,  1   = 100%]
  text   → excluded from score calculation

  Overall = simple average of all quantifiable answer scores
"""

from __future__ import annotations
from datetime import date, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, extract

from models import (
    FeedbackSurvey, FeedbackQuestion, FeedbackResponse, FeedbackAnswer,
)
from schemas import (
    AnalyticsOut, OverallAnalytics, QuestionAnalytics,
    BranchAnalytics, TimeSeriesPoint,
)


def _score_from_type(q_type: str, value: float) -> Optional[float]:
    if q_type == "stars":
        return (value - 1) / 4 * 100
    elif q_type == "nps":
        return value / 10 * 100
    elif q_type == "yesno":
        return value * 100
    return None   # text questions are excluded


def compute_response_score(db: Session, response_id: int) -> Optional[float]:
    """Calculate satisfaction score (0-100) for a single response session."""
    rows = (
        db.query(FeedbackQuestion.type, FeedbackAnswer.value_num)
        .join(FeedbackAnswer, FeedbackAnswer.question_id == FeedbackQuestion.id)
        .filter(
            FeedbackAnswer.response_id == response_id,
            FeedbackQuestion.type.in_(["stars", "nps", "yesno"]),
            FeedbackAnswer.value_num.isnot(None),
        )
        .all()
    )
    if not rows:
        return None
    scores = [s for t, v in rows if (s := _score_from_type(t, float(v))) is not None]
    return round(sum(scores) / len(scores), 1) if scores else None


def get_analytics(
    db: Session,
    org_id: int,
    survey_id: Optional[int],
    branch_ids: Optional[list[int]],
    start_date: date,
    end_date: date,
    granularity: str,
) -> AnalyticsOut:
    """Full analytics computation for the dashboard."""

    # Base filters
    base_filter = [
        FeedbackSurvey.organization_id == org_id,
        FeedbackResponse.created_at >= start_date,
        FeedbackResponse.created_at <= end_date,
    ]
    if survey_id:
        base_filter.append(FeedbackResponse.survey_id == survey_id)
    if branch_ids:
        base_filter.append(FeedbackResponse.branch_id.in_(branch_ids))

    # Total responses
    # Get survey IDs for this org first, then filter responses directly
    org_survey_ids = [
        r[0] for r in db.execute(
            text("SELECT id FROM feedback_surveys WHERE organization_id=:oid AND is_active=true"),
            {"oid": org_id}
        ).fetchall()
    ]
    if survey_id:
        org_survey_ids = [s for s in org_survey_ids if s == survey_id]

    total_responses = (
        db.query(func.count(FeedbackResponse.id))
        .filter(
            FeedbackResponse.survey_id.in_(org_survey_ids),
            FeedbackResponse.created_at >= start_date,
            FeedbackResponse.created_at <= end_date,
            *([FeedbackResponse.branch_id.in_(branch_ids)] if branch_ids else [])
        )
        .scalar() or 0
    )

    # Responses today
    today = date.today()
    responses_today = (
        db.query(func.count(FeedbackResponse.id))
        .join(FeedbackSurvey, FeedbackSurvey.id == FeedbackResponse.survey_id)
        .filter(
            FeedbackSurvey.organization_id == org_id,
            func.date(FeedbackResponse.created_at) == today,
        )
        .scalar() or 0
    )

    # All quantifiable answers for this period
    answers_query = (
        db.query(FeedbackQuestion.id, FeedbackQuestion.type, FeedbackAnswer.value_num)
        .join(FeedbackAnswer, FeedbackAnswer.question_id == FeedbackQuestion.id)
        .join(FeedbackResponse, FeedbackResponse.id == FeedbackAnswer.response_id)
        .filter(
            FeedbackResponse.survey_id.in_(org_survey_ids),
            FeedbackResponse.created_at >= start_date,
            FeedbackResponse.created_at <= end_date,
            FeedbackAnswer.value_num.isnot(None),
            *([FeedbackResponse.branch_id.in_(branch_ids)] if branch_ids else [])
        )
        .all()
    )

    # Overall satisfaction score
    all_scores = [
        s for _, q_type, v in answers_query
        if (s := _score_from_type(q_type, float(v))) is not None
    ]
    overall_score = round(sum(all_scores) / len(all_scores), 1) if all_scores else 0.0

    # Trend: compare to previous period of same length
    period_days = (end_date - start_date).days or 1
    prev_start = start_date - timedelta(days=period_days)
    prev_answers = (
        db.query(FeedbackQuestion.type, FeedbackAnswer.value_num)
        .join(FeedbackAnswer, FeedbackAnswer.question_id == FeedbackQuestion.id)
        .join(FeedbackResponse, FeedbackResponse.id == FeedbackAnswer.response_id)
        .join(FeedbackSurvey, FeedbackSurvey.id == FeedbackResponse.survey_id)
        .filter(
            FeedbackSurvey.organization_id == org_id,
            FeedbackResponse.created_at >= prev_start,
            FeedbackResponse.created_at < start_date,
            FeedbackAnswer.value_num.isnot(None),
        )
        .all()
    )
    prev_scores = [s for t, v in prev_answers if (s := _score_from_type(t, float(v))) is not None]
    prev_score = sum(prev_scores) / len(prev_scores) if prev_scores else None
    if prev_score and prev_score > 0:
        trend_pct = ((overall_score - prev_score) / prev_score) * 100
        trend = f"{'+' if trend_pct >= 0 else ''}{trend_pct:.1f}%"
    else:
        trend = "N/A"

    # Per-question breakdown
    questions = (
        db.query(FeedbackQuestion)
        .join(FeedbackSurvey, FeedbackSurvey.id == FeedbackQuestion.survey_id)
        .filter(
            FeedbackSurvey.organization_id == org_id,
            FeedbackQuestion.is_active == True,
            FeedbackQuestion.type != "text",
        )
        .all()
    )

    by_question = []
    for q in questions:
        q_answers = [v for qid, _, v in answers_query if qid == q.id and v is not None]
        if not q_answers:
            continue
        avg = sum(float(v) for v in q_answers) / len(q_answers)
        qa = QuestionAnalytics(
            question_id=q.id,
            question_text=q.text,
            type=q.type,
            total_answers=len(q_answers),
            avg_score=round(avg, 2),
            satisfaction_pct=round(_score_from_type(q.type, avg), 1),
        )
        if q.type == "nps":
            promoters   = sum(1 for v in q_answers if float(v) >= 9)
            detractors  = sum(1 for v in q_answers if float(v) <= 6)
            qa.nps_score = round((promoters - detractors) / len(q_answers) * 100, 1)
        if q.type == "yesno":
            qa.yes_pct = round(sum(1 for v in q_answers if float(v) == 1) / len(q_answers) * 100, 1)
        by_question.append(qa)

    # Stars distribution (1-5)
    score_dist = {str(i): 0 for i in range(1, 6)}
    stars_answers = [float(v) for _, q_type, v in answers_query if q_type == "stars" and v is not None]
    for v in stars_answers:
        key = str(int(round(v)))
        if key in score_dist:
            score_dist[key] += 1

    # Per-branch breakdown
    from sqlalchemy import text
    branch_rows = db.execute(
        text("SELECT id, name FROM branches WHERE organization_id = :org_id"),
        {"org_id": org_id}
    ).fetchall()

    by_branch = []
    for br_id, br_name in branch_rows:
        br_filter = base_filter + [FeedbackResponse.branch_id == br_id]
        br_answers = (
            db.query(FeedbackQuestion.type, FeedbackAnswer.value_num)
            .join(FeedbackAnswer, FeedbackAnswer.question_id == FeedbackQuestion.id)
            .join(FeedbackResponse, FeedbackResponse.id == FeedbackAnswer.response_id)
            .join(FeedbackSurvey, FeedbackSurvey.id == FeedbackResponse.survey_id)
            .filter(*br_filter, FeedbackAnswer.value_num.isnot(None))
            .all()
        )
        br_scores = [s for t, v in br_answers if (s := _score_from_type(t, float(v))) is not None]
        br_count = (
            db.query(func.count(FeedbackResponse.id))
            .join(FeedbackSurvey, FeedbackSurvey.id == FeedbackResponse.survey_id)
            .filter(*br_filter)
            .scalar() or 0
        )
        if br_count > 0:
            by_branch.append(BranchAnalytics(
                branch_id=br_id,
                branch_name=br_name,
                satisfaction_score=round(sum(br_scores) / len(br_scores), 1) if br_scores else 0.0,
                responses=br_count,
            ))
    by_branch.sort(key=lambda x: x.satisfaction_score, reverse=True)

    # Time series
    time_series = _build_time_series(db, org_id, base_filter, start_date, end_date, granularity)

    return AnalyticsOut(
        organization_id=org_id,
        date_range={"start": str(start_date), "end": str(end_date)},
        overall=OverallAnalytics(
            satisfaction_score=overall_score,
            total_responses=total_responses,
            responses_today=responses_today,
            trend=trend,
        ),
        by_question=by_question,
        score_distribution=score_dist,
        by_branch=by_branch,
        time_series=time_series,
    )


def _build_time_series(db, org_id, base_filter, start_date, end_date, granularity):
    """Build time series data points aggregated by granularity."""
    results = []
    current = start_date

    if granularity == "monthly":
        delta = timedelta(days=30)
        fmt = "%Y-%m"
    elif granularity == "weekly":
        delta = timedelta(weeks=1)
        fmt = "%Y-W%W"
    else:  # daily
        delta = timedelta(days=1)
        fmt = "%Y-%m-%d"

    while current <= end_date:
        period_end = min(current + delta - timedelta(days=1), end_date)
        period_filter = base_filter + [
            FeedbackResponse.created_at >= current,
            FeedbackResponse.created_at <= period_end,
        ]
        count = (
            db.query(func.count(FeedbackResponse.id))
            .join(FeedbackSurvey, FeedbackSurvey.id == FeedbackResponse.survey_id)
            .filter(*period_filter)
            .scalar() or 0
        )
        p_answers = (
            db.query(FeedbackQuestion.type, FeedbackAnswer.value_num)
            .join(FeedbackAnswer, FeedbackAnswer.question_id == FeedbackQuestion.id)
            .join(FeedbackResponse, FeedbackResponse.id == FeedbackAnswer.response_id)
            .join(FeedbackSurvey, FeedbackSurvey.id == FeedbackResponse.survey_id)
            .filter(*period_filter, FeedbackAnswer.value_num.isnot(None))
            .all()
        )
        p_scores = [s for t, v in p_answers if (s := _score_from_type(t, float(v))) is not None]
        score = round(sum(p_scores) / len(p_scores), 1) if p_scores else 0.0

        results.append(TimeSeriesPoint(
            date=current.strftime(fmt),
            responses=count,
            satisfaction_score=score,
        ))
        current += delta

    return results
