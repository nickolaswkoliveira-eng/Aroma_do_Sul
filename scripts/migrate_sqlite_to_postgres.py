"""Migra o banco SQLite local para o PostgreSQL configurado em DATABASE_URL.

Uso (PowerShell):
  $env:DATABASE_URL = "postgresql://postgres:SENHA@host:5432/postgres"
  py -3 scripts/migrate_sqlite_to_postgres.py --source cafeteria.db

A origem é somente lida. Uma cópia dela é salva em backups/ antes da migração, a
escrita no destino é transacional e os totais por tabela são conferidos ao final.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from config import BACKUP_DIRECTORY, DATABASE_URL, PROJECT_ROOT
from services.database_migration import MigrationError, migrate_with_safety_backup


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=str(PROJECT_ROOT / "cafeteria.db"))
    arguments = parser.parse_args()

    source_path = Path(arguments.source).resolve()
    if not source_path.is_file():
        print(f"ERRO: banco de origem não encontrado: {source_path}", file=sys.stderr)
        return 2
    if DATABASE_URL.startswith("sqlite"):
        print("ERRO: DATABASE_URL ainda aponta para SQLite; configure o PostgreSQL de destino.", file=sys.stderr)
        return 2

    source = create_engine(f"sqlite:///{source_path.as_posix()}")
    target = create_engine(DATABASE_URL, pool_pre_ping=True)
    try:
        report, backup_file = migrate_with_safety_backup(source, target, BACKUP_DIRECTORY)
    except (MigrationError, SQLAlchemyError, OSError) as error:
        print(f"ERRO: {error}", file=sys.stderr)
        return 1
    print(f"Cópia de segurança da origem: {backup_file}")
    for table, summary in report.items():
        extras = ", ".join(f"{key}={value}" for key, value in summary.items() if key != "rows")
        print(f"  {table}: {summary['rows']} linhas" + (f" ({extras})" if extras else ""))
    print("Migração validada: contagens e totais monetários conferem.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
