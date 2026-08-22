"""Relational persistence layer for user/admin accounts (users.db).

This module was referenced everywhere in the original project --
`alembic/env.py` (`from database_persistence import Base`), `main.py`
(`from database_persistence import get_db, UserModel`), `tests/test_security.py`
(`from database_persistence import Base`), and the README's manual admin-seed
snippet (`from database_persistence import SessionLocal, UserModel,
pwd_context`) -- but the file itself was never actually included anywhere in
the delivered notebook. Every one of those imports would fail with
`ModuleNotFoundError` without it; this is that missing module.

The `UserModel` schema below matches the two Alembic migrations exactly
(`alembic/versions/1a2b3c4d5e6f_initial.py` creates the base table,
`.../6f5e4d3c2b1a_add_active.py` adds `is_active`), so `alembic upgrade head`
and `Base.metadata.create_all()` (used directly by the test suite) produce
the same table shape.
"""

from __future__ import annotations

import os

from passlib.context import CryptContext
from sqlalchemy import Boolean, Column, DateTime, Integer, String, create_engine, func
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# Matches alembic.ini's default `sqlalchemy.url` and the DATABASE_URL override
# pattern already used by alembic/env.py and docker-compose.yml.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./users.db")

# check_same_thread=False is required for SQLite when the same connection
# pool is shared across FastAPI's threaded request handlers.
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Shared password hashing context. main.py also defines its own `pwd_context`
# instance (harmless duplication -- CryptContext is stateless per hash/verify
# call); this one is exported here to match the README's admin-seed snippet,
# which imports it from this module.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class Base(DeclarativeBase):
    pass


class UserModel(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, server_default="agent")
    is_active = Column(Boolean, nullable=False, server_default="1")
    created_at = Column(DateTime, nullable=False, server_default=func.now())


def get_db() -> Session:
    """FastAPI dependency: yields a request-scoped DB session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
