from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from models.entities import (
    Audit, CashFlow, CashMovement, CashSession, Category, Comanda, ComandaOrder, Customer,
    DemoRecord, Ingredient, Order, OrderItem, Payable, Product, Receivable, RecipeItem,
    Stock, StockMovement,
)
from services.database_backup import export_sqlite_backup
from services.postgres_backup import dump_database

RESET_CONFIRMATION_PHRASE = "APAGAR TUDO"


def build_backup_download(engine: Engine, database_url: str, now: datetime) -> tuple[bytes, str, str]:
    """Gera o backup completo do banco ativo: (conteúdo, nome do arquivo, tipo MIME)."""
    stamp = f"{now:%Y%m%d-%H%M%S}"
    if engine.url.drivername.startswith("sqlite"):
        return export_sqlite_backup(engine), f"cafeteria-backup-{stamp}.sqlite3", "application/vnd.sqlite3"
    return dump_database(database_url), f"cafeteria-backup-{stamp}.dump", "application/octet-stream"

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
