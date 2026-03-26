"""Repair POS sales import schema drift for pre-Alembic create_all environments.

Revision ID: 202603260006
Revises: 202603260005
Create Date: 2026-03-26 00:06:00.000000

This one-time remediation migration reconciles environments where
``pos_sales_import*`` tables were created by SQLAlchemy ``create_all()``
before Alembic revisions 202603260001..202603260005 were applied.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "202603260006"
down_revision = "202603260005"
branch_labels = None
depends_on = None


def _column_names(inspector, table_name):
    return {column["name"] for column in inspector.get_columns(table_name)}


def _index_exists(inspector, table_name, index_name, columns):
    expected = tuple(columns)
    for index in inspector.get_indexes(table_name):
        if index.get("name") == index_name:
            return True
        if tuple(index.get("column_names") or []) == expected:
            return True
    return False


def _unique_constraint_exists(inspector, table_name, constraint_name, columns):
    expected = tuple(columns)
    for constraint in inspector.get_unique_constraints(table_name):
        if constraint.get("name") == constraint_name:
            return True
        if tuple(constraint.get("column_names") or []) == expected:
            return True
    return False


def _check_constraint_exists(inspector, table_name, constraint_name, sqltext_contains):
    needle = " ".join(sqltext_contains.split()).lower()
    for constraint in inspector.get_check_constraints(table_name):
        if constraint.get("name") == constraint_name:
            return True
        sqltext = " ".join((constraint.get("sqltext") or "").split()).lower()
        if needle and needle in sqltext:
            return True
    return False


def _foreign_key_exists(inspector, table_name, constraint_name, constrained_columns, referred_table, referred_columns):
    expected_local = tuple(constrained_columns)
    expected_remote = tuple(referred_columns)
    for fk in inspector.get_foreign_keys(table_name):
        if fk.get("name") == constraint_name:
            return True
        if (
            tuple(fk.get("constrained_columns") or []) == expected_local
            and fk.get("referred_table") == referred_table
            and tuple(fk.get("referred_columns") or []) == expected_remote
        ):
            return True
    return False


def _ensure_pos_sales_import(inspector):
    tables = set(inspector.get_table_names())
    if "pos_sales_import" not in tables:
        op.create_table(
            "pos_sales_import",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("source_provider", sa.String(length=100), nullable=False),
            sa.Column("message_id", sa.String(length=255), nullable=False),
            sa.Column("attachment_filename", sa.String(length=255), nullable=False),
            sa.Column("attachment_sha256", sa.String(length=64), nullable=False),
            sa.Column("attachment_storage_path", sa.String(length=1024), nullable=True),
            sa.Column("received_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
            sa.Column("approved_by", sa.Integer(), nullable=True),
            sa.Column("approved_at", sa.DateTime(), nullable=True),
            sa.Column("reversed_by", sa.Integer(), nullable=True),
            sa.Column("reversed_at", sa.DateTime(), nullable=True),
            sa.Column("approval_batch_id", sa.String(length=64), nullable=True),
            sa.Column("reversal_batch_id", sa.String(length=64), nullable=True),
            sa.Column("failure_reason", sa.Text(), nullable=True),
            sa.Column("reversal_reason", sa.Text(), nullable=True),
            sa.Column("deleted_by", sa.Integer(), nullable=True),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.Column("deletion_reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.CheckConstraint(
                "status IN ('pending', 'needs_mapping', 'approved', 'reversed', 'deleted', 'failed')",
                name="ck_pos_sales_import_status",
            ),
            sa.ForeignKeyConstraint(["approved_by"], ["user.id"]),
            sa.ForeignKeyConstraint(["reversed_by"], ["user.id"]),
            sa.ForeignKeyConstraint(["deleted_by"], ["user.id"], name="fk_pos_sales_import_deleted_by_user"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "source_provider",
                "message_id",
                "attachment_sha256",
                name="uq_pos_sales_import_idempotency",
            ),
        )
        inspector = sa.inspect(op.get_bind())
    else:
        columns = _column_names(inspector, "pos_sales_import")
        if "attachment_storage_path" not in columns:
            op.add_column("pos_sales_import", sa.Column("attachment_storage_path", sa.String(length=1024), nullable=True))
        if "reversal_reason" not in columns:
            op.add_column("pos_sales_import", sa.Column("reversal_reason", sa.Text(), nullable=True))
        if "deleted_by" not in columns:
            op.add_column("pos_sales_import", sa.Column("deleted_by", sa.Integer(), nullable=True))
        if "deleted_at" not in columns:
            op.add_column("pos_sales_import", sa.Column("deleted_at", sa.DateTime(), nullable=True))
        if "deletion_reason" not in columns:
            op.add_column("pos_sales_import", sa.Column("deletion_reason", sa.Text(), nullable=True))

        inspector = sa.inspect(op.get_bind())
        if not _check_constraint_exists(
            inspector,
            "pos_sales_import",
            "ck_pos_sales_import_status",
            "status IN ('pending', 'needs_mapping', 'approved', 'reversed', 'deleted', 'failed')",
        ):
            op.create_check_constraint(
                "ck_pos_sales_import_status",
                "pos_sales_import",
                "status IN ('pending', 'needs_mapping', 'approved', 'reversed', 'deleted', 'failed')",
            )

        if not _unique_constraint_exists(
            inspector,
            "pos_sales_import",
            "uq_pos_sales_import_idempotency",
            ["source_provider", "message_id", "attachment_sha256"],
        ):
            op.create_unique_constraint(
                "uq_pos_sales_import_idempotency",
                "pos_sales_import",
                ["source_provider", "message_id", "attachment_sha256"],
            )

        if not _foreign_key_exists(inspector, "pos_sales_import", None, ["approved_by"], "user", ["id"]):
            op.create_foreign_key(None, "pos_sales_import", "user", ["approved_by"], ["id"])
        if not _foreign_key_exists(inspector, "pos_sales_import", None, ["reversed_by"], "user", ["id"]):
            op.create_foreign_key(None, "pos_sales_import", "user", ["reversed_by"], ["id"])
        if not _foreign_key_exists(
            inspector,
            "pos_sales_import",
            "fk_pos_sales_import_deleted_by_user",
            ["deleted_by"],
            "user",
            ["id"],
        ):
            op.create_foreign_key(
                "fk_pos_sales_import_deleted_by_user",
                "pos_sales_import",
                "user",
                ["deleted_by"],
                ["id"],
            )

    inspector = sa.inspect(op.get_bind())
    if not _index_exists(inspector, "pos_sales_import", "ix_pos_sales_import_status_received_at", ["status", "received_at"]):
        op.create_index("ix_pos_sales_import_status_received_at", "pos_sales_import", ["status", "received_at"], unique=False)
    if not _index_exists(inspector, "pos_sales_import", "ix_pos_sales_import_received_at", ["received_at"]):
        op.create_index("ix_pos_sales_import_received_at", "pos_sales_import", ["received_at"], unique=False)
    if not _index_exists(inspector, "pos_sales_import", "ix_pos_sales_import_approved_by", ["approved_by", "approved_at"]):
        op.create_index("ix_pos_sales_import_approved_by", "pos_sales_import", ["approved_by", "approved_at"], unique=False)
    if not _index_exists(inspector, "pos_sales_import", "ix_pos_sales_import_reversed_by", ["reversed_by", "reversed_at"]):
        op.create_index("ix_pos_sales_import_reversed_by", "pos_sales_import", ["reversed_by", "reversed_at"], unique=False)
    if not _index_exists(inspector, "pos_sales_import", "ix_pos_sales_import_approval_batch", ["approval_batch_id"]):
        op.create_index("ix_pos_sales_import_approval_batch", "pos_sales_import", ["approval_batch_id"], unique=False)
    if not _index_exists(inspector, "pos_sales_import", "ix_pos_sales_import_reversal_batch", ["reversal_batch_id"]):
        op.create_index("ix_pos_sales_import_reversal_batch", "pos_sales_import", ["reversal_batch_id"], unique=False)
    if not _index_exists(inspector, "pos_sales_import", "ix_pos_sales_import_deleted_by", ["deleted_by", "deleted_at"]):
        op.create_index("ix_pos_sales_import_deleted_by", "pos_sales_import", ["deleted_by", "deleted_at"], unique=False)


def _ensure_pos_sales_import_location(inspector):
    tables = set(inspector.get_table_names())
    if "pos_sales_import_location" not in tables:
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
    else:
        if not _foreign_key_exists(inspector, "pos_sales_import_location", None, ["import_id"], "pos_sales_import", ["id"]):
            op.create_foreign_key(None, "pos_sales_import_location", "pos_sales_import", ["import_id"], ["id"], ondelete="CASCADE")
        if not _foreign_key_exists(inspector, "pos_sales_import_location", None, ["location_id"], "location", ["id"]):
            op.create_foreign_key(None, "pos_sales_import_location", "location", ["location_id"], ["id"])
        if not _unique_constraint_exists(
            inspector,
            "pos_sales_import_location",
            "uq_pos_sales_import_location_order",
            ["import_id", "parse_index"],
        ):
            op.create_unique_constraint(
                "uq_pos_sales_import_location_order",
                "pos_sales_import_location",
                ["import_id", "parse_index"],
            )

    inspector = sa.inspect(op.get_bind())
    if not _index_exists(inspector, "pos_sales_import_location", "ix_pos_sales_import_location_import", ["import_id"]):
        op.create_index("ix_pos_sales_import_location_import", "pos_sales_import_location", ["import_id"], unique=False)
    if not _index_exists(inspector, "pos_sales_import_location", "ix_pos_sales_import_location_normalized", ["normalized_location_name"]):
        op.create_index("ix_pos_sales_import_location_normalized", "pos_sales_import_location", ["normalized_location_name"], unique=False)
    if not _index_exists(inspector, "pos_sales_import_location", "ix_pos_sales_import_location_location_id", ["location_id"]):
        op.create_index("ix_pos_sales_import_location_location_id", "pos_sales_import_location", ["location_id"], unique=False)
    if not _index_exists(inspector, "pos_sales_import_location", "ix_pos_sales_import_location_approval_batch", ["approval_batch_id"]):
        op.create_index("ix_pos_sales_import_location_approval_batch", "pos_sales_import_location", ["approval_batch_id"], unique=False)
    if not _index_exists(inspector, "pos_sales_import_location", "ix_pos_sales_import_location_reversal_batch", ["reversal_batch_id"]):
        op.create_index("ix_pos_sales_import_location_reversal_batch", "pos_sales_import_location", ["reversal_batch_id"], unique=False)


def _ensure_pos_sales_import_row(inspector):
    tables = set(inspector.get_table_names())
    if "pos_sales_import_row" not in tables:
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
            sa.Column("approval_metadata", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.ForeignKeyConstraint(["import_id"], ["pos_sales_import.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["location_import_id"], ["pos_sales_import_location.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["product_id"], ["product.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("location_import_id", "parse_index", name="uq_pos_sales_import_row_order"),
        )
    else:
        columns = _column_names(inspector, "pos_sales_import_row")
        if "approval_metadata" not in columns:
            op.add_column("pos_sales_import_row", sa.Column("approval_metadata", sa.Text(), nullable=True))

        inspector = sa.inspect(op.get_bind())
        if not _foreign_key_exists(inspector, "pos_sales_import_row", None, ["import_id"], "pos_sales_import", ["id"]):
            op.create_foreign_key(None, "pos_sales_import_row", "pos_sales_import", ["import_id"], ["id"], ondelete="CASCADE")
        if not _foreign_key_exists(inspector, "pos_sales_import_row", None, ["location_import_id"], "pos_sales_import_location", ["id"]):
            op.create_foreign_key(None, "pos_sales_import_row", "pos_sales_import_location", ["location_import_id"], ["id"], ondelete="CASCADE")
        if not _foreign_key_exists(inspector, "pos_sales_import_row", None, ["product_id"], "product", ["id"]):
            op.create_foreign_key(None, "pos_sales_import_row", "product", ["product_id"], ["id"])
        if not _unique_constraint_exists(
            inspector,
            "pos_sales_import_row",
            "uq_pos_sales_import_row_order",
            ["location_import_id", "parse_index"],
        ):
            op.create_unique_constraint(
                "uq_pos_sales_import_row_order",
                "pos_sales_import_row",
                ["location_import_id", "parse_index"],
            )

    inspector = sa.inspect(op.get_bind())
    if not _index_exists(inspector, "pos_sales_import_row", "ix_pos_sales_import_row_import", ["import_id"]):
        op.create_index("ix_pos_sales_import_row_import", "pos_sales_import_row", ["import_id"], unique=False)
    if not _index_exists(inspector, "pos_sales_import_row", "ix_pos_sales_import_row_location_import", ["location_import_id"]):
        op.create_index("ix_pos_sales_import_row_location_import", "pos_sales_import_row", ["location_import_id"], unique=False)
    if not _index_exists(inspector, "pos_sales_import_row", "ix_pos_sales_import_row_normalized_product", ["normalized_product_name"]):
        op.create_index("ix_pos_sales_import_row_normalized_product", "pos_sales_import_row", ["normalized_product_name"], unique=False)
    if not _index_exists(inspector, "pos_sales_import_row", "ix_pos_sales_import_row_product_id", ["product_id"]):
        op.create_index("ix_pos_sales_import_row_product_id", "pos_sales_import_row", ["product_id"], unique=False)
    if not _index_exists(inspector, "pos_sales_import_row", "ix_pos_sales_import_row_zero_qty", ["is_zero_quantity"]):
        op.create_index("ix_pos_sales_import_row_zero_qty", "pos_sales_import_row", ["is_zero_quantity"], unique=False)
    if not _index_exists(inspector, "pos_sales_import_row", "ix_pos_sales_import_row_approval_batch", ["approval_batch_id"]):
        op.create_index("ix_pos_sales_import_row_approval_batch", "pos_sales_import_row", ["approval_batch_id"], unique=False)
    if not _index_exists(inspector, "pos_sales_import_row", "ix_pos_sales_import_row_reversal_batch", ["reversal_batch_id"]):
        op.create_index("ix_pos_sales_import_row_reversal_batch", "pos_sales_import_row", ["reversal_batch_id"], unique=False)


def upgrade():
    inspector = sa.inspect(op.get_bind())
    _ensure_pos_sales_import(inspector)

    inspector = sa.inspect(op.get_bind())
    _ensure_pos_sales_import_location(inspector)

    inspector = sa.inspect(op.get_bind())
    _ensure_pos_sales_import_row(inspector)


def downgrade():
    # Intentionally conservative: this migration repairs drift and avoids
    # destructive drops on shared/possibly populated tables.
    pass
