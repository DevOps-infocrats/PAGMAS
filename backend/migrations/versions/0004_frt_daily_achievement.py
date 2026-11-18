"""FRT team in the GP-wise task: the FRT reports the Daily Achievement, the FE verifies it and sends it to the AM.

New nullable columns only – no existing row changes:
  users.frt_code               the Escalation Matrix FRT code an FRT account works for (set in User Management)
  ticket_recipients.frt_code   FRT recipient of a ticket: their FRT code
  ticket_task_gps.frt_code     FRT code of the GP in the Escalation Matrix at ticket creation
  ticket_task_gps.frt_stage    FRT → FE step (PENDING_FE / RETURNED_FRT / FE_VERIFIED)
Tickets created before keep NULL there – their GPs stay with the FE exactly as before.

Revision ID: 0004_frt_daily_achievement
Revises: 0003_nd_mgg_picks
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_frt_daily_achievement"
down_revision: str | None = "0003_nd_mgg_picks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = (
    ("users", "frt_code", 60),
    ("ticket_recipients", "frt_code", 60),
    ("ticket_task_gps", "frt_code", 60),
    ("ticket_task_gps", "frt_stage", 20),
)


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    for table, col, size in COLUMNS:
        if col not in {c["name"] for c in insp.get_columns(table)}:
            op.add_column(table, sa.Column(col, sa.String(length=size), nullable=True))
    if "ix_users_frt_code" not in {i["name"] for i in insp.get_indexes("users")}:
        op.create_index("ix_users_frt_code", "users", ["frt_code"])


def downgrade() -> None:
    op.drop_index("ix_users_frt_code", table_name="users")
    for table, col, _size in reversed(COLUMNS):
        op.drop_column(table, col)
