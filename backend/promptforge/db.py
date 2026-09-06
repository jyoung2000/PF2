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
    _register_optional_models()
    models.Base.metadata.create_all(_engine)
    applied = migrate_schema(_engine)
    if applied:
        from .logbus import bus
        bus.info("system", f"schema migrated: added {', '.join(applied)}")
    from . import fts
    fts.ensure_fts(_engine)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def _register_optional_models() -> None:
    """Feature areas that keep their tables in their own module but share
    `models.Base` (Film Studio, S1). Import registers them on the metadata."""
    try:
        from .film import models as _film_models  # noqa: F401
        from .forge import models as _forge_models  # noqa: F401
    except ImportError:
        pass


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


def _sql_default(col) -> str | None:
    """SQL literal for ALTER TABLE ADD COLUMN so existing rows get the model's
    default (dict/list JSON defaults become '{}' / '[]')."""
    d = col.default
    if d is None:
        return None
    if getattr(d, "is_callable", False):
        # SQLAlchemy wraps callables (dict, list, utcnow…) — evaluate once to
        # learn the shape; only JSON-shaped defaults become a literal
        try:
            val = d.arg(None)
        except Exception:
            return None
        if isinstance(val, (dict, list)):
            import json
            return "'" + json.dumps(val).replace("'", "''") + "'"
        return None
    v = getattr(d, "arg", None)
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return "'" + v.replace("'", "''") + "'"
    return None


def migrate_schema(engine) -> list[str]:
    """Additive migration (D61): for every model table that already exists,
    add any column the model declares but the table lacks (ALTER TABLE ADD
    COLUMN with the model default) and create missing indexes. Never drops,
    renames, or rewrites rows — existing IDs/media paths/prompts survive."""
    from sqlalchemy import inspect as sa_inspect
    from . import models
    _register_optional_models()
    applied: list[str] = []
    insp = sa_inspect(engine)
    existing = set(insp.get_table_names())
    with engine.begin() as conn:
        for table in models.Base.metadata.sorted_tables:
            if table.name not in existing:
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ddl = (f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" '
                       f'{col.type.compile(engine.dialect)}')
                default = _sql_default(col)
                if default is not None:
                    ddl += f" DEFAULT {default}"
                conn.execute(text(ddl))
                applied.append(f"{table.name}.{col.name}")
            have_idx = {i["name"] for i in insp.get_indexes(table.name)}
            for idx in table.indexes:
                if idx.name and idx.name not in have_idx:
                    idx.create(conn)
                    applied.append(f"index:{idx.name}")
    return applied
