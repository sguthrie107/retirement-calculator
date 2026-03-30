"""Database configuration and session management."""
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator
import json
from pathlib import Path
from datetime import datetime

from .config import DATABASE_URL
from .models import Base, User, Account, ActualBalance

log = logging.getLogger(__name__)

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
            username = user_data["name"]
            existing_user = db.query(User).filter(User.name == username).first()
            if not existing_user:
                existing_user = User(name=username)
                db.add(existing_user)
                db.flush()

            chart_seed = user_data.get("chart_seed", {})
            seed_actual_balances = chart_seed.get("actual_balances", [])

            for seed_row in seed_actual_balances:
                year = int(seed_row.get("year", 0))
                if year <= 0:
                    continue

                account_balances = seed_row.get("account_balances", {})
                for account_type in ("401k", "roth_ira"):
                    seeded_balance = account_balances.get(account_type)
                    if seeded_balance is None:
                        continue

                    account = (
                        db.query(Account)
                        .filter(Account.user_id == existing_user.id, Account.account_type == account_type)
                        .first()
                    )
                    if not account:
                        account = Account(user_id=existing_user.id, account_type=account_type)
                        db.add(account)
                        db.flush()

                    existing_actual = (
                        db.query(ActualBalance)
                        .filter(ActualBalance.account_id == account.id, ActualBalance.year == year)
                        .first()
                    )
                    if existing_actual:
                        continue

                    db.add(
                        ActualBalance(
                            account_id=account.id,
                            year=year,
                            balance=float(seeded_balance),
                            notes="Seeded from users.json chart_seed.actual_balances",
                            recorded_at=datetime.utcnow().isoformat(),
                        )
                    )
        
        db.commit()
    except Exception:
        db.rollback()
        log.exception("Error seeding users")
    finally:
        db.close()


def _migrate_assumptions_json_column():
    """Drop stress_test_results if assumptions_json is still a legacy TEXT/VARCHAR column.

    The column was changed from String → JSON in the SQLAlchemy model.  SQLAlchemy's
    create_all() never alters existing tables, so an existing deployment that was
    created under the old schema would have a TEXT column.  Inserting a Python dict
    into a PostgreSQL TEXT column raises ``ProgrammingError: can't adapt type 'dict'``.
    Dropping the table here lets create_all() recreate it with the correct JSON type.
    Stress-test results are re-computed on demand so data loss is acceptable.
    """
    from sqlalchemy import inspect, text as sa_text

    inspector = inspect(engine)
    if not inspector.has_table("stress_test_results"):
        return

    columns = {col["name"]: col for col in inspector.get_columns("stress_test_results")}
    assumptions_col = columns.get("assumptions_json")
    if not assumptions_col:
        return

    col_type_str = str(assumptions_col["type"]).upper()
    # JSON columns report as "JSON" or "JSONB"; old String columns report "VARCHAR" or "TEXT".
    if "JSON" not in col_type_str:
        with engine.begin() as conn:
            conn.execute(sa_text("DROP TABLE stress_test_results"))
        log.info("Migrated stress_test_results: dropped legacy TEXT assumptions_json column (will be recreated as JSON)")


def init_db():
    """Initialize database tables and seed default data."""
    _migrate_assumptions_json_column()
    Base.metadata.create_all(bind=engine)
    seed_default_users()


def get_db() -> Generator[Session, None, None]:
    """Dependency for getting database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
