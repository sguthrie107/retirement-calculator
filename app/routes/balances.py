"""Balance management routes."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from ..database import get_db
from ..models import User, Account, ActualBalance
from ..schemas import BalanceCreate, BalanceUpdate, BalanceResponse

router = APIRouter(prefix="/api/balances")


@router.post("/{username}", response_model=BalanceResponse, status_code=status.HTTP_201_CREATED)
async def create_balance(
    username: str,
    balance_data: BalanceCreate,
    db: Session = Depends(get_db)
):
    """
    Create a new actual balance entry for a user.
    
    Args:
        username: Name of user
        balance_data: Balance data to create
        
    Returns:
        Created balance record
        
    Raises:
        409: If balance for this year already exists
        404: If user not found
    """
    # Get or create user
    user = db.query(User).filter(User.name == username).first()
    if not user:
        user = User(name=username)
        db.add(user)
        db.commit()
        db.refresh(user)
    
    # Get or create account
    account = (
        db.query(Account)
        .filter(Account.user_id == user.id, Account.account_type == balance_data.account_type)
        .first()
    )
    if not account:
        account = Account(user_id=user.id, account_type=balance_data.account_type)
        db.add(account)
        db.commit()
        db.refresh(account)
    
    # Create balance entry
    actual_balance = ActualBalance(
        account_id=account.id,
        year=balance_data.year,
        balance=balance_data.balance,
        notes=balance_data.notes,
    )
    
    try:
        db.add(actual_balance)
        db.commit()
        db.refresh(actual_balance)
        return actual_balance
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Balance for {balance_data.account_type} in year {balance_data.year} already exists"
        )


@router.get("/{username}", response_model=list[BalanceResponse])
async def get_balances(username: str, db: Session = Depends(get_db)):
    """Get all actual balances for a user."""
    user = db.query(User).filter(User.name == username).first()
    if not user:
        return []
    
    balances = (
        db.query(ActualBalance)
        .join(Account)
        .filter(Account.user_id == user.id)
        .order_by(ActualBalance.year.desc())
        .all()
    )
    
    return balances


@router.get("/record/{balance_id}", response_model=dict)
async def get_single_balance(balance_id: int, db: Session = Depends(get_db)):
    """Get a single balance record by ID with account type."""
    balance = db.query(ActualBalance).filter(ActualBalance.id == balance_id).first()
    if not balance:
        raise HTTPException(status_code=404, detail="Balance not found")
    
    account = db.query(Account).filter(Account.id == balance.account_id).first()
    account_type = account.account_type if account else "unknown"
    
    return {
        "id": balance.id,
        "account_id": balance.account_id,
        "account_type": account_type,
        "year": balance.year,
        "balance": balance.balance,
        "notes": balance.notes,
        "recorded_at": balance.recorded_at,
    }


@router.put("/{balance_id}", response_model=BalanceResponse)
async def update_balance(
    balance_id: int,
    balance_data: BalanceUpdate,
    db: Session = Depends(get_db)
):
    """Update an existing balance entry. Only updates timestamp if balance value changed."""
    from datetime import datetime
    
    balance = db.query(ActualBalance).filter(ActualBalance.id == balance_id).first()
    if not balance:
        raise HTTPException(status_code=404, detail="Balance not found")
    
    # Check if balance value actually changed
    balance_changed = balance.balance != balance_data.balance
    
    # Update values
    balance.balance = balance_data.balance
    if balance_data.notes is not None:
        balance.notes = balance_data.notes
    
    # Only update timestamp if balance value changed
    if balance_changed:
        balance.recorded_at = datetime.utcnow().isoformat()
    
    db.commit()
    db.refresh(balance)
    return balance


@router.delete("/{balance_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_balance(balance_id: int, db: Session = Depends(get_db)):
    """Delete a balance entry."""
    print(f"DEBUG: Delete requested for balance_id: {balance_id}")
    balance = db.query(ActualBalance).filter(ActualBalance.id == balance_id).first()
    if not balance:
        print(f"DEBUG: Balance not found with id: {balance_id}")
        raise HTTPException(status_code=404, detail="Balance not found")
    
    print(f"DEBUG: Deleting balance: {balance.id}, year: {balance.year}, amount: {balance.balance}")
    db.delete(balance)
    db.commit()
    print(f"DEBUG: Balance deleted successfully")
    return None
