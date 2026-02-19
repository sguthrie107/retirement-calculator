"""Seed or reset Steven debug actual-balance profile for chart testing.

Usage:
  python scripts/steven_debug_profile.py --action seed
  python scripts/steven_debug_profile.py --action reset
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import datetime
from pathlib import Path

from app.database import SessionLocal
from app.models import Account, ActualBalance, User
from app.services.projection import get_user_projection

CURRENT_YEAR = 2026
TARGET_AGE = 51
USERNAME = "Steven"
SEED = 20260219
DEBUG_NOTE = "debug_profile_seed_age_51"


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _target_year() -> int:
    users_path = _project_root() / "data" / "users.json"
    with open(users_path, "r", encoding="utf-8") as f:
        users_data = json.load(f)
    profile = next(u for u in users_data.get("users", []) if u.get("name") == USERNAME)
    current_age = int(profile.get("age", 29))
    return CURRENT_YEAR + max(0, TARGET_AGE - current_age)


def _build_debug_rows() -> list[tuple[int, float, float]]:
    target_year = _target_year()
    projection = get_user_projection(USERNAME, current_year=CURRENT_YEAR)["projected"]
    projection = [row for row in projection if int(row["year"]) <= target_year]

    rng = random.Random(SEED)
    portfolio_state = 0.0
    k401_state = 0.0
    ira_state = 0.0

    rows: list[tuple[int, float, float]] = []
    for row in projection:
        year = int(row["year"])
        projected_accounts = row.get("account_balances", {})
        projected_401k = float(projected_accounts.get("401k", 0.0))
        projected_ira = float(projected_accounts.get("roth_ira", 0.0))

        portfolio_state = 0.45 * portfolio_state + rng.gauss(0.0, 0.065)
        k401_state = 0.40 * k401_state + rng.gauss(0.0, 0.030)
        ira_state = 0.40 * ira_state + rng.gauss(0.0, 0.028)

        k401_multiplier = max(0.75, min(1.25, 1.0 + portfolio_state + k401_state))
        ira_multiplier = max(0.78, min(1.22, 1.0 + portfolio_state + ira_state))

        actual_401k = max(0.0, projected_401k * k401_multiplier)
        actual_ira = max(0.0, projected_ira * ira_multiplier)
        rows.append((year, actual_401k, actual_ira))

    return rows


def seed_debug_profile() -> None:
    rows = _build_debug_rows()

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.name == USERNAME).first()
        if not user:
            user = User(name=USERNAME)
            db.add(user)
            db.flush()

        acct_401k = db.query(Account).filter(Account.user_id == user.id, Account.account_type == "401k").first()
        if not acct_401k:
            acct_401k = Account(user_id=user.id, account_type="401k", provider="DebugSeed")
            db.add(acct_401k)
            db.flush()

        acct_ira = db.query(Account).filter(Account.user_id == user.id, Account.account_type == "roth_ira").first()
        if not acct_ira:
            acct_ira = Account(user_id=user.id, account_type="roth_ira", provider="DebugSeed")
            db.add(acct_ira)
            db.flush()

        updated_count = 0
        inserted_count = 0
        timestamp = datetime.utcnow().isoformat()

        for year, actual_401k, actual_ira in rows:
            for account, balance in ((acct_401k, actual_401k), (acct_ira, actual_ira)):
                existing = (
                    db.query(ActualBalance)
                    .filter(ActualBalance.account_id == account.id, ActualBalance.year == year)
                    .first()
                )
                if existing:
                    existing.balance = round(balance, 2)
                    existing.notes = DEBUG_NOTE
                    existing.recorded_at = timestamp
                    updated_count += 1
                else:
                    db.add(
                        ActualBalance(
                            account_id=account.id,
                            year=year,
                            balance=round(balance, 2),
                            notes=DEBUG_NOTE,
                            recorded_at=timestamp,
                        )
                    )
                    inserted_count += 1

        db.commit()
        print(f"seed complete: years={len(rows)}, inserted={inserted_count}, updated={updated_count}")
    finally:
        db.close()


def reset_debug_profile() -> None:
    db = SessionLocal()
    try:
        rows = (
            db.query(ActualBalance)
            .join(Account)
            .join(User)
            .filter(User.name == USERNAME, ActualBalance.notes == DEBUG_NOTE)
            .all()
        )
        count = len(rows)
        for row in rows:
            db.delete(row)
        db.commit()
        print(f"reset complete: deleted={count}")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=["seed", "reset"], required=True)
    args = parser.parse_args()

    if args.action == "seed":
        seed_debug_profile()
    else:
        reset_debug_profile()


if __name__ == "__main__":
    main()
