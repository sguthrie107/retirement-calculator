"""Dashboard routes."""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path

from ..database import get_db
from ..models import User

router = APIRouter()

# Use absolute path for templates
TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    """Main dashboard view."""
    # Get list of users for dropdown
    users = db.query(User).all()
    user_names = [u.name for u in users]
    
    # Default to first user if available
    selected_user = user_names[0] if user_names else None
    
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "users": user_names,
            "selected_user": selected_user,
        }
    )
