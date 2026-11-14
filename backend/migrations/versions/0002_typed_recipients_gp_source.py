"""Generate Ticket for circles without an Area Manager / SME / COH in the Escalation Matrix.

ticket_recipients.typed   True = the admin typed this person's name / e-mail (nobody, or not this person, in the matrix)
ticket_tasks.gp_source    None = the AM's own GPs; "NO_AM" = the circle's GPs without an AM (acting AM);
                          "AM+NO_AM" = the AM's own GPs plus those

Both columns are nullable and new – existing rows keep NULL (= from the database / the AM's own GPs), no row changes.

Revision ID: 0002_typed_recipients_gp_source
Revises: 0001_baseline
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_typed_recipients_gp_source"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has(table: str, column: str) -> bool:
    return any(c["name"] == column for c in sa.inspect(op.get_bind()).get_columns(table))


def upgrade() -> None:
    if not _has("ticket_recipients", "typed"):
        op.add_column("ticket_recipients", sa.Column("typed", sa.Boolean(), nullable=True))
    if not _has("ticket_tasks", "gp_source"):
        op.add_column("ticket_tasks", sa.Column("gp_source", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("ticket_tasks", "gp_source")
    op.drop_column("ticket_recipients", "typed")
