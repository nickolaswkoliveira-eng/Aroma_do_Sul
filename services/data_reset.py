from datetime import datetime
from pathlib import Path
import tempfile

from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from models.entities import (
    Audit, Base, CashFlow, CashMovement, CashSession, Category, Comanda, ComandaOrder, Customer,
    DemoRecord, Ingredient, Order, OrderItem, Payable, Product, Receivable, RecipeItem,
    Stock, StockMovement,
)
from services.database_backup import export_sqlite_backup
from services.postgres_backup import BackupError, dump_database

RESET_CONFIRMATION_PHRASE = "APAGAR TUDO"
# Tokens de sessão não fazem parte de um backup de dados.
_EXCLUDED_BACKUP_TABLES = {"sessoes_usuario"}


def export_portable_backup(engine: Engine) -> bytes:
    """Copia todas as tabelas para um SQLite; não depende de pg_dump."""
    tables = [table for table in Base.metadata.sorted_tables if table.name not in _EXCLUDED_BACKUP_TABLES]
    with tempfile.TemporaryDirectory(prefix="cafeteria-portable-") as directory:
        destination = Path(directory) / "backup.sqlite3"
        target = create_engine(f"sqlite:///{destination}")
        try:
            Base.metadata.create_all(target, tables=tables)
            with engine.connect() as source, target.begin() as sink:
                for table in tables:
                    rows = [dict(row) for row in source.execute(select(table)).mappings()]
                    for start in range(0, len(rows), 1000):
                        sink.execute(table.insert(), rows[start:start + 1000])
        finally:
            target.dispose()
        return destination.read_bytes()


def build_backup_download(engine: Engine, database_url: str, now: datetime) -> tuple[bytes, str, str]:
    """Gera o backup completo do banco ativo: (conteúdo, nome do arquivo, tipo MIME)."""
    stamp = f"{now:%Y%m%d-%H%M%S}"
    if engine.url.drivername.startswith("sqlite"):
        return export_sqlite_backup(engine), f"cafeteria-backup-{stamp}.sqlite3", "application/vnd.sqlite3"
    try:
        return dump_database(database_url), f"cafeteria-backup-{stamp}.dump", "application/octet-stream"
    except BackupError as error:
        if "não encontrada" not in str(error):
            raise
    return (export_portable_backup(engine), f"cafeteria-backup-portatil-{stamp}.sqlite3",
            "application/vnd.sqlite3")

# Filhos antes dos pais, para respeitar as chaves estrangeiras.
_RESET_ORDER = (
    ComandaOrder, OrderItem, Order, Comanda, Customer,
    CashMovement, CashSession, CashFlow, Payable, Receivable,
    StockMovement, Stock, RecipeItem, Ingredient, Product, Category,
    DemoRecord, Audit,
)


def count_resettable_records(session: Session) -> dict[str, int]:
    return {
        model.__tablename__: session.scalar(select(func.count()).select_from(model)) or 0
        for model in _RESET_ORDER
    }


def clear_all_data(session: Session, responsible: str) -> dict[str, int]:
    """Apaga dados operacionais, catálogo e auditoria; preserva usuários, perfis e permissões."""
    removed: dict[str, int] = {}
    try:
        for model in _RESET_ORDER:
            removed[model.__tablename__] = session.execute(delete(model)).rowcount or 0
        session.add(Audit(
            responsible=responsible,
            action="Limpeza total de dados",
            details=f"{sum(removed.values())} registros removidos",
        ))
        session.commit()
    except Exception:
        session.rollback()
        raise
    return removed
