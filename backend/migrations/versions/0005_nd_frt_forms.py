"""Non-Doable cases proposed by the FRT: who filled each E1 / E2 form (nd_records.role = FRT | FE).

One new nullable column – no existing row changes (NULL = a form of the FE, as every form so far). The new case
statuses FRT_PROPOSED / PENDING_FE fit the existing nd_cases.status column.

Revision ID: 0005_nd_frt_forms
Revises: 0004_frt_daily_achievement
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_nd_frt_forms"
down_revision: str | None = "0004_frt_daily_achievement"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "role" not in {c["name"] for c in insp.get_columns("nd_records")}:
        op.add_column("nd_records", sa.Column("role", sa.String(length=10), nullable=True))


def downgrade() -> None:
    op.drop_column("nd_records", "role")
