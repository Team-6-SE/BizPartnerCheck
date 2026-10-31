import os
from collections.abc import Iterator
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Same .env file as Alembic (project root).
load_dotenv(Path(__file__).resolve().parents[3] / ".env")

# Give up after 5 s if the database is not reachable (e.g. Docker is not running),
# instead of letting a request hang for a long time.
engine = create_engine(
    os.environ["DATABASE_URL"],
    connect_args={"connect_timeout": 5},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one database session per request."""
    with SessionLocal() as session:
        yield session
