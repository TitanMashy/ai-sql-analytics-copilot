from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings


def _engine_options(database_url: str, settings=None) -> dict[str, object]:
    if database_url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}, "poolclass": StaticPool}
    options: dict[str, object] = {
        "pool_pre_ping": True,
        "pool_size": settings.database_pool_size if settings else 5,
        "max_overflow": settings.database_max_overflow if settings else 10,
        "pool_timeout": settings.database_pool_timeout_seconds if settings else 5.0,
        "pool_recycle": settings.database_pool_recycle_seconds if settings else 1800,
    }
    if database_url.startswith("postgresql"):
        options["connect_args"] = {
            "connect_timeout": settings.database_connect_timeout_seconds if settings else 5
        }
    return options


settings = get_settings()
engine = create_engine(settings.database_url, **_engine_options(settings.database_url, settings))
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection: Any, connection_record: object) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
