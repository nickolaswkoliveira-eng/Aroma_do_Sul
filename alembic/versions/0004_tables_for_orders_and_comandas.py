from alembic import op
import sqlalchemy as sa


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _has_column(inspector, table: str, column: str) -> bool:
    return any(item["name"] == column for item in inspector.get_columns(table))


def _has_index(inspector, table: str, index_name: str) -> bool:
    return any(item["name"] == index_name for item in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "comandas" in tables and not _has_column(inspector, "comandas", "table_number"):
        op.add_column("comandas", sa.Column("table_number", sa.Integer(), nullable=True))
    if "pedidos" in tables and not _has_column(inspector, "pedidos", "table_number"):
        op.add_column("pedidos", sa.Column("table_number", sa.Integer(), nullable=True))
    inspector = sa.inspect(bind)
    if "comandas" in tables and _has_column(inspector, "comandas", "table_number") and not _has_index(
        inspector, "comandas", "ix_comandas_table_number"
    ):
        op.create_index("ix_comandas_table_number", "comandas", ["table_number"])
    if "pedidos" in tables and _has_column(inspector, "pedidos", "table_number") and not _has_index(
        inspector, "pedidos", "ix_pedidos_table_number"
    ):
        op.create_index("ix_pedidos_table_number", "pedidos", ["table_number"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "pedidos" in tables and _has_index(inspector, "pedidos", "ix_pedidos_table_number"):
        op.drop_index("ix_pedidos_table_number", table_name="pedidos")
    if "comandas" in tables and _has_index(inspector, "comandas", "ix_comandas_table_number"):
        op.drop_index("ix_comandas_table_number", table_name="comandas")
    inspector = sa.inspect(bind)
    if "pedidos" in tables and _has_column(inspector, "pedidos", "table_number"):
        op.drop_column("pedidos", "table_number")
    if "comandas" in tables and _has_column(inspector, "comandas", "table_number"):
        op.drop_column("comandas", "table_number")
