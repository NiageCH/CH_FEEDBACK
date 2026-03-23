"""
feedback/routers/admin.py
Superadmin panel: tenant management, plan changes, feature flags, audit log.
Requires role == SUPERADMIN.
"""

from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import text, func, extract

from models import FeedbackSurvey, FeedbackResponse
from schemas import (
    TenantOut, TenantListOut, TenantCreate, TenantFeedbackStats,
    PlanUpdate, FlagsUpdate, AuditEntry, AuditLogOut,
)
from dependencies import get_db, get_current_user, require_role, CurrentUser
from services.limits import FREEMIUM_RESPONSES_LIMIT

router = APIRouter(prefix="/admin", tags=["Feedback · Superadmin"])


def _ensure_superadmin(user: CurrentUser):
    require_role(user, ["SUPERADMIN"])


def _get_tenant_stats(db: Session, org_id: int) -> TenantFeedbackStats:
    """Get feedback-specific stats for a tenant."""
    surveys_count = db.query(func.count(FeedbackSurvey.id)).filter(
        FeedbackSurvey.organization_id == org_id,
        FeedbackSurvey.is_active == True,
    ).scalar() or 0

    today = date.today()
    responses_this_month = (
        db.query(func.count(FeedbackResponse.id))
        .join(FeedbackSurvey, FeedbackSurvey.id == FeedbackResponse.survey_id)
        .filter(
            FeedbackSurvey.organization_id == org_id,
            extract("year", FeedbackResponse.created_at) == today.year,
            extract("month", FeedbackResponse.created_at) == today.month,
        )
        .scalar() or 0
    )

    # Get plan to determine limit
    plan_row = db.execute(
        text("SELECT plan FROM organizations WHERE id = :id"), {"id": org_id}
    ).first()
    plan = plan_row[0] if plan_row else "freemium"
    limit = FREEMIUM_RESPONSES_LIMIT if plan == "freemium" else 999999

    users_count = db.execute(
        text("SELECT COUNT(*) FROM users WHERE organization_id = :org_id AND is_active = true"),
        {"org_id": org_id},
    ).scalar() or 0

    return TenantFeedbackStats(
        surveys_count=surveys_count,
        responses_this_month=responses_this_month,
        responses_limit=limit,
        users_count=users_count,
    )


@router.get("/tenants", response_model=TenantListOut)
def list_tenants(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List all tenants with their feedback stats."""
    _ensure_superadmin(current_user)

    rows = db.execute(
        text("SELECT id, name, plan, is_active FROM organizations ORDER BY name")
    ).fetchall()

    tenants = []
    for r in rows:
        tenants.append(TenantOut(
            id=r.id,
            name=r.name,
            plan=r.plan,
            is_active=r.is_active,
            feedback=_get_tenant_stats(db, r.id),
        ))

    return TenantListOut(tenants=tenants)


@router.post("/tenants", status_code=status.HTTP_201_CREATED)
def create_tenant(
    body: TenantCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Create a new tenant organization with an admin user."""
    _ensure_superadmin(current_user)

    # Check duplicate name
    existing = db.execute(
        text("SELECT id FROM organizations WHERE name = :name"),
        {"name": body.name},
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Organization name already exists")

    # Create organization
    result = db.execute(
        text(
            "INSERT INTO organizations (name, plan, is_active) "
            "VALUES (:name, :plan, true) RETURNING id"
        ),
        {"name": body.name, "plan": body.plan},
    )
    org_id = result.scalar()

    # Create admin user
    db.execute(
        text(
            "INSERT INTO users (email, full_name, role, organization_id, is_active) "
            "VALUES (:email, :name, 'ADMIN', :org_id, true)"
        ),
        {"email": body.admin_email, "name": body.admin_full_name, "org_id": org_id},
    )

    db.commit()
    return {"id": org_id, "message": f"Tenant '{body.name}' created with admin {body.admin_email}"}


@router.put("/tenants/{tenant_id}/plan")
def update_plan(
    tenant_id: int,
    body: PlanUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Change a tenant's plan (freemium/paid)."""
    _ensure_superadmin(current_user)

    row = db.execute(
        text("SELECT id FROM organizations WHERE id = :id"), {"id": tenant_id}
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found")

    db.execute(
        text("UPDATE organizations SET plan = :plan WHERE id = :id"),
        {"plan": body.plan, "id": tenant_id},
    )
    db.commit()
    return {"message": f"Plan updated to '{body.plan}' for tenant {tenant_id}"}


@router.put("/tenants/{tenant_id}/flags")
def update_flags(
    tenant_id: int,
    body: FlagsUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Update feature flags for a tenant."""
    _ensure_superadmin(current_user)

    row = db.execute(
        text("SELECT id FROM organizations WHERE id = :id"), {"id": tenant_id}
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Store flags as JSON or in a dedicated table — using a simple approach here
    flags = body.model_dump(exclude_none=True)
    if flags:
        for key, value in flags.items():
            # Upsert into a feature_flags or organization_settings table
            existing = db.execute(
                text(
                    "SELECT 1 FROM organization_settings "
                    "WHERE organization_id = :org_id AND key = :key"
                ),
                {"org_id": tenant_id, "key": key},
            ).first()
            if existing:
                db.execute(
                    text(
                        "UPDATE organization_settings SET value = :val "
                        "WHERE organization_id = :org_id AND key = :key"
                    ),
                    {"val": str(value).lower(), "org_id": tenant_id, "key": key},
                )
            else:
                db.execute(
                    text(
                        "INSERT INTO organization_settings (organization_id, key, value) "
                        "VALUES (:org_id, :key, :val)"
                    ),
                    {"org_id": tenant_id, "key": key, "val": str(value).lower()},
                )

    db.commit()
    return {"message": f"Flags updated for tenant {tenant_id}"}


@router.get("/audit-log", response_model=AuditLogOut)
def get_audit_log(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Retrieve the audit log (most recent first)."""
    _ensure_superadmin(current_user)

    total = db.execute(text("SELECT COUNT(*) FROM audit_log")).scalar() or 0

    rows = db.execute(
        text(
            "SELECT al.id, al.created_at, u.email, u.role, "
            "al.action, al.resource_type, al.resource_id, al.details "
            "FROM audit_log al "
            "LEFT JOIN users u ON u.id = al.actor_id "
            "ORDER BY al.created_at DESC "
            "LIMIT :limit OFFSET :offset"
        ),
        {"limit": per_page, "offset": (page - 1) * per_page},
    ).fetchall()

    entries = [
        AuditEntry(
            id=r[0],
            timestamp=r[1],
            actor_email=r[2] or "system",
            actor_role=r[3] or "SUPERADMIN",
            action=r[4],
            resource_type=r[5],
            resource_id=r[6],
            details=r[7],
        )
        for r in rows
    ]

    return AuditLogOut(total=total, entries=entries)
