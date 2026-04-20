"""store remnawave users on devices

Revision ID: 202604200001
Revises: 202604190002
Create Date: 2026-04-20 20:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "202604200001"
down_revision = "202604190002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("remnawave_uuid", sa.String(length=128), nullable=True))
    op.add_column("devices", sa.Column("remnawave_username", sa.String(length=320), nullable=True))
    op.add_column("devices", sa.Column("remnawave_subscription_url", sa.Text(), nullable=True))
    op.add_column("devices", sa.Column("remnawave_raw", sa.JSON(), nullable=True))
    op.add_column("devices", sa.Column("traffic_used", sa.BigInteger(), nullable=False, server_default="0"))
    op.add_column("devices", sa.Column("traffic_limit_bytes", sa.BigInteger(), nullable=False, server_default="0"))
    op.create_index(op.f("ix_devices_remnawave_uuid"), "devices", ["remnawave_uuid"], unique=False)
    op.create_index(op.f("ix_devices_remnawave_username"), "devices", ["remnawave_username"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_devices_remnawave_username"), table_name="devices")
    op.drop_index(op.f("ix_devices_remnawave_uuid"), table_name="devices")
    op.drop_column("devices", "traffic_limit_bytes")
    op.drop_column("devices", "traffic_used")
    op.drop_column("devices", "remnawave_raw")
    op.drop_column("devices", "remnawave_subscription_url")
    op.drop_column("devices", "remnawave_username")
    op.drop_column("devices", "remnawave_uuid")
