"""Ticket hierarchy: FE tickets and FRT (GP-wise) tickets under an AM ticket (app.tickets.units).

Two new tables only – no existing row or column changes. The FE / FRT tickets of the tickets that already exist are
added at start-up by app.tickets.units.backfill (new rows only; their status follows where each GP already is).

Revision ID: 0008_ticket_units
Revises: 0007_roles
Create Date: 2026-11-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_ticket_units"
down_revision: str | None = "0007_roles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("ticket_units"):
        op.create_table(
            "ticket_units",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("ticket_id", sa.Integer(), nullable=False),
            sa.Column("level", sa.String(length=3), nullable=False),
            sa.Column("parent_id", sa.Integer(), nullable=True),
            sa.Column("seq", sa.Integer(), nullable=False),
            sa.Column("code", sa.String(length=40), nullable=False),
            sa.Column("unit_key", sa.String(length=420), nullable=False),
            sa.Column("recipient_id", sa.Integer(), nullable=True),
            sa.Column("fe_name", sa.String(length=160), nullable=True),
            sa.Column("fe_email", sa.String(length=254), nullable=True),
            sa.Column("task_gp_id", sa.Integer(), nullable=True),
            sa.Column("frt_code", sa.String(length=60), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("closed_by_id", sa.Integer(), nullable=True),
            sa.Column("closed_by_name", sa.String(length=120), nullable=True),
            sa.Column("close_remark", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["parent_id"], ["ticket_units.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["recipient_id"], ["ticket_recipients.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["task_gp_id"], ["ticket_task_gps.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["closed_by_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("code"),
            sa.UniqueConstraint("task_gp_id"),
            sa.UniqueConstraint("ticket_id", "level", "unit_key", name="uq_ticket_unit_key"),
        )
        op.create_index("ix_ticket_units_ticket_id", "ticket_units", ["ticket_id"])
        op.create_index("ix_ticket_units_parent_id", "ticket_units", ["parent_id"])
        op.create_index("ix_ticket_units_recipient_id", "ticket_units", ["recipient_id"])
        op.create_index("ix_ticket_units_status", "ticket_units", ["status"])
    if not insp.has_table("ticket_unit_events"):
        op.create_table(
            "ticket_unit_events",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("unit_id", sa.Integer(), nullable=False),
            sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("actor_id", sa.Integer(), nullable=True),
            sa.Column("actor_name", sa.String(length=120), nullable=False),
            sa.Column("action", sa.String(length=20), nullable=False),
            sa.Column("from_status", sa.String(length=20), nullable=True),
            sa.Column("to_status", sa.String(length=20), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["unit_id"], ["ticket_units.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_ticket_unit_events_unit_id", "ticket_unit_events", ["unit_id"])


def downgrade() -> None:
    op.drop_table("ticket_unit_events")
    op.drop_table("ticket_units")
