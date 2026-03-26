"""Create POS sales import staging tables.

Revision ID: 202603260001
Revises: 202603210002
Create Date: 2026-03-26 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "202603260001"
down_revision = "202603210002"
branch_labels = None
depends_on = None


def _table_exists(inspector, table_name):
    return table_name in set(inspector.get_table_names())


def _index_exists(inspector, table_name, index_name, columns):
    expected = tuple(columns)
    for index in inspector.get_indexes(table_name):
        if index.get("name") == index_name:
            return True
        if tuple(index.get("column_names") or []) == expected:
            return True
    return False


def _create_index_if_missing(table_name, index_name, columns):
    inspector = sa.inspect(op.get_bind())
    if _table_exists(inspector, table_name) and not _index_exists(inspector, table_name, index_name, columns):
        op.create_index(index_name, table_name, columns, unique=False)


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not _table_exists(inspector, "pos_sales_import"):
        op.create_table(
            "pos_sales_import",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("source_provider", sa.String(length=100), nullable=False),
            sa.Column("message_id", sa.String(length=255), nullable=False),
            sa.Column("attachment_filename", sa.String(length=255), nullable=False),
            sa.Column("attachment_sha256", sa.String(length=64), nullable=False),
            sa.Column("received_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
            sa.Column("approved_by", sa.Integer(), nullable=True),
            sa.Column("approved_at", sa.DateTime(), nullable=True),
            sa.Column("reversed_by", sa.Integer(), nullable=True),
            sa.Column("reversed_at", sa.DateTime(), nullable=True),
            sa.Column("approval_batch_id", sa.String(length=64), nullable=True),
            sa.Column("reversal_batch_id", sa.String(length=64), nullable=True),
            sa.Column("failure_reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.CheckConstraint(
                "status IN ('pending', 'needs_mapping', 'approved', 'reversed', 'deleted', 'failed')",
                name="ck_pos_sales_import_status",
            ),
            sa.ForeignKeyConstraint(["approved_by"], ["user.id"]),
            sa.ForeignKeyConstraint(["reversed_by"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "source_provider",
                "message_id",
                "attachment_sha256",
                name="uq_pos_sales_import_idempotency",
            ),
        )
    _create_index_if_missing("pos_sales_import", "ix_pos_sales_import_status_received_at", ["status", "received_at"])
    _create_index_if_missing("pos_sales_import", "ix_pos_sales_import_received_at", ["received_at"])
    _create_index_if_missing("pos_sales_import", "ix_pos_sales_import_approved_by", ["approved_by", "approved_at"])
    _create_index_if_missing("pos_sales_import", "ix_pos_sales_import_reversed_by", ["reversed_by", "reversed_at"])
    _create_index_if_missing("pos_sales_import", "ix_pos_sales_import_approval_batch", ["approval_batch_id"])
    _create_index_if_missing("pos_sales_import", "ix_pos_sales_import_reversal_batch", ["reversal_batch_id"])

    inspector = sa.inspect(op.get_bind())
    if not _table_exists(inspector, "pos_sales_import_location"):
        op.create_table(
            "pos_sales_import_location",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("import_id", sa.Integer(), nullable=False),
            sa.Column("source_location_name", sa.String(length=255), nullable=False),
            sa.Column("normalized_location_name", sa.String(length=255), nullable=False),
            sa.Column("location_id", sa.Integer(), nullable=True),
            sa.Column("total_quantity", sa.Float(), server_default="0.0", nullable=False),
            sa.Column("net_inc", sa.Float(), server_default="0.0", nullable=False),
            sa.Column("discounts_abs", sa.Float(), server_default="0.0", nullable=False),
            sa.Column("computed_total", sa.Float(), server_default="0.0", nullable=False),
            sa.Column("parse_index", sa.Integer(), nullable=False),
            sa.Column("approval_batch_id", sa.String(length=64), nullable=True),
            sa.Column("reversal_batch_id", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.ForeignKeyConstraint(["import_id"], ["pos_sales_import.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["location_id"], ["location.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("import_id", "parse_index", name="uq_pos_sales_import_location_order"),
        )
    _create_index_if_missing("pos_sales_import_location", "ix_pos_sales_import_location_import", ["import_id"])
    _create_index_if_missing("pos_sales_import_location", "ix_pos_sales_import_location_normalized", ["normalized_location_name"])
    _create_index_if_missing("pos_sales_import_location", "ix_pos_sales_import_location_location_id", ["location_id"])
    _create_index_if_missing("pos_sales_import_location", "ix_pos_sales_import_location_approval_batch", ["approval_batch_id"])
    _create_index_if_missing("pos_sales_import_location", "ix_pos_sales_import_location_reversal_batch", ["reversal_batch_id"])

    inspector = sa.inspect(op.get_bind())
    if not _table_exists(inspector, "pos_sales_import_row"):
        op.create_table(
            "pos_sales_import_row",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("import_id", sa.Integer(), nullable=False),
            sa.Column("location_import_id", sa.Integer(), nullable=False),
            sa.Column("source_product_code", sa.String(length=128), nullable=True),
            sa.Column("source_product_name", sa.String(length=255), nullable=False),
            sa.Column("normalized_product_name", sa.String(length=255), nullable=False),
            sa.Column("product_id", sa.Integer(), nullable=True),
            sa.Column("quantity", sa.Float(), server_default="0.0", nullable=False),
            sa.Column("net_inc", sa.Float(), server_default="0.0", nullable=False),
            sa.Column("discount_raw", sa.String(length=64), nullable=True),
            sa.Column("discount_abs", sa.Float(), server_default="0.0", nullable=False),
            sa.Column("computed_line_total", sa.Float(), server_default="0.0", nullable=False),
            sa.Column("computed_unit_price", sa.Float(), server_default="0.0", nullable=False),
            sa.Column("parse_index", sa.Integer(), nullable=False),
            sa.Column("is_zero_quantity", sa.Boolean(), server_default="0", nullable=False),
            sa.Column("approval_batch_id", sa.String(length=64), nullable=True),
            sa.Column("reversal_batch_id", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.ForeignKeyConstraint(["import_id"], ["pos_sales_import.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["location_import_id"], ["pos_sales_import_location.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["product_id"], ["product.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("location_import_id", "parse_index", name="uq_pos_sales_import_row_order"),
        )
    _create_index_if_missing("pos_sales_import_row", "ix_pos_sales_import_row_import", ["import_id"])
    _create_index_if_missing("pos_sales_import_row", "ix_pos_sales_import_row_location_import", ["location_import_id"])
    _create_index_if_missing("pos_sales_import_row", "ix_pos_sales_import_row_normalized_product", ["normalized_product_name"])
    _create_index_if_missing("pos_sales_import_row", "ix_pos_sales_import_row_product_id", ["product_id"])
    _create_index_if_missing("pos_sales_import_row", "ix_pos_sales_import_row_zero_qty", ["is_zero_quantity"])
    _create_index_if_missing("pos_sales_import_row", "ix_pos_sales_import_row_approval_batch", ["approval_batch_id"])
    _create_index_if_missing("pos_sales_import_row", "ix_pos_sales_import_row_reversal_batch", ["reversal_batch_id"])


def downgrade():
    op.drop_index("ix_pos_sales_import_row_reversal_batch", table_name="pos_sales_import_row")
    op.drop_index("ix_pos_sales_import_row_approval_batch", table_name="pos_sales_import_row")
    op.drop_index("ix_pos_sales_import_row_zero_qty", table_name="pos_sales_import_row")
    op.drop_index("ix_pos_sales_import_row_product_id", table_name="pos_sales_import_row")
    op.drop_index("ix_pos_sales_import_row_normalized_product", table_name="pos_sales_import_row")
    op.drop_index("ix_pos_sales_import_row_location_import", table_name="pos_sales_import_row")
    op.drop_index("ix_pos_sales_import_row_import", table_name="pos_sales_import_row")
    op.drop_table("pos_sales_import_row")

    op.drop_index("ix_pos_sales_import_location_reversal_batch", table_name="pos_sales_import_location")
    op.drop_index("ix_pos_sales_import_location_approval_batch", table_name="pos_sales_import_location")
    op.drop_index("ix_pos_sales_import_location_location_id", table_name="pos_sales_import_location")
    op.drop_index("ix_pos_sales_import_location_normalized", table_name="pos_sales_import_location")
    op.drop_index("ix_pos_sales_import_location_import", table_name="pos_sales_import_location")
    op.drop_table("pos_sales_import_location")

    op.drop_index("ix_pos_sales_import_reversal_batch", table_name="pos_sales_import")
    op.drop_index("ix_pos_sales_import_approval_batch", table_name="pos_sales_import")
    op.drop_index("ix_pos_sales_import_reversed_by", table_name="pos_sales_import")
    op.drop_index("ix_pos_sales_import_approved_by", table_name="pos_sales_import")
    op.drop_index("ix_pos_sales_import_received_at", table_name="pos_sales_import")
    op.drop_index("ix_pos_sales_import_status_received_at", table_name="pos_sales_import")
    op.drop_table("pos_sales_import")
