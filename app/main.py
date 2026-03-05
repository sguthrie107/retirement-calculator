"""FastAPI application factory."""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager
from pathlib import Path

from .database import init_db
from .routes import dashboard, projections, balances, stress_test, holdings
from .auth import BasicAuthMiddleware
from .security_headers import SecurityHeadersMiddleware

# Get absolute paths
BASE_DIR = Path(__file__).parent.parent
STATIC_DIR = BASE_DIR / "app" / "static"
TEMPLATES_DIR = BASE_DIR / "app" / "templates"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown."""
    # Startup: Initialize database
    init_db()
    yield
    # Shutdown: cleanup if needed


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="Retirement Calculator Dashboard",
        description="Track and compare projected vs actual retirement performance",
        version="1.0.0",
        lifespan=lifespan,
    )
    
    # Middleware (outermost first — security headers wrap auth wrap routes)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(BasicAuthMiddleware)

    # Mount static files (use absolute path)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    
    # Register routes
    app.include_router(dashboard.router, tags=["dashboard"])
    app.include_router(projections.router, tags=["projections"])
    app.include_router(holdings.router, tags=["holdings"])
    app.include_router(balances.router, tags=["balances"])
    app.include_router(stress_test.router, tags=["stress-test"])

    @app.get("/health", include_in_schema=False)
    def health_check():
        return {"status": "ok"}
    
    return app


# Create app instance
app = create_app()
