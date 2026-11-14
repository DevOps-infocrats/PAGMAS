"""Baseline: the complete schema as of 13 Nov 2026 (41 tables).

Safe on every database – it only ADDS what is missing and never drops, renames or rewrites a row:
  * empty database           -> creates every table, index and unique rule
  * database made by the old start-up code (create_all + ADDED_COLUMNS, before Alembic) – e.g. the live server
                             -> creates only the missing tables / columns / indexes / unique rules, then applies the
                                two schema fixes the old start-up code made (gps.total_rkm optional, ticket_gp_forwards
                                unique per review step)
  * database already at this schema (the local database) -> only the missing ix_tickets_deleted_at index is created

Leftovers of an earlier design that are no longer in the models (table ticket_gp_stages, columns ticket_task_gps.stage /
stage_at, ticket_tasks.workflow) are left untouched – they still hold rows (see LEGACY_* in migrations/env.py).

Revision ID: 0001_baseline
Revises:
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# one MetaData for the whole baseline: a foreign key finds the table it points to (tables are listed parents first)
_META = sa.MetaData()


def _insp() -> sa.Inspector:
    return sa.inspect(op.get_bind())  # fresh every call: earlier steps of this migration change the schema


def _table(name: str, *elements: sa.SchemaItem) -> None:
    """CREATE TABLE when it is missing; on an existing table add only the missing (nullable) columns and unique rules."""
    insp = _insp()
    table = sa.Table(name, _META, *elements)
    if not insp.has_table(name):
        table.create(op.get_bind())
        return
    have = {c["name"] for c in insp.get_columns(name)}
    for col in table.columns:
        if col.name in have:
            continue
        if not col.nullable and col.server_default is None:
            raise RuntimeError(f"{name}.{col.name} is missing and NOT NULL without a default – add it by hand (with a value for the existing rows)")
        op.add_column(name, col._copy())
    if op.get_bind().dialect.name == "sqlite":
        return  # SQLite (tests / local fallback only) cannot add a constraint to an existing table
    uniques = {frozenset(u["column_names"]) for u in insp.get_unique_constraints(name)}
    uniques |= {frozenset(i["column_names"]) for i in insp.get_indexes(name) if i["unique"]}
    for uc in table.constraints:
        cols = frozenset(c.name for c in uc.columns)
        if isinstance(uc, sa.UniqueConstraint) and cols not in uniques:
            op.create_unique_constraint(uc.name or f"uq_{name}_{'_'.join(sorted(cols))}", name, sorted(cols))


def _index(name: str, table: str, columns: list[str], unique: bool = False) -> None:
    """CREATE INDEX unless an index of that name – or one on the same columns – already exists."""
    have = _insp().get_indexes(table)
    if any(i["name"] == name or (i["column_names"] == columns and bool(i["unique"]) == unique) for i in have):
        return
    op.create_index(name, table, columns, unique=unique)


def _legacy_fixes() -> None:
    """The schema fixes the old start-up code (app/db.py before Alembic) made on PostgreSQL."""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    insp = _insp()
    # blank TOTAL RKM = not reported, stored as NULL (never invented as 0)
    if insp.has_table("gps") and any(c["name"] == "total_rkm" and not c["nullable"] for c in insp.get_columns("gps")):
        op.alter_column("gps", "total_rkm", nullable=True)
    # ticket_gp_forwards first shipped unique on (GP, recipient, action) – that blocked forwarding a GP to the same SME /
    # COH again after a send-back; the unique rule is now (review step, recipient), created by _table above
    if insp.has_table("ticket_gp_forwards") and "uq_gp_forward" in {u["name"] for u in insp.get_unique_constraints("ticket_gp_forwards")}:
        op.drop_constraint("uq_gp_forward", "ticket_gp_forwards", type_="unique")


def upgrade() -> None:
    global _META
    _META = sa.MetaData()  # fresh on every run (a second upgrade in the same process must not meet the old tables)
    _legacy_fixes()  # first: the old (GP, recipient, action) rule would otherwise stay next to the new one
    _table('gp_daily_history',
    sa.Column('month', sa.String(length=7), nullable=False),
    sa.Column('gp_codes', sa.Text(), nullable=False),
    sa.Column('periods', sa.Text(), nullable=False),
    sa.Column('values', sa.LargeBinary(), nullable=False),
    sa.Column('data_as_of', sa.Date(), nullable=False),
    sa.Column('source_file', sa.String(length=255), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.PrimaryKeyConstraint('month')
    )
    _table('mail_templates',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('key', sa.String(length=40), nullable=True),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.String(length=300), nullable=True),
    sa.Column('subject', sa.String(length=300), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key')
    )
    _table('period_history',
    sa.Column('kind', sa.String(length=4), nullable=False),
    sa.Column('period', sa.String(length=10), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=True),
    sa.Column('end_date', sa.Date(), nullable=True),
    sa.Column('number', sa.Integer(), nullable=True),
    sa.Column('codes', sa.Text(), nullable=False),
    sa.Column('values', sa.LargeBinary(), nullable=False),
    sa.Column('data_as_of', sa.Date(), nullable=False),
    sa.Column('source_file', sa.String(length=255), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.PrimaryKeyConstraint('kind', 'period')
    )
    _table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('token_version', sa.Integer(), nullable=False),
    sa.Column('failed_logins', sa.Integer(), nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    _index('ix_users_email', 'users', ['email'], unique=True)
    _table('audit_logs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('action', sa.String(length=60), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.Column('detail', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    _index('ix_audit_logs_action', 'audit_logs', ['action'], unique=False)
    _index('ix_audit_logs_at', 'audit_logs', ['at'], unique=False)
    _table('datasets',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=False),
    sa.Column('stored_path', sa.String(length=1024), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('message', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('data_as_of', sa.Date(), nullable=True),
    sa.Column('rows_total', sa.Integer(), nullable=False),
    sa.Column('rows_accepted', sa.Integer(), nullable=False),
    sa.Column('rows_rejected', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('uploaded_by', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    _index('ix_datasets_is_active', 'datasets', ['is_active'], unique=False)
    _index('ix_datasets_sha256', 'datasets', ['sha256'], unique=False)
    _table('escalation_imports',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=False),
    sa.Column('stored_path', sa.String(length=1024), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('message', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('rows_total', sa.Integer(), nullable=False),
    sa.Column('rows_rejected', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('uploaded_by', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    _index('ix_escalation_imports_is_active', 'escalation_imports', ['is_active'], unique=False)
    _index('ix_escalation_imports_sha256', 'escalation_imports', ['sha256'], unique=False)
    _table('mail_configs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('template_id', sa.Integer(), nullable=True),
    sa.Column('audiences', sa.Text(), nullable=False),
    sa.Column('filter_circles', sa.Text(), nullable=False),
    sa.Column('filter_bas', sa.Text(), nullable=False),
    sa.Column('filter_blocks', sa.Text(), nullable=False),
    sa.Column('filter_people', sa.Text(), nullable=False),
    sa.Column('user_ids', sa.Text(), nullable=False),
    sa.Column('extra_recipients', sa.Text(), nullable=True),
    sa.Column('frequency', sa.String(length=10), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=False),
    sa.Column('send_time', sa.String(length=5), nullable=False),
    sa.Column('weekday', sa.Integer(), nullable=True),
    sa.Column('month_day', sa.Integer(), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_status', sa.String(length=20), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['template_id'], ['mail_templates.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    _index('ix_mail_configs_next_run_at', 'mail_configs', ['next_run_at'], unique=False)
    _table('nd_mgg_members',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('added_by_name', sa.String(length=120), nullable=False),
    sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id')
    )
    _table('tickets',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(length=20), nullable=True),
    sa.Column('subject', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('priority', sa.String(length=10), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('assignee_id', sa.Integer(), nullable=True),
    sa.Column('assignee_name', sa.String(length=120), nullable=False),
    sa.Column('assignee_email', sa.String(length=254), nullable=False),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_by_name', sa.String(length=120), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('closed_by_id', sa.Integer(), nullable=True),
    sa.Column('closed_by_name', sa.String(length=120), nullable=True),
    sa.Column('circle', sa.String(length=80), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by_name', sa.String(length=120), nullable=True),
    sa.ForeignKeyConstraint(['assignee_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['closed_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    _index('ix_tickets_assignee_id', 'tickets', ['assignee_id'], unique=False)
    _index('ix_tickets_created_at', 'tickets', ['created_at'], unique=False)
    _index('ix_tickets_deleted_at', 'tickets', ['deleted_at'], unique=False)
    _index('ix_tickets_status', 'tickets', ['status'], unique=False)
    _table('user_scopes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('level', sa.String(length=10), nullable=False),
    sa.Column('scope_id', sa.String(length=120), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'level', 'scope_id', name='uq_user_scope')
    )
    _index('ix_user_scopes_user_id', 'user_scopes', ['user_id'], unique=False)
    _table('circle_sheet_values',
    sa.Column('dataset_id', sa.Integer(), nullable=False),
    sa.Column('circle', sa.String(length=60), nullable=False),
    sa.Column('metric', sa.String(length=40), nullable=False),
    sa.Column('period', sa.String(length=10), nullable=False),
    sa.Column('value', sa.Float(), nullable=False),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('dataset_id', 'circle', 'metric', 'period')
    )
    _table('dataset_weeks',
    sa.Column('dataset_id', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(length=10), nullable=False),
    sa.Column('number', sa.Integer(), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=False),
    sa.Column('end_date', sa.Date(), nullable=False),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('dataset_id', 'code')
    )
    _table('escalation_contacts',
    sa.Column('import_id', sa.Integer(), nullable=False),
    sa.Column('gp_code', sa.String(length=40), nullable=False),
    sa.Column('circle', sa.String(length=60), nullable=False),
    sa.Column('ba', sa.String(length=80), nullable=True),
    sa.Column('district', sa.String(length=80), nullable=True),
    sa.Column('block_name', sa.String(length=120), nullable=True),
    sa.Column('block_code', sa.String(length=40), nullable=True),
    sa.Column('gp_name', sa.String(length=160), nullable=True),
    sa.Column('frt_code', sa.String(length=60), nullable=True),
    sa.Column('splicer_name', sa.String(length=120), nullable=True),
    sa.Column('splicer_phone', sa.String(length=80), nullable=True),
    sa.Column('fe_name', sa.String(length=120), nullable=True),
    sa.Column('fe_phone', sa.String(length=80), nullable=True),
    sa.Column('fe_email', sa.String(length=200), nullable=True),
    sa.Column('am_name', sa.String(length=120), nullable=True),
    sa.Column('am_phone', sa.String(length=80), nullable=True),
    sa.Column('am_email', sa.String(length=200), nullable=True),
    sa.Column('shq_name', sa.String(length=160), nullable=True),
    sa.Column('shq_phone', sa.String(length=80), nullable=True),
    sa.Column('shq_email', sa.String(length=200), nullable=True),
    sa.Column('coh_name', sa.String(length=120), nullable=True),
    sa.Column('coh_phone', sa.String(length=80), nullable=True),
    sa.Column('coh_email', sa.String(length=200), nullable=True),
    sa.Column('cbh_name', sa.String(length=120), nullable=True),
    sa.Column('cbh_phone', sa.String(length=80), nullable=True),
    sa.Column('cbh_email', sa.String(length=200), nullable=True),
    sa.ForeignKeyConstraint(['import_id'], ['escalation_imports.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('import_id', 'gp_code')
    )
    _table('escalation_edits',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('import_id', sa.Integer(), nullable=False),
    sa.Column('gp_code', sa.String(length=40), nullable=False),
    sa.Column('field', sa.String(length=40), nullable=False),
    sa.Column('old_value', sa.Text(), nullable=True),
    sa.Column('new_value', sa.Text(), nullable=True),
    sa.Column('edited_by', sa.Integer(), nullable=True),
    sa.Column('edited_by_name', sa.String(length=120), nullable=False),
    sa.Column('edited_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['edited_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['import_id'], ['escalation_imports.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    _index('ix_escalation_edits_edited_at', 'escalation_edits', ['edited_at'], unique=False)
    _index('ix_escalation_edits_gp_code', 'escalation_edits', ['gp_code'], unique=False)
    _index('ix_escalation_edits_import_id', 'escalation_edits', ['import_id'], unique=False)
    _table('gp_amc_plan',
    sa.Column('dataset_id', sa.Integer(), nullable=False),
    sa.Column('gp_code', sa.String(length=40), nullable=False),
    sa.Column('category', sa.String(length=80), nullable=True),
    sa.Column('planned_date', sa.Date(), nullable=True),
    sa.Column('ach_date', sa.Date(), nullable=True),
    sa.Column('current_status', sa.String(length=40), nullable=True),
    sa.Column('letter_status', sa.String(length=40), nullable=True),
    sa.Column('letter_date', sa.Date(), nullable=True),
    sa.Column('approval_status', sa.String(length=60), nullable=True),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('dataset_id', 'gp_code')
    )
    _table('gp_availability',
    sa.Column('dataset_id', sa.Integer(), nullable=False),
    sa.Column('gp_code', sa.String(length=40), nullable=False),
    sa.Column('kind', sa.String(length=2), nullable=False),
    sa.Column('period', sa.String(length=10), nullable=False),
    sa.Column('value', sa.Float(), nullable=True),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('dataset_id', 'gp_code', 'kind', 'period')
    )
    _table('gp_availability_packs',
    sa.Column('dataset_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=2), nullable=False),
    sa.Column('gp_codes', sa.Text(), nullable=False),
    sa.Column('periods', sa.Text(), nullable=False),
    sa.Column('values', sa.LargeBinary(), nullable=False),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('dataset_id', 'kind')
    )
    _table('gps',
    sa.Column('dataset_id', sa.Integer(), nullable=False),
    sa.Column('gp_code', sa.String(length=40), nullable=False),
    sa.Column('source_row', sa.Integer(), nullable=False),
    sa.Column('location_code', sa.String(length=80), nullable=True),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('circle', sa.String(length=60), nullable=False),
    sa.Column('ba', sa.String(length=80), nullable=True),
    sa.Column('district', sa.String(length=80), nullable=False),
    sa.Column('block_name', sa.String(length=120), nullable=False),
    sa.Column('block_code', sa.String(length=40), nullable=False),
    sa.Column('block_hoto_status', sa.String(length=40), nullable=True),
    sa.Column('np_status', sa.String(length=80), nullable=True),
    sa.Column('gp_type', sa.String(length=40), nullable=True),
    sa.Column('phase', sa.String(length=40), nullable=True),
    sa.Column('lot', sa.String(length=20), nullable=True),
    sa.Column('olt_location', sa.String(length=160), nullable=True),
    sa.Column('bbnl_km', sa.Float(), nullable=True),
    sa.Column('bsnl_km', sa.Float(), nullable=True),
    sa.Column('total_rkm', sa.Float(), nullable=True),
    sa.Column('hoto_date', sa.Date(), nullable=True),
    sa.Column('lms_amc_date', sa.Date(), nullable=True),
    sa.Column('letter_date', sa.Date(), nullable=True),
    sa.Column('amc_category', sa.String(length=20), nullable=True),
    sa.Column('amc_date', sa.Date(), nullable=True),
    sa.Column('am_name', sa.String(length=120), nullable=True),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('dataset_id', 'gp_code')
    )
    _index('ix_gp_dataset_block', 'gps', ['dataset_id', 'block_code'], unique=False)
    _index('ix_gps_block_code', 'gps', ['block_code'], unique=False)
    _index('ix_gps_circle', 'gps', ['circle'], unique=False)
    _table('import_reports',
    sa.Column('dataset_id', sa.Integer(), nullable=False),
    sa.Column('previous_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('report', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('dataset_id')
    )
    _table('mail_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('config_id', sa.Integer(), nullable=False),
    sa.Column('scheduled_for', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('sent', sa.Integer(), nullable=False),
    sa.Column('failed', sa.Integer(), nullable=False),
    sa.Column('skipped', sa.Integer(), nullable=False),
    sa.Column('message', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['config_id'], ['mail_configs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('config_id', 'scheduled_for', name='uq_mail_run_slot')
    )
    _index('ix_mail_runs_config_id', 'mail_runs', ['config_id'], unique=False)
    _table('master_blocks',
    sa.Column('dataset_id', sa.Integer(), nullable=False),
    sa.Column('block_code', sa.String(length=40), nullable=False),
    sa.Column('state', sa.String(length=60), nullable=False),
    sa.Column('block_name', sa.String(length=120), nullable=False),
    sa.Column('total_gp_count', sa.Integer(), nullable=True),
    sa.Column('existing_gps', sa.Integer(), nullable=True),
    sa.Column('new_gps', sa.Integer(), nullable=True),
    sa.Column('block_status', sa.String(length=60), nullable=True),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('dataset_id', 'block_code')
    )
    _table('reported_numbers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('dataset_id', sa.Integer(), nullable=False),
    sa.Column('state', sa.String(length=60), nullable=False),
    sa.Column('metric', sa.String(length=120), nullable=False),
    sa.Column('value_num', sa.Float(), nullable=True),
    sa.Column('value_text', sa.String(length=255), nullable=True),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    _index('ix_reported_numbers_dataset_id', 'reported_numbers', ['dataset_id'], unique=False)
    _table('ticket_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ticket_id', sa.Integer(), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('actor_id', sa.Integer(), nullable=True),
    sa.Column('actor_name', sa.String(length=120), nullable=False),
    sa.Column('action', sa.String(length=30), nullable=False),
    sa.Column('from_status', sa.String(length=20), nullable=True),
    sa.Column('to_status', sa.String(length=20), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    _index('ix_ticket_events_ticket_id', 'ticket_events', ['ticket_id'], unique=False)
    _table('ticket_notifications',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('ticket_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=30), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('body', sa.String(length=500), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    _index('ix_ticket_notifications_created_at', 'ticket_notifications', ['created_at'], unique=False)
    _index('ix_ticket_notifications_ticket_id', 'ticket_notifications', ['ticket_id'], unique=False)
    _index('ix_ticket_notifications_user_id', 'ticket_notifications', ['user_id'], unique=False)
    _table('ticket_progress',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ticket_id', sa.Integer(), nullable=False),
    sa.Column('submitted_by_id', sa.Integer(), nullable=True),
    sa.Column('submitted_by_name', sa.String(length=120), nullable=False),
    sa.Column('submitted_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['submitted_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    _index('ix_ticket_progress_submitted_at', 'ticket_progress', ['submitted_at'], unique=False)
    _index('ix_ticket_progress_ticket_id', 'ticket_progress', ['ticket_id'], unique=False)
    _table('ticket_recipients',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ticket_id', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=10), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('can_work', sa.Boolean(), nullable=False),
    sa.Column('attach_workbook', sa.Boolean(), nullable=False),
    sa.Column('email_status', sa.String(length=10), nullable=False),
    sa.Column('email_error', sa.String(length=300), nullable=True),
    sa.Column('emailed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('am_name', sa.String(length=160), nullable=True),
    sa.Column('fe_mail', sa.String(length=200), nullable=True),
    sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('ticket_id', 'email', name='uq_ticket_recipient_email')
    )
    _index('ix_ticket_recipients_ticket_id', 'ticket_recipients', ['ticket_id'], unique=False)
    _index('ix_ticket_recipients_user_id', 'ticket_recipients', ['user_id'], unique=False)
    _table('ticket_submissions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ticket_id', sa.Integer(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('submitted_by_id', sa.Integer(), nullable=True),
    sa.Column('submitted_by_name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('submitted_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('review', sa.String(length=20), nullable=False),
    sa.Column('reviewed_by_id', sa.Integer(), nullable=True),
    sa.Column('reviewed_by_name', sa.String(length=120), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('review_comment', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['reviewed_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['submitted_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('ticket_id', 'version', name='uq_ticket_submission_version')
    )
    _index('ix_ticket_submissions_ticket_id', 'ticket_submissions', ['ticket_id'], unique=False)
    _table('ticket_task_gps',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ticket_id', sa.Integer(), nullable=False),
    sa.Column('sort', sa.Integer(), nullable=False),
    sa.Column('gp_code', sa.String(length=40), nullable=False),
    sa.Column('gp_name', sa.String(length=160), nullable=False),
    sa.Column('circle', sa.String(length=80), nullable=False),
    sa.Column('business_area', sa.String(length=120), nullable=True),
    sa.Column('district', sa.String(length=120), nullable=True),
    sa.Column('block', sa.String(length=160), nullable=True),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('category', sa.String(length=60), nullable=True),
    sa.Column('planned_date', sa.Date(), nullable=True),
    sa.Column('ready_date', sa.Date(), nullable=True),
    sa.Column('amc_date', sa.Date(), nullable=True),
    sa.Column('target', sa.Integer(), nullable=False),
    sa.Column('base_achieved', sa.Integer(), nullable=False),
    sa.Column('reported', sa.Integer(), nullable=False),
    sa.Column('remarks', sa.Text(), nullable=True),
    sa.Column('fe_name', sa.String(length=120), nullable=True),
    sa.Column('fe_email', sa.String(length=200), nullable=True),
    sa.Column('gp_category', sa.String(length=1), nullable=True),
    sa.Column('review', sa.String(length=20), nullable=True),
    sa.Column('review_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('letter_date', sa.Date(), nullable=True),
    sa.Column('amc_on', sa.Date(), nullable=True),
    sa.Column('added_by', sa.String(length=120), nullable=True),
    sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('ticket_id', 'gp_code', name='uq_ticket_task_gp')
    )
    _index('ix_ticket_task_gps_ticket_id', 'ticket_task_gps', ['ticket_id'], unique=False)
    _table('ticket_tasks',
    sa.Column('ticket_id', sa.Integer(), nullable=False),
    sa.Column('am_name', sa.String(length=160), nullable=False),
    sa.Column('am_email', sa.String(length=254), nullable=True),
    sa.Column('week_code', sa.String(length=10), nullable=False),
    sa.Column('week_start', sa.Date(), nullable=False),
    sa.Column('week_end', sa.Date(), nullable=False),
    sa.Column('data_as_of', sa.Date(), nullable=False),
    sa.Column('source_file', sa.String(length=255), nullable=False),
    sa.Column('assignment_file', sa.String(length=80), nullable=True),
    sa.Column('circle', sa.String(length=80), nullable=True),
    sa.Column('cbh_name', sa.String(length=160), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('ticket_id')
    )
    _table('validation_issues',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('dataset_id', sa.Integer(), nullable=False),
    sa.Column('sheet', sa.String(length=60), nullable=False),
    sa.Column('row_number', sa.Integer(), nullable=True),
    sa.Column('column', sa.String(length=80), nullable=True),
    sa.Column('gp_code', sa.String(length=40), nullable=True),
    sa.Column('severity', sa.String(length=10), nullable=False),
    sa.Column('code', sa.String(length=40), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    _index('ix_validation_issues_code', 'validation_issues', ['code'], unique=False)
    _index('ix_validation_issues_dataset_id', 'validation_issues', ['dataset_id'], unique=False)
    _index('ix_validation_issues_gp_code', 'validation_issues', ['gp_code'], unique=False)
    _table('nd_cases',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ref', sa.String(length=20), nullable=True),
    sa.Column('ticket_id', sa.Integer(), nullable=False),
    sa.Column('task_gp_id', sa.Integer(), nullable=False),
    sa.Column('gp_code', sa.String(length=40), nullable=False),
    sa.Column('round', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('physical_status', sa.String(length=20), nullable=False),
    sa.Column('evidence_status', sa.String(length=20), nullable=False),
    sa.Column('approval_status', sa.String(length=20), nullable=False),
    sa.Column('revisit_status', sa.String(length=20), nullable=True),
    sa.Column('fe_name', sa.String(length=120), nullable=True),
    sa.Column('fe_email', sa.String(length=200), nullable=True),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_by_name', sa.String(length=120), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('decision', sa.String(length=10), nullable=True),
    sa.Column('decided_by_id', sa.Integer(), nullable=True),
    sa.Column('decided_by_name', sa.String(length=120), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decision_remark', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['decided_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['task_gp_id'], ['ticket_task_gps.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('ref')
    )
    _index('ix_nd_cases_created_at', 'nd_cases', ['created_at'], unique=False)
    _index('ix_nd_cases_gp_code', 'nd_cases', ['gp_code'], unique=False)
    _index('ix_nd_cases_status', 'nd_cases', ['status'], unique=False)
    _index('ix_nd_cases_task_gp_id', 'nd_cases', ['task_gp_id'], unique=False)
    _index('ix_nd_cases_ticket_id', 'nd_cases', ['ticket_id'], unique=False)
    _table('ticket_attachments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ticket_id', sa.Integer(), nullable=False),
    sa.Column('submission_id', sa.Integer(), nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=False),
    sa.Column('stored_name', sa.String(length=80), nullable=False),
    sa.Column('content_type', sa.String(length=100), nullable=False),
    sa.Column('size', sa.Integer(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['submission_id'], ['ticket_submissions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    _index('ix_ticket_attachments_submission_id', 'ticket_attachments', ['submission_id'], unique=False)
    _index('ix_ticket_attachments_ticket_id', 'ticket_attachments', ['ticket_id'], unique=False)
    _table('ticket_gp_reviews',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ticket_id', sa.Integer(), nullable=False),
    sa.Column('task_gp_id', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=10), nullable=False),
    sa.Column('action', sa.String(length=20), nullable=False),
    sa.Column('category', sa.String(length=1), nullable=True),
    sa.Column('on_date', sa.Date(), nullable=True),
    sa.Column('remark', sa.Text(), nullable=True),
    sa.Column('actor_id', sa.Integer(), nullable=True),
    sa.Column('actor_name', sa.String(length=120), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['task_gp_id'], ['ticket_task_gps.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    _index('ix_ticket_gp_reviews_at', 'ticket_gp_reviews', ['at'], unique=False)
    _index('ix_ticket_gp_reviews_task_gp_id', 'ticket_gp_reviews', ['task_gp_id'], unique=False)
    _index('ix_ticket_gp_reviews_ticket_id', 'ticket_gp_reviews', ['ticket_id'], unique=False)
    _table('ticket_progress_lines',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('progress_id', sa.Integer(), nullable=False),
    sa.Column('task_gp_id', sa.Integer(), nullable=False),
    sa.Column('achieved_today', sa.Integer(), nullable=False),
    sa.Column('cumulative', sa.Integer(), nullable=False),
    sa.Column('gap', sa.Integer(), nullable=False),
    sa.Column('remark', sa.Text(), nullable=True),
    sa.Column('category', sa.String(length=1), nullable=True),
    sa.ForeignKeyConstraint(['progress_id'], ['ticket_progress.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['task_gp_id'], ['ticket_task_gps.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    _index('ix_ticket_progress_lines_progress_id', 'ticket_progress_lines', ['progress_id'], unique=False)
    _index('ix_ticket_progress_lines_task_gp_id', 'ticket_progress_lines', ['task_gp_id'], unique=False)
    _table('nd_records',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=25), nullable=False),
    sa.Column('visit_date', sa.Date(), nullable=True),
    sa.Column('location', sa.String(length=300), nullable=True),
    sa.Column('visitor_name', sa.String(length=160), nullable=True),
    sa.Column('findings', sa.Text(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('remarks', sa.Text(), nullable=True),
    sa.Column('justification', sa.Text(), nullable=True),
    sa.Column('frt_team', sa.Text(), nullable=True),
    sa.Column('frt_visit', sa.Text(), nullable=True),
    sa.Column('outcome', sa.String(length=1), nullable=True),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_by_name', sa.String(length=120), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['nd_cases.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    _index('ix_nd_records_case_id', 'nd_records', ['case_id'], unique=False)
    _table('ticket_gp_forwards',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ticket_id', sa.Integer(), nullable=False),
    sa.Column('task_gp_id', sa.Integer(), nullable=False),
    sa.Column('review_id', sa.Integer(), nullable=False),
    sa.Column('recipient_id', sa.Integer(), nullable=False),
    sa.Column('action', sa.String(length=20), nullable=False),
    sa.Column('role', sa.String(length=10), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['recipient_id'], ['ticket_recipients.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['review_id'], ['ticket_gp_reviews.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['task_gp_id'], ['ticket_task_gps.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('review_id', 'recipient_id', name='uq_gp_forward_step')
    )
    _index('ix_ticket_gp_forwards_recipient_id', 'ticket_gp_forwards', ['recipient_id'], unique=False)
    _index('ix_ticket_gp_forwards_review_id', 'ticket_gp_forwards', ['review_id'], unique=False)
    _index('ix_ticket_gp_forwards_task_gp_id', 'ticket_gp_forwards', ['task_gp_id'], unique=False)
    _index('ix_ticket_gp_forwards_ticket_id', 'ticket_gp_forwards', ['ticket_id'], unique=False)
    _table('ticket_progress_files',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ticket_id', sa.Integer(), nullable=False),
    sa.Column('progress_line_id', sa.Integer(), nullable=False),
    sa.Column('task_gp_id', sa.Integer(), nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=False),
    sa.Column('stored_name', sa.String(length=80), nullable=False),
    sa.Column('content_type', sa.String(length=100), nullable=False),
    sa.Column('size', sa.Integer(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['progress_line_id'], ['ticket_progress_lines.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['task_gp_id'], ['ticket_task_gps.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    _index('ix_ticket_progress_files_progress_line_id', 'ticket_progress_files', ['progress_line_id'], unique=False)
    _index('ix_ticket_progress_files_task_gp_id', 'ticket_progress_files', ['task_gp_id'], unique=False)
    _index('ix_ticket_progress_files_ticket_id', 'ticket_progress_files', ['ticket_id'], unique=False)
    _table('nd_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.Integer(), nullable=False),
    sa.Column('ticket_id', sa.Integer(), nullable=False),
    sa.Column('task_gp_id', sa.Integer(), nullable=False),
    sa.Column('stage', sa.String(length=4), nullable=False),
    sa.Column('action', sa.String(length=30), nullable=False),
    sa.Column('role', sa.String(length=10), nullable=False),
    sa.Column('from_status', sa.String(length=20), nullable=True),
    sa.Column('to_status', sa.String(length=20), nullable=False),
    sa.Column('remark', sa.Text(), nullable=True),
    sa.Column('recommendation', sa.Text(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('decision', sa.String(length=10), nullable=True),
    sa.Column('record_id', sa.Integer(), nullable=True),
    sa.Column('actor_id', sa.Integer(), nullable=True),
    sa.Column('actor_name', sa.String(length=120), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['case_id'], ['nd_cases.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['record_id'], ['nd_records.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['task_gp_id'], ['ticket_task_gps.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    _index('ix_nd_events_action', 'nd_events', ['action'], unique=False)
    _index('ix_nd_events_at', 'nd_events', ['at'], unique=False)
    _index('ix_nd_events_case_id', 'nd_events', ['case_id'], unique=False)
    _index('ix_nd_events_task_gp_id', 'nd_events', ['task_gp_id'], unique=False)
    _index('ix_nd_events_ticket_id', 'nd_events', ['ticket_id'], unique=False)
    _table('nd_files',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.Integer(), nullable=False),
    sa.Column('ticket_id', sa.Integer(), nullable=False),
    sa.Column('record_id', sa.Integer(), nullable=True),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=False),
    sa.Column('stored_name', sa.String(length=80), nullable=False),
    sa.Column('content_type', sa.String(length=100), nullable=False),
    sa.Column('size', sa.Integer(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('uploaded_by_name', sa.String(length=120), nullable=False),
    sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['nd_cases.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['record_id'], ['nd_records.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    _index('ix_nd_files_case_id', 'nd_files', ['case_id'], unique=False)
    _index('ix_nd_files_record_id', 'nd_files', ['record_id'], unique=False)
    _index('ix_nd_files_ticket_id', 'nd_files', ['ticket_id'], unique=False)
    _table('nd_forwards',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.Integer(), nullable=False),
    sa.Column('event_id', sa.Integer(), nullable=False),
    sa.Column('recipient_id', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=10), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['nd_cases.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['event_id'], ['nd_events.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['recipient_id'], ['ticket_recipients.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('event_id', 'recipient_id', name='uq_nd_forward_step')
    )
    _index('ix_nd_forwards_case_id', 'nd_forwards', ['case_id'], unique=False)
    _index('ix_nd_forwards_event_id', 'nd_forwards', ['event_id'], unique=False)
    _index('ix_nd_forwards_recipient_id', 'nd_forwards', ['recipient_id'], unique=False)


def downgrade() -> None:
    # Undoing the baseline would drop every table with all its data – restore a pg_dump backup instead.
    raise RuntimeError("0001_baseline cannot be downgraded – restore a database backup instead")
