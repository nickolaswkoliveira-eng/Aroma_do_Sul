from collections import defaultdict
from contextlib import contextmanager
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Iterator

from sqlalchemy import URL, create_engine, delete, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from database.connection import Base, DemoSessionLocal, demo_engine
from models.entities import (
    Audit, CashFlow, CashMovement, CashSession, Category, Comanda, ComandaOrder,
    Customer, DemoRecord, Ingredient, Order, OrderItem, Payable, Product,
    Receivable, RecipeItem, Role, RolePermission, Stock, StockMovement, User,
)
from utils.clock import local_now


MAX_BACKUP_SIZE_BYTES = 100 * 1024 * 1024
BACKUP_FORMAT_VERSION = 1

_DEMO_MODELS_TO_DELETE = (
    CashFlow, CashMovement, ComandaOrder, OrderItem, StockMovement, RecipeItem,
    Ingredient, Stock, Payable, Receivable, CashSession, Order, Comanda, Customer,
    Product, Category, Audit,
)
_DEMO_MODELS_BY_TABLE = {model.__tablename__: model for model in _DEMO_MODELS_TO_DELETE}
_TRACKED_DEMO_MODELS = frozenset(_DEMO_MODELS_TO_DELETE)
_ALL_MODELS_BY_TABLE = {
    model.__tablename__: model
    for model in (
        Audit, CashFlow, CashMovement, CashSession, Category, Comanda,
        ComandaOrder, Customer, DemoRecord, Ingredient, Order, OrderItem,
        Payable, Product, Receivable, RecipeItem, Role, RolePermission, Stock,
        StockMovement, User,
    )
}
_PROTECTED_TABLES = (
    "perfis", "permissoes", "perfil_permissoes", "usuarios",
    "auditoria_login", "auditoria",
)
_LEGACY_OPTIONAL_BACKUP_TABLES = {"comandas", "comanda_pedidos"}


def _track_new_demo_records(session: Session, flush_context, instances) -> None:
    if not session.info.get("track_demo_records"):
        return
    pending = session.info.setdefault("pending_demo_records", [])
    pending.extend(
        instance for instance in session.new
        if type(instance) in _TRACKED_DEMO_MODELS
    )


def _persist_demo_record_markers(session: Session, flush_context) -> None:
    pending = session.info.get("pending_demo_records", [])
    if not pending:
        return
    session.add_all(
        DemoRecord(entity=type(instance).__tablename__, record_id=instance.id, demo=True)
        for instance in pending
        if instance.id is not None
    )
    pending.clear()


@contextmanager
def track_demo_records(session: Session) -> Iterator[None]:
    event.listen(session, "before_flush", _track_new_demo_records)
    event.listen(session, "after_flush_postexec", _persist_demo_record_markers)
    session.info["track_demo_records"] = True
    try:
        yield
    finally:
        session.info.pop("track_demo_records", None)
        session.info.pop("pending_demo_records", None)
        event.remove(session, "before_flush", _track_new_demo_records)
        event.remove(session, "after_flush_postexec", _persist_demo_record_markers)


def _ensure_no_unmarked_references(
    session: Session,
    demo_ids_by_table: dict[str, set[int]],
) -> None:
    for child_table, child_model in _ALL_MODELS_BY_TABLE.items():
        marked_child_ids = demo_ids_by_table.get(child_table, set())
        for foreign_key in child_model.__table__.foreign_keys:
            parent_table = foreign_key.column.table.name
            parent_ids = demo_ids_by_table.get(parent_table, set())
            if not parent_ids:
                continue

            child_column = child_model.__table__.c[foreign_key.parent.name]
            referencing_ids = set(session.scalars(
                select(child_model.id).where(child_column.in_(parent_ids))
            ))
            unmarked_references = referencing_ids - marked_child_ids
            if unmarked_references:
                raise ValueError(
                    "A limpeza foi bloqueada: registros não demonstrativos "
                    f"referenciam dados marcados para exclusão ({child_table}). "
                    "Remova ou reclassifique esses vínculos antes de tentar novamente."
                )


