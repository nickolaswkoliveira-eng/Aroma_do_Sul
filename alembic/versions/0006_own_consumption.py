from alembic import op
import sqlalchemy as sa


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "consumo_proprio" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "consumo_proprio",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("produtos.id"), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("unit_cost", sa.Numeric(12, 2), nullable=False),
        sa.Column("total_cost", sa.Numeric(12, 2), nullable=False),
        sa.Column("consumed_by", sa.String(80), nullable=False),
        sa.Column("reason", sa.String(160), nullable=False),
        sa.Column("responsible", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_consumo_proprio_product_id", "consumo_proprio", ["product_id"])
    op.create_index("ix_consumo_proprio_created_at", "consumo_proprio", ["created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    if "consumo_proprio" in sa.inspect(bind).get_table_names():
        op.drop_table("consumo_proprio")
