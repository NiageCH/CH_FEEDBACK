"""
feedback/schemas.py
Pydantic v2 request/response schemas for the Feedback module.
"""

from __future__ import annotations
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, EmailStr, Field, field_validator
import re


# ── Enums ─────────────────────────────────────────────────────────────────────

QuestionType  = Literal["stars", "nps", "yesno", "text"]
DeviceType    = Literal["mobile", "tablet", "desktop"]
UserRole      = Literal["SUPERADMIN", "ADMIN", "MANAGER", "VIEWER"]
InviteRole    = Literal["MANAGER", "VIEWER"]   # roles that can be invited via the panel


# ── Surveys ───────────────────────────────────────────────────────────────────

class SurveyCreate(BaseModel):
    name:          str = Field(..., min_length=1, max_length=255)
    thank_you_msg: Optional[str] = Field(None, max_length=500)


class SurveyUpdate(BaseModel):
    name:          Optional[str] = Field(None, min_length=1, max_length=255)
    thank_you_msg: Optional[str] = Field(None, max_length=500)
    is_active:     Optional[bool] = None


class SurveyOut(BaseModel):
    id:                 int
    organization_id:    int
    name:               str
    qr_token:           str
    qr_url:             str
    thank_you_msg:      str
    is_active:          bool
    questions_count:    int = 0
    responses_count:    int = 0
    satisfaction_score: Optional[float] = None
    created_at:         datetime

    model_config = {"from_attributes": True}


class SurveyDetail(SurveyOut):
    questions: list[QuestionOut] = []


# ── Questions ─────────────────────────────────────────────────────────────────

class QuestionCreate(BaseModel):
    text:       str = Field(..., min_length=1, max_length=500)
    type:       QuestionType
    sort_order: Optional[int] = None    # auto-assigned if not provided


class QuestionUpdate(BaseModel):
    text:       Optional[str]          = Field(None, min_length=1, max_length=500)
    type:       Optional[QuestionType] = None
    sort_order: Optional[int]          = None
    is_active:  Optional[bool]         = None


class QuestionOut(BaseModel):
    id:         int
    survey_id:  int
    text:       str
    type:       QuestionType
    sort_order: int
    is_active:  bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Public QR page (no auth) ──────────────────────────────────────────────────

class PublicBrandingOut(BaseModel):
    name:           str
    brand_color:    str
    welcome_msg:    str
    show_powered_by: bool


class PublicBranchOut(BaseModel):
    id:   int
    name: str


class PublicQuestionOut(BaseModel):
    id:         int
    text:       str
    type:       QuestionType
    sort_order: int


class PublicSurveyOut(BaseModel):
    """Response for GET /public/feedback/{qr_token}"""
    survey_id:    int
    survey_name:  str
    thank_you_msg: str
    organization: PublicBrandingOut
    branches:     list[PublicBranchOut]
    questions:    list[PublicQuestionOut]


class AnswerIn(BaseModel):
    question_id: int
    value_num:   Optional[float] = Field(None, ge=0, le=10)
    value_text:  Optional[str]   = Field(None, max_length=2000)

    @field_validator("value_num")
    @classmethod
    def round_value(cls, v):
        return round(v, 2) if v is not None else v


class ResponseCreate(BaseModel):
    """Body for POST /public/feedback/{qr_token}/responses"""
    branch_id:   Optional[int]       = None
    device_type: Optional[DeviceType] = None
    answers:     list[AnswerIn]       = Field(..., min_length=1)


class ResponseCreatedOut(BaseModel):
    response_id:        int
    message:            str = "Respuesta registrada. ¡Gracias!"
    satisfaction_score: Optional[float] = None   # 0-100


# ── Analytics ─────────────────────────────────────────────────────────────────

class QuestionAnalytics(BaseModel):
    question_id:      int
    question_text:    str
    type:             QuestionType
    avg_score:        Optional[float] = None
    satisfaction_pct: Optional[float] = None
    nps_score:        Optional[float] = None   # only for type='nps'
    yes_pct:          Optional[float] = None   # only for type='yesno'
    total_answers:    int = 0


class BranchAnalytics(BaseModel):
    branch_id:          int
    branch_name:        str
    satisfaction_score: float
    responses:          int


class TimeSeriesPoint(BaseModel):
    date:               str    # YYYY-MM-DD or YYYY-WXX or YYYY-MM
    responses:          int
    satisfaction_score: float


