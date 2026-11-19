"""Camera proof of the FRT's Daily Achievement: where and when the live photo was taken.

New nullable columns on ticket_progress_files only – no existing row changes (NULL = an uploaded file without location):
  latitude, longitude, geo_accuracy (metres), captured_at (device time of the capture), capture_source (CAMERA).

Revision ID: 0006_proof_photo_location
Revises: 0005_nd_frt_forms
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_proof_photo_location"
down_revision: str | None = "0005_nd_frt_forms"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = (
    ("latitude", sa.Float()),
    ("longitude", sa.Float()),
    ("geo_accuracy", sa.Float()),
    ("captured_at", sa.DateTime(timezone=True)),
    ("capture_source", sa.String(length=10)),
)


def upgrade() -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("ticket_progress_files")}
    for name, typ in COLUMNS:
        if name not in have:
            op.add_column("ticket_progress_files", sa.Column(name, typ, nullable=True))


def downgrade() -> None:
    for name, _typ in reversed(COLUMNS):
        op.drop_column("ticket_progress_files", name)
