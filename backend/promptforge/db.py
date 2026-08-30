"""SQLite (WAL) engine + session management. Sync SQLAlchemy throughout (D2)."""
from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from .config import get_config

_engine = None
_SessionLocal: sessionmaker | None = None


def _apply_pragmas(dbapi_conn, _record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=15000")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()


def init_db(echo: bool = False):
    """Create (or return) the process-wide engine and create all tables."""
    global _engine, _SessionLocal
    if _engine is not None:
        return _engine
    cfg = get_config()
    cfg.ensure_dirs()
    _engine = create_engine(
        f"sqlite:///{cfg.db_path}", echo=echo,
        connect_args={"check_same_thread": False},
    )
    event.listen(_engine, "connect", _apply_pragmas)
    from . import models  # noqa: F401  (register tables)
    models.Base.metadata.create_all(_engine)
    from . import fts
    fts.ensure_fts(_engine)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def dispose_db() -> None:
    """Test hook: drop the engine so the next init_db() rebuilds against the
    current config."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def get_engine():
    if _engine is None:
        init_db()
    return _engine


@contextmanager
def session_scope() -> Session:
    if _SessionLocal is None:
        init_db()
    session: Session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db():
    """FastAPI dependency."""
    with session_scope() as s:
        yield s


def wal_mode(engine=None) -> str:
    engine = engine or get_engine()
    with engine.connect() as conn:
        return conn.execute(text("PRAGMA journal_mode")).scalar_one()
