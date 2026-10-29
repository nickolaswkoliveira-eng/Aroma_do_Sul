from alembic import op
import sqlalchemy as sa


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "backup_execucoes" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "backup_execucoes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("location", sa.String(300), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="Sucesso"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_backup_execucoes_created_at", "backup_execucoes", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_backup_execucoes_created_at", table_name="backup_execucoes")
    op.drop_table("backup_execucoes")
