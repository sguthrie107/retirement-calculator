"""File upload/download routes."""
import logging
import mimetypes
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import UploadedFile

log = logging.getLogger(__name__)

router = APIRouter()

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Storage directory: use UPLOAD_DIR env var (set this to a Railway Volume path in prod)
# or default to data/uploads/ relative to the project root.
_DEFAULT_UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "uploads"
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", str(_DEFAULT_UPLOAD_DIR)))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".txt", ".png", ".jpg", ".jpeg",
    ".xlsx", ".xls", ".csv", ".pptx", ".ppt",
}
MAX_FILE_SIZE_MB = 25
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

CATEGORIES = [
    "Retirement",
    "Estate Planning",
    "Will & Trust",
    "Insurance",
    "Tax",
    "Legal",
    "Other",
]


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / 1024 ** 2:.1f} MB"


@router.get("/files", response_class=HTMLResponse)
async def files_page(request: Request, db: Session = Depends(get_db)):
    """File vault page — lists all uploaded documents."""
    all_files = db.query(UploadedFile).order_by(UploadedFile.uploaded_at.desc()).all()

    # Group by category
    grouped: dict[str, list] = {cat: [] for cat in CATEGORIES}
    for f in all_files:
        cat = f.category if f.category in grouped else "Other"
        grouped[cat].append({
            "id": f.id,
            "title": f.title,
            "original_filename": f.original_filename,
            "category": f.category,
            "description": f.description or "",
            "file_size": _format_size(f.file_size),
            "mime_type": f.mime_type or "application/octet-stream",
            "uploaded_at": f.uploaded_at[:10],  # date portion only
        })

    # Remove empty categories and convert to simple list of dicts
    grouped_list = [
        {"category": k, "files": v}
        for k, v in grouped.items() if v
    ]

    return templates.TemplateResponse("files.html", {
        "request": request,
        "grouped_files": grouped_list,
        "categories": CATEGORIES,
        "total_count": len(all_files),
    })


@router.post("/files/upload")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    title: str = Form(""),
    category: str = Form("Other"),
    description: str = Form(""),
    db: Session = Depends(get_db),
):
    """Handle a file upload."""
    # Validate extension
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{suffix}' is not allowed. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    # Read content and enforce size limit
    content = await file.read()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=400, detail=f"File exceeds {MAX_FILE_SIZE_MB} MB limit.")

    # Use a UUID filename so we never have path-traversal or collision issues
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    dest = UPLOAD_DIR / stored_name
    dest.write_bytes(content)

    mime_type = file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"
    category = category if category in CATEGORIES else "Other"
    display_title = title.strip() or (file.filename or stored_name)

    db_file = UploadedFile(
        title=display_title,
        original_filename=file.filename or stored_name,
        stored_filename=stored_name,
        category=category,
        description=description.strip() or None,
        file_size=len(content),
        mime_type=mime_type,
    )
    db.add(db_file)
    db.commit()
    log.info("Uploaded file %s (%d bytes) as %s", file.filename, len(content), stored_name)

    return RedirectResponse(url="/files", status_code=303)


@router.get("/files/{file_id}/download")
async def download_file(file_id: int, db: Session = Depends(get_db)):
    """Serve a stored file for download."""
    record = db.get(UploadedFile, file_id)
    if not record:
        raise HTTPException(status_code=404, detail="File not found.")

    path = UPLOAD_DIR / record.stored_filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing from storage.")

    return FileResponse(
        path=str(path),
        media_type=record.mime_type or "application/octet-stream",
        filename=record.original_filename,
    )


@router.post("/files/{file_id}/delete")
async def delete_file(file_id: int, db: Session = Depends(get_db)):
    """Delete a file record and its stored bytes."""
    record = db.get(UploadedFile, file_id)
    if not record:
        raise HTTPException(status_code=404, detail="File not found.")

    path = UPLOAD_DIR / record.stored_filename
    if path.exists():
        path.unlink()

    db.delete(record)
    db.commit()
    log.info("Deleted file id=%d (%s)", file_id, record.original_filename)

    return RedirectResponse(url="/files", status_code=303)
