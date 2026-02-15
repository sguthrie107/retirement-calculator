"""Database configuration and session management."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator
import json
from pathlib import Path

from .config import DATABASE_URL
from .models import Base, User

# Create engine
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def seed_default_users():
    """Load default users from users.json into the database."""
    db = SessionLocal()
    try:
        # Load users from JSON
        users_file = Path(__file__).parent.parent / "data" / "users.json"
        
        if not users_file.exists():
            return
        
        with open(users_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Insert each user if not already present
        for user_data in data.get("users", []):
            existing_user = db.query(User).filter(User.name == user_data["name"]).first()
            if not existing_user:
                new_user = User(name=user_data["name"])
                db.add(new_user)
        
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Error seeding users: {e}")
    finally:
        db.close()


def init_db():
    """Initialize database tables and seed default data."""
    Base.metadata.create_all(bind=engine)
    seed_default_users()


def get_db() -> Generator[Session, None, None]:
    """Dependency for getting database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
