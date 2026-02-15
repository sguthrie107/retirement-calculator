"""SQLAlchemy ORM models."""
from sqlalchemy import Column, Integer, String, Float, ForeignKey, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import relationship, DeclarativeBase
from datetime import datetime


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    created_at = Column(String, nullable=False, default=lambda: datetime.utcnow().isoformat())
    
    accounts = relationship("Account", back_populates="user", cascade="all, delete-orphan")


class Account(Base):
    __tablename__ = "accounts"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    account_type = Column(String, nullable=False)
    provider = Column(String)
    
    user = relationship("User", back_populates="accounts")
    actual_balances = relationship("ActualBalance", back_populates="account", cascade="all, delete-orphan")
    
    __table_args__ = (
        UniqueConstraint("user_id", "account_type", name="uq_user_account_type"),
        CheckConstraint("account_type IN ('401k', 'roth_ira')", name="ck_account_type"),
    )


class ActualBalance(Base):
    __tablename__ = "actual_balances"
    
    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    year = Column(Integer, nullable=False)
    balance = Column(Float, nullable=False)
    notes = Column(String)
    recorded_at = Column(String, nullable=False, default=lambda: datetime.utcnow().isoformat())
    
    account = relationship("Account", back_populates="actual_balances")
    
    __table_args__ = (
        UniqueConstraint("account_id", "year", name="uq_account_year"),
        CheckConstraint("balance >= 0", name="ck_balance_positive"),
    )
