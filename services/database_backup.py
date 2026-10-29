from contextlib import closing
from datetime import datetime
import logging
import os
from pathlib import Path
import re
import sqlite3
import tempfile

from sqlalchemy.engine import Engine

from utils.clock import local_now


_AUTOMATIC_BACKUP_PATTERN = re.compile(r"cafeteria-(\d{8})-(\d{4})\.sqlite3$")
_logger = logging.getLogger(__name__)


def _sqlite_database_path(engine: Engine) -> Path:
    if not engine.url.drivername.startswith("sqlite"):
        raise ValueError("Backup automático local disponível somente para SQLite.")
    database = engine.url.database
    if not database or database == ":memory:" or engine.url.query.get("mode") == "memory":
        raise ValueError("Backup exige um banco SQLite em arquivo.")
    return Path(database).resolve()


def _is_valid_backup(path: Path) -> bool:
    try:
        with closing(sqlite3.connect(path)) as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            return bool(integrity and integrity[0] == "ok")
    except sqlite3.DatabaseError:
        return False


def _write_backup(source: Path, temporary_path: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(f"Banco SQLite não encontrado: {source}")
    with closing(sqlite3.connect(source)) as source_connection:
        with closing(sqlite3.connect(temporary_path)) as destination_connection:
            source_connection.backup(destination_connection)
    if not _is_valid_backup(temporary_path):
        raise ValueError("A cópia do banco falhou na verificação de integridade.")


def _prune_backups(directory: Path, retention_count: int) -> None:
    if retention_count < 1:
        raise ValueError("BACKUP_RETENTION_COUNT deve ser maior que zero.")
    backups = sorted(
        (
            path for path in directory.iterdir()
            if _AUTOMATIC_BACKUP_PATTERN.fullmatch(path.name)
        ),
        reverse=True,
    )
    for expired_backup in backups[retention_count:]:
        expired_backup.unlink()


def create_automatic_backup(
    engine: Engine,
    backup_directory: Path,
    retention_count: int = 96,
    now: datetime | None = None,
) -> Path | None:
    if not engine.url.drivername.startswith("sqlite"):
        return None
    source = _sqlite_database_path(engine)
    if not source.is_file():
        return None
    if retention_count < 1:
        raise ValueError("BACKUP_RETENTION_COUNT deve ser maior que zero.")

    directory = Path(backup_directory).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = now or local_now()
    bucket_minute = timestamp.minute - timestamp.minute % 15
    bucket = timestamp.replace(minute=bucket_minute, second=0, microsecond=0)
    destination = directory / f"cafeteria-{bucket:%Y%m%d-%H%M}.sqlite3"

    if destination.is_file() and destination.stat().st_size > 0:
        _prune_backups(directory, retention_count)
        return destination

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".cafeteria-backup-", suffix=".sqlite3",
            dir=directory, delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        _write_backup(source, temporary_path)
        os.replace(temporary_path, destination)
    except (OSError, sqlite3.Error, ValueError):
        _logger.exception("Não foi possível criar o backup automático do banco SQLite.")
        raise
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()

    _prune_backups(directory, retention_count)
    return destination


def export_sqlite_backup(engine: Engine) -> bytes:
    source = _sqlite_database_path(engine)
    with tempfile.TemporaryDirectory(prefix="cafeteria-export-") as temporary_directory:
        destination = Path(temporary_directory) / "cafeteria-backup.sqlite3"
        _write_backup(source, destination)
        return destination.read_bytes()


def latest_automatic_backup(backup_directory: Path) -> Path | None:
    directory = Path(backup_directory).expanduser().resolve()
    if not directory.is_dir():
        return None
    backups = sorted(
        (
            path for path in directory.iterdir()
            if _AUTOMATIC_BACKUP_PATTERN.fullmatch(path.name)
        ),
        reverse=True,
    )
    return next(
        (path for path in backups if path.is_file() and path.stat().st_size > 0),
        None,
    )
