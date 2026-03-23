"""
feedback/routers/config.py
GET/PUT branding configuration per tenant.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from models import FeedbackConfig
from schemas import ConfigOut, ConfigUpdate
from dependencies import (
    get_db, get_current_user, require_role, require_org_access, CurrentUser,
)

router = APIRouter(prefix="/organizations/{org_id}/feedback", tags=["Feedback · Config"])


def _config_to_out(config: FeedbackConfig) -> ConfigOut:
    return ConfigOut(
        organization_id=config.organization_id,
        brand_color=config.brand_color or "#FAD51B",
        brand_name=config.brand_name,
        welcome_msg=config.welcome_msg or "Tu opinión nos importa. Solo tardas 30 segundos.",
        thank_you_msg=config.thank_you_msg or "¡Gracias por tu opinión!",
        show_powered_by=config.show_powered_by,
    )


@router.get("/config", response_model=ConfigOut)
def get_config(
    org_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Get branding configuration for the feedback module."""
    require_org_access(current_user, org_id)

    config = db.query(FeedbackConfig).filter(
        FeedbackConfig.organization_id == org_id
    ).first()

    if not config:
        # Return defaults
        return ConfigOut(
            organization_id=org_id,
            brand_color="#FAD51B",
            brand_name=None,
            welcome_msg="Tu opinión nos importa. Solo tardas 30 segundos.",
            thank_you_msg="¡Gracias por tu opinión!",
            show_powered_by=True,
        )

    return _config_to_out(config)


@router.put("/config", response_model=ConfigOut)
def upsert_config(
    org_id: int,
    body: ConfigUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Create or update branding configuration (upsert)."""
    require_role(current_user, ["ADMIN", "SUPERADMIN"])
    require_org_access(current_user, org_id)

    config = db.query(FeedbackConfig).filter(
        FeedbackConfig.organization_id == org_id
    ).first()

    if not config:
        config = FeedbackConfig(organization_id=org_id)
        db.add(config)

    if body.brand_color is not None:
        config.brand_color = body.brand_color
    if body.brand_name is not None:
        config.brand_name = body.brand_name
    if body.welcome_msg is not None:
        config.welcome_msg = body.welcome_msg
    if body.thank_you_msg is not None:
        config.thank_you_msg = body.thank_you_msg
    if body.show_powered_by is not None:
        config.show_powered_by = body.show_powered_by

    db.commit()
    db.refresh(config)
    return _config_to_out(config)
