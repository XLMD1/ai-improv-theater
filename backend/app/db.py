import hashlib
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None):
    database_url = url or get_settings().database_url
    kwargs = {"pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs.update(pool_size=3, max_overflow=2)
    return create_engine(database_url, **kwargs)


def testing_database_id(url):
    """Non-secret identity only for dedicated test databases; never expose a DSN."""
    if url.get_backend_name()!='postgresql' or not (url.database or '').endswith('_test'):
        return None
    scope=[(url.host or '').lower(),url.port or 5432,url.database]
    return hashlib.sha256(json.dumps(scope).encode()).hexdigest()


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
