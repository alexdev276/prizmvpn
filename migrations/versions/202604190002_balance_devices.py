"""balance devices and account transactions

Revision ID: 202604190002
Revises: 202604190001
Create Date: 2026-04-19 01:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "202604190002"
down_revision = "202604190001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("balance_microrub", sa.BigInteger(), nullable=False, server_default="0"),
    )

    op.create_table(
        "devices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=16), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("config_uuid", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_billed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_devices_public_id"), "devices", ["public_id"], unique=True)
    op.create_index(op.f("ix_devices_user_id"), "devices", ["user_id"], unique=False)

    op.create_table(
        "account_transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=True),
        sa.Column("payment_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("amount_microrub", sa.BigInteger(), nullable=False),
        sa.Column("balance_after_microrub", sa.BigInteger(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_account_transactions_device_id"), "account_transactions", ["device_id"], unique=False)
    op.create_index(op.f("ix_account_transactions_payment_id"), "account_transactions", ["payment_id"], unique=False)
    op.create_index(op.f("ix_account_transactions_user_id"), "account_transactions", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_account_transactions_user_id"), table_name="account_transactions")
    op.drop_index(op.f("ix_account_transactions_payment_id"), table_name="account_transactions")
    op.drop_index(op.f("ix_account_transactions_device_id"), table_name="account_transactions")
    op.drop_table("account_transactions")
    op.drop_index(op.f("ix_devices_user_id"), table_name="devices")
    op.drop_index(op.f("ix_devices_public_id"), table_name="devices")
    op.drop_table("devices")
    op.drop_column("users", "balance_microrub")

