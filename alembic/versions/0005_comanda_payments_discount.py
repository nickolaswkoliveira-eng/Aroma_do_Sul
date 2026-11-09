from alembic import op
import sqlalchemy as sa


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _has_column(inspector, table: str, column: str) -> bool:
    return any(item["name"] == column for item in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "comandas" in tables:
        if not _has_column(inspector, "comandas", "discount"):
            op.add_column("comandas", sa.Column("discount", sa.Numeric(12, 2), nullable=False, server_default="0"))
        if not _has_column(inspector, "comandas", "discount_reason"):
            op.add_column("comandas", sa.Column("discount_reason", sa.String(160), nullable=False, server_default=""))
        if not _has_column(inspector, "comandas", "discount_by"):
            op.add_column("comandas", sa.Column("discount_by", sa.String(80), nullable=False, server_default=""))
    if "comanda_pagamentos" not in tables:
        op.create_table(
            "comanda_pagamentos",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("comanda_id", sa.Integer(), sa.ForeignKey("comandas.id"), nullable=False),
            sa.Column("method", sa.String(30), nullable=False),
            sa.Column("amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("received_by", sa.String(80), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_comanda_pagamentos_comanda_id", "comanda_pagamentos", ["comanda_id"])
    if "configuracoes" not in tables:
        op.create_table(
            "configuracoes",
            sa.Column("key", sa.String(60), primary_key=True),
            sa.Column("value", sa.Text(), nullable=False),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "configuracoes" in tables:
        op.drop_table("configuracoes")
    if "comanda_pagamentos" in tables:
        op.drop_table("comanda_pagamentos")
    if "comandas" in tables:
        for column in ("discount_by", "discount_reason", "discount"):
            if _has_column(inspector, "comandas", column):
                op.drop_column("comandas", column)
