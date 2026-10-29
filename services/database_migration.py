from decimal import Decimal

from sqlalchemy import Numeric, func, insert, select, text
from sqlalchemy.engine import Engine

from models.entities import Base
from services.database_backup import export_sqlite_backup
from utils.money import money

BATCH_SIZE = 500


class MigrationError(RuntimeError):
    pass


def _money_columns(table):
    return [
        column for column in table.columns
        if isinstance(column.type, Numeric) and column.type.scale == 2
    ]


def _normalize_row(table, row: dict) -> dict:
    for column in _money_columns(table):
        if row.get(column.name) is not None:
            row[column.name] = float(money(row[column.name]))
    return row


def _reset_sequences(connection) -> None:
    if connection.dialect.name != "postgresql":
        return
    for table in Base.metadata.sorted_tables:
        if "id" not in table.columns or not table.columns["id"].primary_key:
            continue
        connection.execute(text(
            f"SELECT setval(pg_get_serial_sequence('\"{table.name}\"', 'id'), "
            f"COALESCE((SELECT MAX(id) FROM \"{table.name}\"), 1), "
            f"(SELECT MAX(id) FROM \"{table.name}\") IS NOT NULL)"
        ))


def _table_summary(connection, table) -> dict:
    summary = {"rows": connection.scalar(select(func.count()).select_from(table)) or 0}
    for column in _money_columns(table):
        total = Decimal("0")
        for (value,) in connection.execute(select(column).where(column.is_not(None))):
            total += money(value)
        summary[column.name] = total
    return summary


def summarize(engine: Engine) -> dict:
    with engine.connect() as connection:
        return {
            table.name: _table_summary(connection, table)
            for table in Base.metadata.sorted_tables
        }


def migrate_database(source: Engine, target: Engine) -> dict:
    """Copia todo o conteúdo de `source` para um banco `target` vazio e valida o resultado.

    A escrita no destino ocorre em uma única transação: qualquer falha ou divergência
    desfaz tudo e deixa o destino intacto. A origem é apenas lida.
    """
    Base.metadata.create_all(bind=target)
    with target.connect() as connection:
        populated = [
            table.name for table in Base.metadata.sorted_tables
            if connection.scalar(select(func.count()).select_from(table))
        ]
    if populated:
        raise MigrationError(
            "O banco de destino já possui dados nas tabelas: "
            + ", ".join(populated) + ". Use um banco vazio."
        )

    with source.connect() as reader, target.begin() as writer:
        for table in Base.metadata.sorted_tables:
            batch = []
            for row in reader.execute(select(table)).mappings():
                batch.append(_normalize_row(table, dict(row)))
                if len(batch) >= BATCH_SIZE:
                    writer.execute(insert(table), batch)
                    batch = []
            if batch:
                writer.execute(insert(table), batch)
        _reset_sequences(writer)

        mismatches = []
        for table in Base.metadata.sorted_tables:
            expected = _table_summary(reader, table)
            actual = _table_summary(writer, table)
            if expected != actual:
                mismatches.append(f"{table.name}: origem={expected} destino={actual}")
        if mismatches:
            raise MigrationError(
                "Validação falhou; nada foi gravado no destino. " + " | ".join(mismatches)
            )
    return summarize(target)


def migrate_with_safety_backup(source: Engine, target: Engine, backup_directory) -> tuple[dict, str]:
    """Salva uma cópia da origem SQLite antes de migrar e retorna o relatório e o arquivo."""
    if not source.url.drivername.startswith("sqlite"):
        raise MigrationError("A origem da migração deve ser um banco SQLite.")
    from datetime import datetime
    from pathlib import Path

    directory = Path(backup_directory)
    directory.mkdir(parents=True, exist_ok=True)
    backup_file = directory / f"pre-migracao-{datetime.now():%Y%m%d-%H%M%S}.sqlite3"
    backup_file.write_bytes(export_sqlite_backup(source))
    return migrate_database(source, target), str(backup_file)