class OverallAnalytics(BaseModel):
    satisfaction_score: float
    total_responses:    int
    responses_today:    int
    trend:              str    # e.g. "+4.2%"


class AnalyticsOut(BaseModel):
    organization_id: int
    date_range:      dict
    overall:         OverallAnalytics
    by_question:     list[QuestionAnalytics]
    score_distribution: dict[str, int]   # {"1": N, "2": N, ..., "5": N}
    by_branch:       list[BranchAnalytics]
    time_series:     list[TimeSeriesPoint]


# ── Responses list ────────────────────────────────────────────────────────────

class AnswerOut(BaseModel):
    question_id:   int
    question_text: str
    type:          QuestionType
    value_num:     Optional[float] = None
    value_text:    Optional[str]   = None


class ResponseOut(BaseModel):
    id:                 int
    branch_name:        Optional[str]
    created_at:         datetime
    device_type:        Optional[DeviceType]
    satisfaction_score: Optional[float]
    answers:            list[AnswerOut]

    model_config = {"from_attributes": True}


class ResponseListOut(BaseModel):
    total:     int
    page:      int
    per_page:  int
    responses: list[ResponseOut]


# ── Team / Users ──────────────────────────────────────────────────────────────

class BranchRef(BaseModel):
    id:   int
    name: str


class UserOut(BaseModel):
    id:         int
    full_name:  str
    email:      str
    role:       UserRole
    is_active:  bool
    branches:   Optional[list[BranchRef]] = None   # None means "all" (ADMIN)
    created_at: datetime

    model_config = {"from_attributes": True}


class UserListOut(BaseModel):
    users: list[UserOut]


class UserInvite(BaseModel):
    email:      EmailStr
    full_name:  str = Field(..., min_length=1, max_length=255)
    role:       InviteRole
    branch_ids: list[int] = Field(..., min_length=1)


class UserUpdate(BaseModel):
    role:       Optional[InviteRole]  = None
    branch_ids: Optional[list[int]]  = None
    is_active:  Optional[bool]        = None


class UserInviteOut(BaseModel):
    id:              int
    email:           str
    role:            UserRole
    invitation_sent: bool


# ── Config / Branding ─────────────────────────────────────────────────────────

class ConfigOut(BaseModel):
    organization_id: int
    brand_color:     str
    brand_name:      Optional[str]
    welcome_msg:     str
    thank_you_msg:   str
    show_powered_by: bool

    model_config = {"from_attributes": True}


class ConfigUpdate(BaseModel):
    brand_color:     Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    brand_name:      Optional[str] = Field(None, max_length=255)
    welcome_msg:     Optional[str] = Field(None, max_length=500)
    thank_you_msg:   Optional[str] = Field(None, max_length=500)
    show_powered_by: Optional[bool] = None


# ── Superadmin ────────────────────────────────────────────────────────────────

class TenantFeedbackStats(BaseModel):
    surveys_count:          int
    responses_this_month:   int
    responses_limit:        int
    users_count:            int


class TenantOut(BaseModel):
    id:        int
    name:      str
    plan:      str
    is_active: bool
    feedback:  TenantFeedbackStats


class TenantListOut(BaseModel):
    tenants: list[TenantOut]


class TenantCreate(BaseModel):
    name:            str = Field(..., min_length=1, max_length=255)
    plan:            str = Field(default="freemium")
    admin_email:     EmailStr
    admin_full_name: str = Field(..., min_length=1, max_length=255)


class PlanUpdate(BaseModel):
    plan: str = Field(..., pattern=r"^(freemium|paid)$")


class FlagsUpdate(BaseModel):
    feedback_optin_v2:    Optional[bool] = None
    feedback_rewards_v3:  Optional[bool] = None
    feedback_api_export:  Optional[bool] = None


class AuditEntry(BaseModel):
    id:            int
    timestamp:     datetime
    actor_email:   str
    actor_role:    UserRole
    action:        str
    resource_type: str
    resource_id:   Optional[int]
    details:       Optional[dict]


class AuditLogOut(BaseModel):
    total:   int
    entries: list[AuditEntry]


# ── Error responses ───────────────────────────────────────────────────────────

class ErrorOut(BaseModel):
    error:   str
    message: str
    detail:  Optional[str] = None


class PlanLimitOut(BaseModel):
    error:   str        # e.g. "PLAN_LIMIT_SURVEYS"
    message: str
    used:    int
    limit:   int


# Fix forward references
SurveyDetail.model_rebuild()
