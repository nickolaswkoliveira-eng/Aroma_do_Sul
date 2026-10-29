from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from config import (
    BACKUP_DIRECTORY, BACKUP_RETENTION_COUNT, DATABASE_URL, DEFAULT_DATABASE_URL,
    DEFAULT_DEMO_DATABASE_URL, DEMO_DATABASE_URL, MODO_DEMONSTRACAO,
)


class Base(DeclarativeBase):
    pass


def _engine_options(database_url: str) -> dict:
    if database_url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    # Evita conexões ociosas derrubadas pelo provedor.
    return {"pool_recycle": 1800}


def _sqlite_path(database_url: str) -> Path | None:
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite") or not url.database or url.database == ":memory:":
        return None
    return Path(url.database).resolve()


def _default_database_path_guard(database_url: str, default_url: str) -> None:
    if database_url != default_url:
        return
    filename = make_url(default_url).database
    if not filename:
        return
    configured_path = Path(filename).resolve()
    legacy_path = (Path.cwd() / configured_path.name).resolve()
    if legacy_path != configured_path and legacy_path.is_file():
        raise ValueError(
            f"Foi encontrado um banco em {legacy_path}, mas o caminho padrão atual "
            f"é {configured_path}. Configure DATABASE_URL explicitamente para evitar "
            "abrir um banco vazio ou deixar o histórico inacessível."
        )


_default_database_path_guard(DATABASE_URL, DEFAULT_DATABASE_URL)
_default_database_path_guard(DEMO_DATABASE_URL, DEFAULT_DEMO_DATABASE_URL)

demo_url = make_url(DEMO_DATABASE_URL)
if (
    not demo_url.drivername.startswith("sqlite")
    or not demo_url.database
    or demo_url.database == ":memory:"
    or demo_url.query.get("mode") == "memory"
):
    raise ValueError("DEMO_DATABASE_URL deve apontar para um arquivo SQLite persistente.")

if DATABASE_URL == DEMO_DATABASE_URL or (
    _sqlite_path(DATABASE_URL) is not None
    and _sqlite_path(DATABASE_URL) == _sqlite_path(DEMO_DATABASE_URL)
):
    raise ValueError("DATABASE_URL e DEMO_DATABASE_URL precisam apontar para bancos diferentes.")

engine = create_engine(DATABASE_URL, pool_pre_ping=True, **_engine_options(DATABASE_URL))
demo_engine = create_engine(DEMO_DATABASE_URL, pool_pre_ping=True, **_engine_options(DEMO_DATABASE_URL))
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
DemoSessionLocal = sessionmaker(bind=demo_engine, autoflush=False, expire_on_commit=False)


def get_session(demo: bool | None = None):
    use_demo_database = MODO_DEMONSTRACAO if demo is None else demo
    return (DemoSessionLocal if use_demo_database else SessionLocal)()


def init_database(demo: bool | None = None) -> None:
    from models.entities import Base as ModelsBase

    use_demo_database = MODO_DEMONSTRACAO if demo is None else demo
    target_engine = demo_engine if use_demo_database else engine
    if not use_demo_database:
        from services.database_backup import create_automatic_backup

        create_automatic_backup(
            target_engine,
            BACKUP_DIRECTORY,
            BACKUP_RETENTION_COUNT,
        )
    ModelsBase.metadata.create_all(bind=target_engine)
