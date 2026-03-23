from __future__ import annotations
from typing import Optional, List
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from jose import jwt, JWTError
from pydantic import BaseModel
import os

bearer_scheme = HTTPBearer()

JWT_SECRET = os.getenv("JWT_SECRET_KEY", "change-me")
JWT_ALGO   = os.getenv("JWT_ALGORITHM", "HS256")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/customerhub")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class CurrentUser(BaseModel):
    id:              int
    email:           str
    full_name:       str
    role:            str
    organization_id: int
    branch_id:       Optional[int] = None
    is_active:       bool

    model_config = {"from_attributes": True}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> CurrentUser:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Could not validate credentials")

    row = db.execute(
        text("SELECT id, email, full_name, role, organization_id, branch_id, is_active FROM users WHERE id = :id AND is_active = true"),
        {"id": int(user_id)}
    ).first()

    if not row:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    return CurrentUser(
        id=row[0], email=row[1], full_name=row[2], role=row[3],
        organization_id=row[4], branch_id=row[5], is_active=row[6]
    )


def require_role(user: CurrentUser, allowed_roles: List[str]) -> None:
    if user.role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.role}' not authorized. Required: {allowed_roles}"
        )


def require_org_access(user: CurrentUser, org_id: int) -> None:
    if user.role == "SUPERADMIN":
        return
    if user.organization_id != org_id:
        raise HTTPException(status_code=403, detail="Access denied to this organization")


def require_branch_access(user: CurrentUser, branch_id: int, db: Session) -> None:
    if user.role in ("ADMIN", "SUPERADMIN"):
        return
    from models import FeedbackUserBranch
    assigned = db.query(FeedbackUserBranch).filter(
        FeedbackUserBranch.user_id == user.id,
        FeedbackUserBranch.branch_id == branch_id,
    ).first()
    if not assigned:
        raise HTTPException(status_code=403, detail=f"No access to branch {branch_id}")


def get_user_branch_ids(user: CurrentUser, org_id: int, db: Session) -> Optional[List[int]]:
    if user.role in ("ADMIN", "SUPERADMIN"):
        return None
    from models import FeedbackUserBranch
    rows = db.query(FeedbackUserBranch.branch_id).filter(
        FeedbackUserBranch.user_id == user.id,
    ).all()
    return [r[0] for r in rows]
