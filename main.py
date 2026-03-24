from dotenv import load_dotenv
load_dotenv()

"""
feedback/main.py
FastAPI app entry point for the Feedback module.

HOW TO INTEGRATE WITH YOUR EXISTING CUSTOMER HUB APP:
  Option A â Mount as sub-app (recommended for separation):
    from feedback.main import feedback_app
    main_app.mount("/feedback-module", feedback_app)

  Option B â Include routers directly in your existing app:
    from feedback.routers import surveys, public_qr, responses, team, config, admin
    app.include_router(surveys.router, prefix="/api/v1")
    app.include_router(public_qr.router, prefix="/api/v1")
    # etc.

For now (standalone testing), run with:
  uvicorn feedback.main:app --reload --port 8001
"""

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from routers import surveys, public_qr, responses, team, config, admin

app = FastAPI(
    title="Customer Hub â Feedback Module",
    description="Satisfaction surveys, QR codes, and analytics for Customer Hub tenants.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS â adjust origins for your environment
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*",  
        "https://democba.niage.es",
        "http://localhost:3000",   # React dev server
        "http://localhost:5173",   # Vite dev server
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ââ Register routers ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
API_PREFIX = "/api/v1"

app.include_router(surveys.router,    prefix=API_PREFIX)    # /organizations/{id}/feedback/surveys
app.include_router(public_qr.router,  prefix=API_PREFIX)    # /public/feedback/{token}
app.include_router(responses.router,  prefix=API_PREFIX)    # /organizations/{id}/feedback/responses
app.include_router(team.router,       prefix=API_PREFIX)    # /organizations/{id}/feedback/users
app.include_router(config.router,     prefix=API_PREFIX)    # /organizations/{id}/feedback/config
app.include_router(admin.router,      prefix=API_PREFIX)    # /admin/tenants


@app.get("/dashboard-ui")
def ui(): return FileResponse("dashboard.html")

@app.get("/health")
def health():
    return {"status": "ok", "module": "feedback", "version": "1.0.0"}


@app.get("/api/v1/me/sidebar/feedback-entry")
def sidebar_entry():
    """
    Returns the Feedback entry to be merged into the existing sidebar response.
    The existing /api/v1/me/sidebar endpoint should include this in its 'modules' array.
    """
    return {
        "code":       "feedback",
        "name":       "Feedback",
        "route":      "/feedback",
        "icon":       "chat",
        "sort_order": 7,
    }

@app.post("/api/v1/auth/login")
def login(body: dict, db = Depends(get_db)):
    from sqlalchemy import text as t
    from jose import jwt
    import datetime, os
    email = body.get("email","").strip().lower()
    user = db.execute(t("SELECT id, organization_id, full_name, role FROM users WHERE email=:e AND is_active=true"), {"e": email}).fetchone()
    if not user:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")
    token = jwt.encode(
        {"sub": str(user[0]), "exp": datetime.datetime.utcnow() + datetime.timedelta(days=30)},
        os.getenv("JWT_SECRET_KEY","dev_secret_local_123"),
        algorithm=os.getenv("JWT_ALGORITHM","HS256")
    )
    org = db.execute(t("SELECT name FROM organizations WHERE id=:i"), {"i": user[1]}).fetchone()
    return {"access_token": token, "token_type": "bearer", "user_id": user[0], "org_id": user[1], "org_name": org[0] if org else "", "full_name": user[2], "role": user[3]}