def clear_demo_records(session: Session) -> int:
    markers = session.scalars(
        select(DemoRecord).where(DemoRecord.demo.is_(True))
    ).all()
    ids_by_table: dict[str, set[int]] = defaultdict(set)
    for marker in markers:
        if marker.entity not in _DEMO_MODELS_BY_TABLE:
            raise ValueError(
                f"Limpeza bloqueada: entidade demo desconhecida ({marker.entity})."
            )
        ids_by_table[marker.entity].add(marker.record_id)

    _ensure_no_unmarked_references(session, ids_by_table)
    deleted_count = 0
    for model in _DEMO_MODELS_TO_DELETE:
        record_ids = ids_by_table.get(model.__tablename__, set())
        sorted_ids = sorted(record_ids)
        for start in range(0, len(sorted_ids), 500):
            result = session.execute(
                delete(model).where(model.id.in_(sorted_ids[start:start + 500]))
            )
            deleted_count += result.rowcount or 0

    session.execute(delete(DemoRecord).where(DemoRecord.demo.is_(True)))
    return deleted_count


def _database_path(engine: Engine) -> Path:
    database = engine.url.database
    if not database or database == ":memory:" or engine.url.query.get("mode") == "memory":
        raise ValueError("A operação exige o banco SQLite persistente de demonstração.")
    return Path(database).resolve()


