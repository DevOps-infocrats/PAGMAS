"""Non-Doable: the COH forwards a case to the Corporate Team – MGG person(s) it chooses or types (nd_mgg_picks).

A new table only – no existing row or column changes. Cases forwarded before keep going to every authorised MGG
account, as before.

Revision ID: 0003_nd_mgg_picks
Revises: 0002_typed_recipients_gp_source
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_nd_mgg_picks"
down_revision: str | None = "0002_typed_recipients_gp_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if insp.has_table("nd_mgg_picks"):
        return
    op.create_table(
        "nd_mgg_picks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["nd_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["nd_events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "email", name="uq_nd_mgg_pick_step"),
    )
    op.create_index("ix_nd_mgg_picks_case_id", "nd_mgg_picks", ["case_id"])
    op.create_index("ix_nd_mgg_picks_event_id", "nd_mgg_picks", ["event_id"])
    op.create_index("ix_nd_mgg_picks_email", "nd_mgg_picks", ["email"])


def downgrade() -> None:
    op.drop_table("nd_mgg_picks")
