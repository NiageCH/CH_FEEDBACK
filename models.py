from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, Numeric, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class FeedbackSurvey(Base):
    __tablename__ = "feedback_surveys"
    id              = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, nullable=False, index=True)
    name            = Column(String(255), nullable=False)
    qr_token        = Column(String(64), unique=True, nullable=False, index=True)
    thank_you_msg   = Column(Text, default="Gracias por tu opinion")
    is_active       = Column(Boolean, default=True, nullable=False)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), server_default=func.now())


class FeedbackQuestion(Base):
    __tablename__ = "feedback_questions"
    id          = Column(Integer, primary_key=True, index=True)
    survey_id   = Column(Integer, nullable=False, index=True)
    text        = Column(Text, nullable=False)
    type        = Column(String(20), nullable=False)
    sort_order  = Column(Integer, nullable=False, default=0)
    is_active   = Column(Boolean, default=True, nullable=False)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())


class FeedbackResponse(Base):
    __tablename__ = "feedback_responses"
    id          = Column(Integer, primary_key=True, index=True)
    survey_id   = Column(Integer, nullable=False, index=True)
    branch_id   = Column(Integer, nullable=True, index=True)
    device_type = Column(String(20), nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class FeedbackAnswer(Base):
    __tablename__ = "feedback_answers"
    id          = Column(Integer, primary_key=True, index=True)
    response_id = Column(Integer, nullable=False, index=True)
    question_id = Column(Integer, nullable=False, index=True)
    value_num   = Column(Numeric(5, 2), nullable=True)
    value_text  = Column(Text, nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())


class FeedbackConfig(Base):
    __tablename__ = "feedback_configs"
    id              = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, unique=True, nullable=False)
    brand_color     = Column(String(7), default="#FAD51B")
    brand_name      = Column(String(255), nullable=True)
    welcome_msg     = Column(Text, default="Tu opinion nos importa.")
    thank_you_msg   = Column(Text, default="Gracias por tu opinion")
    show_powered_by = Column(Boolean, default=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), server_default=func.now())


class FeedbackUserBranch(Base):
    __tablename__ = "feedback_user_branches"
    user_id    = Column(Integer, primary_key=True)
    branch_id  = Column(Integer, primary_key=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
