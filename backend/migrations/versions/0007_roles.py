"""Roles & Access: access roles (which pages, laptop / phone) and the role of a viewer account.

New table `roles` and a new nullable column users.role_id – no existing row changes: every user keeps role_id NULL,
which is the built-in Viewer role (every page, as before). The built-in roles (Viewer, AM, FE, FRT) are created at
start-up by app.security.roles.ensure_system_roles (never overwriting an edited role).

Revision ID: 0007_roles
Revises: 0006_proof_photo_location
Create Date: 2026-11-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_roles"
down_revision: str | None = "0006_proof_photo_location"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "roles" not in insp.get_table_names():
        op.create_table(
            "roles",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("key", sa.String(length=20), nullable=True),
            sa.Column("name", sa.String(length=60), nullable=False),
            sa.Column("description", sa.String(length=300), nullable=True),
            sa.Column("pages", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("laptop_home", sa.String(length=40), nullable=True),
            sa.Column("phone_home", sa.String(length=40), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_by", sa.String(length=120), nullable=True),
            sa.UniqueConstraint("key", name="uq_roles_key"),
            sa.UniqueConstraint("name", name="uq_roles_name"),
        )
    if "role_id" not in {c["name"] for c in insp.get_columns("users")}:
        # batch mode: a plain ALTER on PostgreSQL, copy-and-move on SQLite (which cannot add a foreign key by ALTER)
        with op.batch_alter_table("users") as batch:
            batch.add_column(sa.Column("role_id", sa.Integer(), nullable=True))
            batch.create_foreign_key("fk_users_role_id", "roles", ["role_id"], ["id"], ondelete="SET NULL")
            batch.create_index("ix_users_role_id", ["role_id"])


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_index("ix_users_role_id")
        batch.drop_constraint("fk_users_role_id", type_="foreignkey")
        batch.drop_column("role_id")
    op.drop_table("roles")
