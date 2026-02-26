"""Dashboard routes."""
import logging

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path
import json

from ..database import get_db
from ..models import User
from ..services.comparison import get_comparison_data

log = logging.getLogger(__name__)

router = APIRouter()

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    """Main dashboard view."""
    users = db.query(User).all()
    user_names = [u.name for u in users]
    selected_user = user_names[0] if user_names else None

    initial_data = None
    if selected_user:
        try:
            initial_data = get_comparison_data(selected_user, db)
        except Exception:
            log.exception("Failed to load initial data for %s", selected_user)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "users": user_names,
            "selected_user": selected_user,
            "initial_data": initial_data,
        }
    )
