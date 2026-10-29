"""Backup diário criptografado do PostgreSQL para o Supabase Storage privado.

Variáveis de ambiente exigidas (guarde-as apenas no agendador, nunca no app):
DATABASE_URL, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, BACKUP_ENCRYPTION_KEY.
Opcional: SUPABASE_BACKUP_BUCKET (padrão: database-backups).
"""
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from config import DATABASE_URL
import config
from models.entities import BackupRun
from services.postgres_backup import BackupError, SupabaseStorage, run_backup


def _required(name: str) -> str:
    value = config._setting(name)
    if not value:
        raise BackupError(f"Variável de ambiente ausente: {name}")
    return value


def main() -> int:
    try:
        storage = SupabaseStorage(
            _required("SUPABASE_URL"),
            _required("SUPABASE_SERVICE_ROLE_KEY"),
            config._setting("SUPABASE_BACKUP_BUCKET", "database-backups"),
        )
        now = datetime.now()
        result = run_backup(DATABASE_URL, storage, _required("BACKUP_ENCRYPTION_KEY"), now)
        engine = create_engine(DATABASE_URL, pool_pre_ping=True)
        BackupRun.__table__.create(bind=engine, checkfirst=True)
        with Session(engine) as session:
            session.add(BackupRun(
                location=f"{storage.bucket}/{result['name']}",
                size_bytes=result["size_bytes"],
                status="Sucesso",
                created_at=now,
            ))
            session.commit()
    except BackupError as error:
        print(f"ERRO: {error}", file=sys.stderr)
        return 1
    print(f"Backup concluído: {result['name']} ({result['size_bytes']} bytes); removidos pela retenção: {len(result['removed'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
