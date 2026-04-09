"""FastAPI application factory."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .auth import BasicAuthMiddleware
from .database import init_db
from .limiter import limiter
from .routes import balances, benchmark, dashboard, files, holdings, projections, stress_test
from .security_headers import SecurityHeadersMiddleware

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "app" / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown."""
    init_db()
    yield


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Retirement Calculator Dashboard",
        description="Track and compare projected vs actual retirement performance",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(BasicAuthMiddleware)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.include_router(dashboard.router, tags=["dashboard"])
    app.include_router(projections.router, tags=["projections"])
    app.include_router(holdings.router, tags=["holdings"])
    app.include_router(balances.router, tags=["balances"])
    app.include_router(stress_test.router, tags=["stress-test"])
    app.include_router(benchmark.router, tags=["benchmark"])
    app.include_router(files.router, tags=["files"])

    @app.get("/health", include_in_schema=False)
    def health_check():
        return {"status": "ok"}

    return app


app = create_app()
