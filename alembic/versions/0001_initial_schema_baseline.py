from alembic import op
import sqlalchemy as sa


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names()) - {"alembic_version"}
    if existing_tables:
        return

    # The project previously created tables via SQLAlchemy metadata.
    # This baseline is used to stamp an already initialized database.
    from models.entities import Base
    Base.metadata.create_all(bind)


def downgrade() -> None:
    pass
