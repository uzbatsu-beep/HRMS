from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.identity.router import router as identity_router
from app.organization.router import router as organization_router

app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    description="API foundation for Technical Workforce Management.",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-CSRF-Token"],
)
app.include_router(identity_router)
app.include_router(organization_router)


@app.get("/", tags=["system"], summary="API information")
def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "environment": settings.app_env,
        "docs": "/docs",
        "health": f"{settings.api_v1_prefix}/health/live",
    }


@app.get(f"{settings.api_v1_prefix}/health/live", tags=["health"], summary="Liveness probe")
def liveness() -> dict[str, str]:
    """Return success when the API process is running."""

    return {"status": "ok"}


@app.get(f"{settings.api_v1_prefix}/health/ready", tags=["health"], summary="Readiness probe")
def readiness(db: Session = Depends(get_db)) -> dict[str, object]:  # noqa: B008
    """Return success only when the API can execute a database query."""

    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not ready",
        ) from exc

    return {"status": "ready", "dependencies": {"database": "ok"}}
