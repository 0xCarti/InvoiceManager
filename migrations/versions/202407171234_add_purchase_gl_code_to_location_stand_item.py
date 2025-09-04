"""add purchase gl code to location stand item"""

from alembic import op
import sqlalchemy as sa


def _has_column(table_name: str, column_name: str, bind) -> bool:
    """Return True if the given table already has the specified column."""
    inspector = sa.inspect(bind)
    columns = [c["name"] for c in inspector.get_columns(table_name)]
    return column_name in columns


def _has_fk(table_name: str, fk_name: str, bind) -> bool:
    """Return True if the given table already has the specified foreign key."""
    inspector = sa.inspect(bind)
    fks = [fk["name"] for fk in inspector.get_foreign_keys(table_name)]
    return fk_name in fks


# revision identifiers, used by Alembic.
revision = "add_purchase_gl_code_to_location_stand_item"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    if not _has_column("location_stand_item", "purchase_gl_code_id", bind):
        op.add_column(
            "location_stand_item",
            sa.Column("purchase_gl_code_id", sa.Integer(), nullable=True),
        )

    if not _has_fk(
        "location_stand_item", "fk_location_stand_item_purchase_gl_code", bind
    ):
        op.create_foreign_key(
            "fk_location_stand_item_purchase_gl_code",
            "location_stand_item",
            "gl_code",
            ["purchase_gl_code_id"],
            ["id"],
        )


def downgrade():
    bind = op.get_bind()

    if _has_fk("location_stand_item", "fk_location_stand_item_purchase_gl_code", bind):
        op.drop_constraint(
            "fk_location_stand_item_purchase_gl_code",
            "location_stand_item",
            type_="foreignkey",
        )

    if _has_column("location_stand_item", "purchase_gl_code_id", bind):
        op.drop_column("location_stand_item", "purchase_gl_code_id")

