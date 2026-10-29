from alembic import op
import sqlalchemy as sa


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

MONEY_COLUMNS = {
    "produtos": ("cost_price", "sale_price"),
    "pedidos": ("total",),
    "comandas": ("total",),
    "itens_pedido": ("unit_price",),
    "caixa": ("opening_balance", "closing_balance"),
    "movimentacoes_caixa": ("amount",),
    "contas_pagar": ("amount",),
    "contas_receber": ("amount",),
    "fluxo_caixa": ("amount",),
}


def upgrade() -> None:
    bind = op.get_bind()
    # SQLite não impõe tipos de coluna; o ajuste só é necessário em bancos com tipo estrito.
    if bind.dialect.name != "postgresql":
        return
    inspector = sa.inspect(bind)
    for table, columns in MONEY_COLUMNS.items():
        if table not in inspector.get_table_names():
            continue
        current = {column["name"]: column["type"] for column in inspector.get_columns(table)}
        for column in columns:
            if column in current and not isinstance(current[column], sa.Numeric):
                op.execute(
                    f'ALTER TABLE "{table}" ALTER COLUMN "{column}" '
                    f'TYPE NUMERIC(12, 2) USING ROUND("{column}"::numeric, 2)'
                )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    existing = sa.inspect(bind).get_table_names()
    for table, columns in MONEY_COLUMNS.items():
        if table not in existing:
            continue
        for column in columns:
            op.execute(
                f'ALTER TABLE "{table}" ALTER COLUMN "{column}" TYPE DOUBLE PRECISION'
            )
