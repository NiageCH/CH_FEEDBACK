"""
feedback/routers/team.py
CRUD for feedback team members (MANAGER/VIEWER) with branch assignment.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text

from models import FeedbackUserBranch
from schemas import (
    UserOut, UserListOut, UserInvite, UserUpdate, UserInviteOut, BranchRef,
)
from dependencies import (
    get_db, get_current_user, require_role, require_org_access, CurrentUser,
)
from services.limits import check_user_limit

router = APIRouter(prefix="/organizations/{org_id}/feedback", tags=["Feedback · Team"])


def _get_user_branches(db: Session, user_id: int) -> list[BranchRef]:
    """Get branches assigned to a user via feedback_user_branches."""
    rows = db.execute(
        text(
            "SELECT b.id, b.name "
            "FROM feedback_user_branches fub "
            "JOIN branches b ON b.id = fub.branch_id "
            "WHERE fub.user_id = :uid ORDER BY b.name"
        ),
        {"uid": user_id},
    ).fetchall()
    return [BranchRef(id=r[0], name=r[1]) for r in rows]


def _set_user_branches(db: Session, user_id: int, branch_ids: list[int]) -> None:
    """Replace all branch assignments for a user."""
    db.query(FeedbackUserBranch).filter(FeedbackUserBranch.user_id == user_id).delete()
    for bid in branch_ids:
        db.add(FeedbackUserBranch(user_id=user_id, branch_id=bid))


@router.get("/users", response_model=UserListOut)
def list_users(
    org_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List all feedback users in the organization."""
    require_role(current_user, ["ADMIN", "SUPERADMIN"])
    require_org_access(current_user, org_id)

    rows = db.execute(
        text(
            "SELECT id, full_name, email, role, is_active, created_at "
            "FROM users WHERE organization_id = :org_id ORDER BY full_name"
        ),
        {"org_id": org_id},
    ).fetchall()

    users = []
    for r in rows:
        branches = None
        if r.role in ("MANAGER", "VIEWER"):
            branches = _get_user_branches(db, r.id)
        users.append(UserOut(
            id=r.id,
            full_name=r.full_name,
            email=r.email,
            role=r.role,
            is_active=r.is_active,
            branches=branches,
            created_at=r.created_at,
        ))

    return UserListOut(users=users)


@router.post("/users", response_model=UserInviteOut, status_code=status.HTTP_201_CREATED)
def invite_user(
    org_id: int,
    body: UserInvite,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Invite a new MANAGER or VIEWER to the organization."""
    require_role(current_user, ["ADMIN", "SUPERADMIN"])
    require_org_access(current_user, org_id)

    # Freemium limit
    check_user_limit(db, org_id)

    # Check if email already exists in this org
    existing = db.execute(
        text("SELECT id FROM users WHERE email = :email AND organization_id = :org_id"),
        {"email": body.email, "org_id": org_id},
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="User with this email already exists in this organization")

    # Validate branch_ids belong to this org
    for bid in body.branch_ids:
        check = db.execute(
            text("SELECT 1 FROM branches WHERE id = :id AND organization_id = :org_id"),
            {"id": bid, "org_id": org_id},
        ).first()
        if not check:
            raise HTTPException(status_code=422, detail=f"Branch {bid} not found in this organization")

    # Insert user (password handling is outside the scope of this module)
    result = db.execute(
        text(
            "INSERT INTO users (email, full_name, role, organization_id, is_active) "
            "VALUES (:email, :name, :role, :org_id, true) RETURNING id"
        ),
        {"email": body.email, "name": body.full_name, "role": body.role, "org_id": org_id},
    )
    user_id = result.scalar()

    # Assign branches
    _set_user_branches(db, user_id, body.branch_ids)
    db.commit()

    return UserInviteOut(
        id=user_id,
        email=body.email,
        role=body.role,
        invitation_sent=False,  # actual email sending is out of scope
    )


@router.put("/users/{user_id}", response_model=UserOut)
def update_user(
    org_id: int,
    user_id: int,
    body: UserUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Update a user's role, branches, or active status."""
    require_role(current_user, ["ADMIN", "SUPERADMIN"])
    require_org_access(current_user, org_id)

    row = db.execute(
        text("SELECT id, full_name, email, role, is_active, created_at FROM users WHERE id = :id AND organization_id = :org_id"),
        {"id": user_id, "org_id": org_id},
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="User not found in this organization")

    # Apply updates
    updates = {}
    if body.role is not None:
        updates["role"] = body.role
    if body.is_active is not None:
        updates["is_active"] = body.is_active

    if updates:
        set_clause = ", ".join(f"{k} = :{k}" for k in updates)
        db.execute(
            text(f"UPDATE users SET {set_clause} WHERE id = :id"),
            {**updates, "id": user_id},
        )

    if body.branch_ids is not None:
        # Validate branch_ids
        for bid in body.branch_ids:
            check = db.execute(
                text("SELECT 1 FROM branches WHERE id = :id AND organization_id = :org_id"),
                {"id": bid, "org_id": org_id},
            ).first()
            if not check:
                raise HTTPException(status_code=422, detail=f"Branch {bid} not found in this organization")
        _set_user_branches(db, user_id, body.branch_ids)

    db.commit()

    # Reload user
    updated = db.execute(
        text("SELECT id, full_name, email, role, is_active, created_at FROM users WHERE id = :id"),
        {"id": user_id},
    ).first()
    role = body.role or row.role
    branches = None
    if role in ("MANAGER", "VIEWER"):
        branches = _get_user_branches(db, user_id)

    return UserOut(
        id=updated.id,
        full_name=updated.full_name,
        email=updated.email,
        role=updated.role,
        is_active=updated.is_active,
        branches=branches,
        created_at=updated.created_at,
    )


@router.delete("/users/{user_id}")
def deactivate_user(
    org_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Deactivate a user (soft delete)."""
    require_role(current_user, ["ADMIN", "SUPERADMIN"])
    require_org_access(current_user, org_id)

    row = db.execute(
        text("SELECT id FROM users WHERE id = :id AND organization_id = :org_id"),
        {"id": user_id, "org_id": org_id},
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="User not found in this organization")

    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")

    db.execute(
        text("UPDATE users SET is_active = false WHERE id = :id"),
        {"id": user_id},
    )
    # Remove branch assignments
    db.query(FeedbackUserBranch).filter(FeedbackUserBranch.user_id == user_id).delete()
    db.commit()

    return {"message": "User deactivated"}
