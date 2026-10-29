from datetime import datetime
from pathlib import Path
import sqlite3
from contextlib import closing

from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import Engine

from models.entities import BackupRun
from utils.clock import local_now
from services.database_backup import latest_automatic_backup


def database_health(engine: Engine, backup_directory: Path) -> dict:
    result = {
        "connected": False,
        "integrity": None,
        "table_count": 0,
        "latest_backup": None,
        "backup_age_minutes": None,
    }
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            result["connected"] = True
            result["table_count"] = len(inspect(connection).get_table_names())

        if engine.url.drivername.startswith("sqlite"):
            database = engine.url.database
            if database and database != ":memory:":
                with closing(sqlite3.connect(database)) as connection:
                    check = connection.execute("PRAGMA integrity_check").fetchone()
                    result["integrity"] = check[0] if check else "desconhecida"
        else:
            with engine.connect() as connection:
                if "backup_execucoes" in inspect(connection).get_table_names():
                    last = connection.execute(
                        select(func.max(BackupRun.created_at)).where(BackupRun.status == "Sucesso")
                    ).scalar()
                    if last:
                        result["external_backup_at"] = last
                        result["external_backup_age_hours"] = round(
                            max(0, (local_now() - last).total_seconds() / 3600), 1
                        )
            return result

        backup = latest_automatic_backup(backup_directory)
        if backup:
            result["latest_backup"] = backup
            modified = datetime.fromtimestamp(backup.stat().st_mtime)
            result["backup_age_minutes"] = round(
                max(0, (local_now().replace(tzinfo=None) - modified).total_seconds() / 60),
                1,
            )
    except Exception as error:
        result["error"] = str(error)
    return result
