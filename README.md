# Customer Hub — Módulo Feedback

> Satisfacción de clientes con QR, encuestas anónimas y analytics en tiempo real. Desarrollado por Niage para Customer Hub.

## Stack
- **Backend**: FastAPI (Python 3.9+) + SQLAlchemy 2.0
- **Base de datos**: PostgreSQL 15
- **Auth**: JWT Bearer (HS256)
- **Dashboard**: HTML + Vanilla JS + Chart.js

## Arranque rápido

### 1. Base de datos local (Docker)
```bash
docker run -d --name feedback-db \
  -e POSTGRES_USER=feedback_user \
  -e POSTGRES_PASSWORD=feedback_pass \
  -e POSTGRES_DB=feedback_db \
  -p 5432:5432 postgres:15
```

### 2. Instalar y arrancar
```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements-feedback.txt
uvicorn main:app --reload --port 8001
```

- **Dashboard**: http://localhost:8001/dashboard-ui
- **Swagger API**: http://localhost:8001/docs

### 3. Variables de entorno (.env)
```env
DATABASE_URL=postgresql://feedback_user:feedback_pass@localhost:5432/feedback_db
JWT_SECRET_KEY=your_secret_here
JWT_ALGORITHM=HS256
FEEDBACK_BASE_URL=http://localhost:8001/feedback
FEEDBACK_FREEMIUM_SURVEYS_LIMIT=1
FEEDBACK_FREEMIUM_RESPONSE_LIMIT=100
FEEDBACK_FREEMIUM_USERS_LIMIT=2
```

## Estructura del proyecto
```
├── main.py               # FastAPI entry point
├── models.py             # SQLAlchemy models (7 tablas)
├── schemas.py            # Pydantic v2 schemas
├── dependencies.py       # Auth, DB session, role checks
├── dashboard.html        # Dashboard visual (servido por FastAPI)
├── requirements-feedback.txt
├── routers/
│   ├── surveys.py        # CRUD encuestas + asignación tiendas
│   ├── public.py         # Endpoints QR sin autenticación
│   ├── responses.py      # Listado respuestas + analytics
│   ├── team.py           # Gestión usuarios y branches
│   ├── config.py         # Branding del tenant
│   └── admin.py          # Panel Superadmin (Niage)
├── services/
│   ├── analytics.py      # Cálculo satisfaction score
│   └── limits.py         # Límites freemium
├── migrations/
│   └── 001_create_feedback_tables.py
└── tests/
    └── test_public.py
```

## Arquitectura de roles

| Rol | Acceso |
|---|---|
| `ADMIN` | Todas las tiendas del tenant |
| `MANAGER` | Solo tiendas asignadas (N:M) |
| `VIEWER` | Solo lectura en tiendas asignadas |
| `SUPERADMIN` | Control total multiplataforma (Niage) |

## API — Endpoints principales

```
# Auth: Authorization: Bearer <jwt_token>

GET    /api/v1/organizations/{org_id}/feedback/surveys
POST   /api/v1/organizations/{org_id}/feedback/surveys
PUT    /api/v1/organizations/{org_id}/feedback/surveys/{id}/branches
GET    /api/v1/public/feedback/{qr_token}          # Sin auth
POST   /api/v1/public/feedback/{qr_token}/responses # Sin auth
GET    /api/v1/organizations/{org_id}/feedback/responses
GET    /api/v1/organizations/{org_id}/feedback/analytics
```

## Flujo de una respuesta

```
Admin crea encuesta → asigna tiendas libremente
         ↓
Se genera 1 QR único permanente
         ↓
Cliente escanea QR → selecciona su tienda → responde (30 seg)
         ↓
Respuesta guardada: branch_id + device_type + answers
(sin IP, sin cookies, sin datos personales)
         ↓
Dashboard actualiza métricas en tiempo real
```

## Fórmula de satisfacción

```python
stars  → (valor - 1) / 4 × 100   # 1★=0%, 5★=100%
nps    → valor / 10 × 100          # 0=0%, 10=100%
yesno  → valor × 100               # No=0%, Sí=100%
text   → excluido del cálculo
# Global = promedio de todos los scores cuantificables
```

## Modelo freemium

| Funcionalidad | Freemium | Paid |
|---|---|---|
| Encuestas activas | 1 | Ilimitadas |
| Respuestas / mes | 100 | Ilimitadas |
| Usuarios | 2 | Ilimitados |
| Opt-in contacto (v2) | No | Sí |
| Rewards/wallet (v3) | No | Sí |

## Roadmap

| Versión | Funcionalidades |
|---|---|
| **v1.0** ✅ | QR + encuestas anónimas + dashboard + roles + freemium + asignación tiendas |
| **v2.0** | Opt-in email/móvil voluntario + doble consentimiento RGPD |
| **v3.0** | Login cliente final + wallet puntos + fidelización |
| **v4.0** | Benchmarking multi-tienda + alertas + API pública + integraciones CRM |

---
*Customer Hub · Módulo Feedback · Niage © 2026*