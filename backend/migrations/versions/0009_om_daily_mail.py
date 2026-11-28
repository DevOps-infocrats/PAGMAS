"""O&M Daily Dashboard e-mail: settings, circle-wise recipients, runs and the delivery log (app.mail.om_service).

Four new tables only – no existing row or column changes; the AMC Conversion e-mail schedules are untouched.

Revision ID: 0009_om_daily_mail
Revises: 0008_ticket_units
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_om_daily_mail"
down_revision: str | None = "0008_ticket_units"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("om_mail_settings"):
        op.create_table(
            "om_mail_settings",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("central_cc", sa.Text(), nullable=False),
            sa.Column("schedule", sa.Text(), nullable=False),
            sa.Column("window_start", sa.String(length=5), nullable=False),
            sa.Column("window_end", sa.String(length=5), nullable=False),
            sa.Column("subject_template", sa.String(length=200), nullable=False),
            sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_status", sa.String(length=20), nullable=True),
            sa.Column("updated_by", sa.String(length=120), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    if not insp.has_table("om_mail_circles"):
        op.create_table(
            "om_mail_circles",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("circle_id", sa.String(length=40), nullable=False),
            sa.Column("circle_name", sa.String(length=80), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("to_emails", sa.Text(), nullable=False),
            sa.Column("cc_emails", sa.Text(), nullable=False),
            sa.Column("subject", sa.String(length=200), nullable=True),
            sa.Column("include_ams", sa.Boolean(), nullable=False),
            sa.Column("area_managers", sa.Text(), nullable=False),
            sa.Column("remarks", sa.Text(), nullable=True),
            sa.Column("remarks_updated_by", sa.String(length=120), nullable=True),
            sa.Column("remarks_updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("circle_id"),
        )
    if not insp.has_table("om_mail_runs"):
        op.create_table(
            "om_mail_runs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("slot_key", sa.String(length=80), nullable=False),
            sa.Column("kind", sa.String(length=10), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("dataset_id", sa.Integer(), nullable=True),
            sa.Column("data_as_of", sa.Date(), nullable=True),
            sa.Column("triggered_by", sa.String(length=120), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("sent", sa.Integer(), nullable=False),
            sa.Column("failed", sa.Integer(), nullable=False),
            sa.Column("skipped", sa.Integer(), nullable=False),
            sa.Column("message", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("slot_key"),
        )
        op.create_index("ix_om_mail_runs_started_at", "om_mail_runs", ["started_at"])
    if not insp.has_table("om_mail_deliveries"):
        op.create_table(
            "om_mail_deliveries",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("run_id", sa.Integer(), nullable=False),
            sa.Column("circle_id", sa.String(length=40), nullable=False),
            sa.Column("to_emails", sa.Text(), nullable=False),
            sa.Column("cc_emails", sa.Text(), nullable=False),
            sa.Column("subject", sa.String(length=250), nullable=False),
            sa.Column("status", sa.String(length=10), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("error", sa.String(length=300), nullable=True),
            sa.Column("size_bytes", sa.Integer(), nullable=True),
            sa.Column("html_sha256", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["run_id"], ["om_mail_runs.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("run_id", "circle_id", name="uq_om_delivery_circle"),
        )
        op.create_index("ix_om_mail_deliveries_run_id", "om_mail_deliveries", ["run_id"])
        op.create_index("ix_om_mail_deliveries_status", "om_mail_deliveries", ["status"])
        op.create_index("ix_om_mail_deliveries_created_at", "om_mail_deliveries", ["created_at"])


def downgrade() -> None:
    op.drop_table("om_mail_deliveries")
    op.drop_table("om_mail_runs")
    op.drop_table("om_mail_circles")
    op.drop_table("om_mail_settings")
