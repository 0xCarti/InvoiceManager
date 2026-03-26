"""Add approval metadata to POS sales import rows.

Defensive guards handle pre-existing drifted schemas where the column may
already exist (or already be missing during downgrade).

Revision ID: 202603260003
Revises: 202603260002
Create Date: 2026-03-26 01:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "202603260003"
down_revision = "202603260002"
branch_labels = None
depends_on = None


def _column_names(table_name):
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade():
    if "approval_metadata" not in _column_names("pos_sales_import_row"):
        op.add_column(
            "pos_sales_import_row",
            sa.Column("approval_metadata", sa.Text(), nullable=True),
        )


def downgrade():
    if "approval_metadata" in _column_names("pos_sales_import_row"):
        op.drop_column("pos_sales_import_row", "approval_metadata")
