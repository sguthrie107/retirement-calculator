"""Dashboard routes."""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path
import json

from ..database import get_db
from ..models import User
from ..services.comparison import get_comparison_data

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
    
    print(f"\nDEBUG DASHBOARD: Users found: {user_names}")
    print(f"DEBUG DASHBOARD: Selected user: {selected_user}")
    
    # Fetch initial data for the selected user
    initial_data = None
    if selected_user:
        print(f"DEBUG DASHBOARD: Fetching initial data for {selected_user}")
        try:
            initial_data = get_comparison_data(selected_user, db)
            print(f"DEBUG DASHBOARD: Initial data fetched, deltas: {len(initial_data.get('deltas', []))}")
            print(f"DEBUG DASHBOARD: Projected data points: {len(initial_data.get('projected', []))}")
            print(f"DEBUG DASHBOARD: First projected point: {initial_data.get('projected', [{}])[0] if initial_data.get('projected') else 'none'}")
        except Exception as e:
            print(f"DEBUG DASHBOARD: Error fetching initial data: {e}")
            import traceback
            traceback.print_exc()
    
    # Convert initial_data to JSON for embedding in template
    initial_data_json = json.dumps(initial_data) if initial_data else "null"
    print(f"DEBUG DASHBOARD: JSON data length: {len(initial_data_json)} chars")
    if len(initial_data_json) > 10:
        print(f"DEBUG DASHBOARD: Sample JSON: {initial_data_json[:300]}")
    
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "users": user_names,
            "selected_user": selected_user,
            "initial_data": initial_data,
        }
    )
