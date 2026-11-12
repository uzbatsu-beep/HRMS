
# TWM Backend

FastAPI backend for Technical Workforce Management.

Install from the repository root with:

    python -m pip install -e "./backend[dev]"

Set TWM_DATABASE_URL to a reachable PostgreSQL connection string. From this directory run:

    alembic upgrade head
    uvicorn app.main:app --reload

The API exposes liveness and readiness probes under /api/v1/health.