def _copy_database(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(f"Banco de demonstração não encontrado: {source}")
    with closing(sqlite3.connect(source)) as source_connection:
        with closing(sqlite3.connect(destination)) as destination_connection:
            source_connection.backup(destination_connection)
            destination_connection.execute(
                f"PRAGMA user_version = {BACKUP_FORMAT_VERSION}"
            )
            destination_connection.commit()


def create_automatic_backup(
    engine: Engine = demo_engine,
    backup_directory: Path | None = None,
) -> Path:
    source = _database_path(engine)
    directory = backup_directory or source.parent / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = local_now().strftime("%Y%m%d-%H%M%S-%f")
    destination = directory / f"demo-backup-{timestamp}.sqlite3"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".demo-backup-", suffix=".tmp", dir=directory, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
        _copy_database(source, temporary_path)
        os.replace(temporary_path, destination)
        return destination
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def export_demo_backup(engine: Engine = demo_engine) -> bytes:
    source = _database_path(engine)
    with tempfile.TemporaryDirectory(prefix="demo-export-") as temporary_directory:
        destination = Path(temporary_directory) / "demo-backup.sqlite3"
        _copy_database(source, destination)
        return destination.read_bytes()


def _validate_backup(path: Path) -> None:
    try:
        with closing(sqlite3.connect(path)) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version != BACKUP_FORMAT_VERSION:
                raise ValueError("Versão de backup não suportada.")

            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise ValueError("O arquivo de backup está corrompido.")

            existing_tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            required_tables = set(Base.metadata.tables)
            missing_tables = required_tables - existing_tables
            if missing_tables - _LEGACY_OPTIONAL_BACKUP_TABLES:
                raise ValueError(
                    "O arquivo não contém o esquema completo de backup deste aplicativo."
                )
            unexpected_tables = existing_tables - required_tables - {"sqlite_sequence"}
            if unexpected_tables:
                raise ValueError("O arquivo contém tabelas não reconhecidas.")

            foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchone()
            if foreign_key_errors:
                raise ValueError("O backup contém relacionamentos inconsistentes.")
    except sqlite3.DatabaseError as error:
        raise ValueError("O arquivo enviado não é um backup SQLite válido.") from error


def _ensure_backup_schema(database_path: Path) -> None:
    backup_engine = create_engine(URL.create("sqlite", database=str(database_path)))
    try:
        Base.metadata.create_all(backup_engine)
    finally:
        backup_engine.dispose()


def _ensure_current_database_is_demo_only(session: Session) -> None:
    markers = session.execute(
        select(DemoRecord.entity, DemoRecord.record_id)
        .where(DemoRecord.demo.is_(True), DemoRecord.entity != "auditoria")
    ).all()
    demo_ids_by_table: dict[str, set[int]] = defaultdict(set)
    for entity, record_id in markers:
        demo_ids_by_table[entity].add(record_id)

    for model in _DEMO_MODELS_TO_DELETE:
        if model is Audit:
            continue
        existing_ids = set(session.scalars(select(model.id)))
        unmarked_ids = existing_ids - demo_ids_by_table.get(model.__tablename__, set())
        if unmarked_ids:
            raise ValueError(
                "A importação foi bloqueada para preservar registros sem marca "
                f"demo=True na tabela {model.__tablename__}. Apague-os ou faça a "
                "classificação manual antes de importar."
            )


def _read_protected_rows(database_path: Path) -> dict[str, list[tuple]]:
    with closing(sqlite3.connect(database_path)) as connection:
        connection.row_factory = sqlite3.Row
        demo_audit_ids = {
            row[0] for row in connection.execute(
                "SELECT record_id FROM registros_demo "
                "WHERE entity = 'auditoria' AND demo = 1"
            )
        }
        protected_rows: dict[str, list[tuple]] = {}
        for table in _PROTECTED_TABLES:
            rows = connection.execute(f'SELECT * FROM "{table}"').fetchall()
            if table == "auditoria":
                rows = [row for row in rows if row["id"] not in demo_audit_ids]
            protected_rows[table] = [tuple(row) for row in rows]
        return protected_rows


def _restore_protected_rows(
    database_path: Path,
    protected_rows: dict[str, list[tuple]],
) -> None:
    with closing(sqlite3.connect(database_path)) as connection:
        for table in reversed(_PROTECTED_TABLES):
            connection.execute(f'DELETE FROM "{table}"')
        connection.execute(
            "DELETE FROM registros_demo WHERE entity = 'auditoria'"
        )
        for table in _PROTECTED_TABLES:
            columns = [
                row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')
            ]
            if not columns:
                raise ValueError(f"O backup não contém a tabela necessária: {table}.")
            quoted_columns = ", ".join(f'"{column}"' for column in columns)
            placeholders = ", ".join("?" for _ in columns)
            connection.executemany(
                f'INSERT INTO "{table}" ({quoted_columns}) VALUES ({placeholders})',
                protected_rows[table],
            )
        connection.commit()


def delete_demo_data(
    session: Session,
    responsible: str,
    action: str,
    engine: Engine = demo_engine,
    backup_directory: Path | None = None,
) -> tuple[int, Path]:
    backup_path = create_automatic_backup(engine, backup_directory)
    try:
        deleted_count = clear_demo_records(session)
        session.add(Audit(
            responsible=responsible[:80],
            action=action,
            details=f"{deleted_count} registros demo removidos. Backup automático: {backup_path}",
            created_at=local_now(),
        ))
        session.commit()
    finally:
        if session.in_transaction():
            session.rollback()
    return deleted_count, backup_path


def export_demo_data(
    session: Session,
    responsible: str,
    engine: Engine = demo_engine,
) -> bytes:
    try:
        session.add(Audit(
            responsible=responsible[:80],
            action="Backup do ambiente de demonstração exportado",
            details="Backup SQLite completo do ambiente demo.",
            created_at=local_now(),
        ))
        session.commit()
        return export_demo_backup(engine)
    finally:
        if session.in_transaction():
            session.rollback()


def restore_demo_backup(
    session: Session,
    backup_data: bytes,
    responsible: str,
    engine: Engine = demo_engine,
    backup_directory: Path | None = None,
) -> Path:
    if not backup_data:
        raise ValueError("Selecione um arquivo de backup.")
    if len(backup_data) > MAX_BACKUP_SIZE_BYTES:
        raise ValueError("O arquivo excede o limite de 100 MB.")

    destination = _database_path(engine)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".demo-restore-", suffix=".sqlite3",
            dir=destination.parent, delete=False,
        ) as temporary:
            temporary.write(backup_data)
            temporary_path = Path(temporary.name)
        _validate_backup(temporary_path)
        _ensure_backup_schema(temporary_path)

        _ensure_current_database_is_demo_only(session)
        backup_path = create_automatic_backup(engine, backup_directory)
        session.commit()
        protected_rows = _read_protected_rows(destination)
        session.close()
        engine.dispose()

        _restore_protected_rows(temporary_path, protected_rows)
        with closing(sqlite3.connect(temporary_path)) as connection:
            connection.execute(
                "INSERT INTO auditoria (responsible, action, details, created_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    responsible[:80],
                    "Backup do ambiente de demonstração importado",
                    f"Backup restaurado. Backup anterior: {backup_path}",
                    local_now().isoformat(sep=" "),
                ),
            )
            connection.commit()

        os.replace(temporary_path, destination)
        return backup_path
    finally:
        if session.in_transaction():
            session.rollback()
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()
