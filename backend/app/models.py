"""Database schema.

Every imported workbook becomes a *dataset*. GP rows, availability values and
validation issues are stored per dataset, so a failed import never touches the
dataset currently served to the dashboard (only one dataset is `is_active`).

Personal contact data present in the source (splicer / FE / AM / SPOC phone
numbers) is deliberately NOT imported. Only the Area Manager name is kept,
because area-manager performance is a dashboard requirement.
"""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20), default="viewer")  # admin | viewer
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Incremented on logout-all / password change / deactivation -> invalidates issued tokens.
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserScope(Base):
    """Circle / district / block a dashboard user may receive in the AMC Conversion e-mails (one row per area).
    `scope_id` is the dashboard's location id: circle "haryana", district "haryana~hisar", block "hr-123".
    Admins receive everything; a viewer without a valid row receives nothing (access is never widened)."""

    __tablename__ = "user_scopes"
    __table_args__ = (UniqueConstraint("user_id", "level", "scope_id", name="uq_user_scope"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    level: Mapped[str] = mapped_column(String(10))  # circle | district | block
    scope_id: Mapped[str] = mapped_column(String(120))


class MailTemplate(Base):
    """Customisable e-mail text with {{placeholders}} (see app.mail.template). Built-in templates have a `key` and can
    be edited and reset to their original text, but not deleted."""

    __tablename__ = "mail_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str | None] = mapped_column(String(40), unique=True, nullable=True)  # built-in id, None = admin-made
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MailConfig(Base):
    """A schedule of the AMC Conversion e-mail: who (audiences + filters), what (template) and when.
    Times are wall-clock times in MAIL_TIMEZONE; next_run_at is UTC. New schedules start disabled, and saving one never
    sends anything (next_run_at is always in the future). JSON lists are stored as text."""

    __tablename__ = "mail_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    template_id: Mapped[int | None] = mapped_column(ForeignKey("mail_templates.id", ondelete="SET NULL"), nullable=True)
    audiences: Mapped[str] = mapped_column(Text, default='["am"]')  # am | sme | coh | users (CBH is never mailed)
    filter_circles: Mapped[str] = mapped_column(Text, default="[]")  # circle ids; [] = all
    filter_bas: Mapped[str] = mapped_column(Text, default="[]")  # business area names; [] = all
    filter_blocks: Mapped[str] = mapped_column(Text, default="[]")  # block ids; [] = all
    filter_people: Mapped[str] = mapped_column(Text, default="[]")  # person ids "am:haryana:hemant"; [] = everyone
    user_ids: Mapped[str] = mapped_column(Text, default="[]")  # dashboard users ("users" audience); [] = all active
    # Extra recipients typed in by an admin (people not in the Escalation Matrix and without an account), each with
    # their own report: [{"email", "name", "areas": [{"level", "id"}]}] – no areas = every circle (within the filters).
    extra_recipients: Mapped[str | None] = mapped_column(Text, nullable=True, default="[]")
    frequency: Mapped[str] = mapped_column(String(10))  # daily | weekly | monthly
    start_date: Mapped[date] = mapped_column(Date)
    send_time: Mapped[str] = mapped_column(String(5))  # "HH:MM"
    weekday: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0 = Monday … 6 = Sunday
    month_day: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1–31 (short months: last day)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MailRun(Base):
    """One execution of a schedule for one planned time. The unique (config, scheduled_for) pair is the claim: the first
    process to insert it sends, every other attempt for the same slot is refused – no double e-mails."""

    __tablename__ = "mail_runs"
    __table_args__ = (UniqueConstraint("config_id", "scheduled_for", name="uq_mail_run_slot"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    config_id: Mapped[int] = mapped_column(ForeignKey("mail_configs.id", ondelete="CASCADE"), index=True)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20))  # RUNNING | SUCCESS | PARTIAL | FAILED | SKIPPED
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)  # counts and reasons only: no addresses or content


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_name: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(1024))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(20), default="PROCESSING")  # PROCESSING|SUCCESS|PARTIAL|FAILED
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    data_as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    rows_total: Mapped[int] = mapped_column(Integer, default=0)
    rows_accepted: Mapped[int] = mapped_column(Integer, default=0)
    rows_rejected: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class EscalationImport(Base):
    """One uploaded Escalation Matrix workbook (GP-wise field team and escalation contacts). Independent of the
    master-data datasets: either file can be uploaded alone or together; the newest successful one is active."""

    __tablename__ = "escalation_imports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_name: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(1024))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(20), default="PROCESSING")  # PROCESSING|SUCCESS|FAILED
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rows_total: Mapped[int] = mapped_column(Integer, default=0)
    rows_rejected: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class EscalationContact(Base):
    """Escalation chain of one GP: FRT → splicer → FE → AM → SHQ SPOC → COH → CBH (name + phone each).
    Phone numbers are personal data: the API shows them in full to admins only (masked for everyone else)."""

    __tablename__ = "escalation_contacts"

    import_id: Mapped[int] = mapped_column(ForeignKey("escalation_imports.id", ondelete="CASCADE"), primary_key=True)
    gp_code: Mapped[str] = mapped_column(String(40), primary_key=True)
    circle: Mapped[str] = mapped_column(String(60))
    ba: Mapped[str | None] = mapped_column(String(80), nullable=True)  # business area
    district: Mapped[str | None] = mapped_column(String(80), nullable=True)
    block_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    block_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    gp_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    frt_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    splicer_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    splicer_phone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    fe_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    fe_phone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    fe_email: Mapped[str | None] = mapped_column(String(200), nullable=True)  # Field Engineer
    am_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    am_phone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    am_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    shq_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    shq_phone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    shq_email: Mapped[str | None] = mapped_column(String(200), nullable=True)  # SME / SHQ SPOC
    coh_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    coh_phone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    coh_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cbh_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cbh_phone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    cbh_email: Mapped[str | None] = mapped_column(String(200), nullable=True)


class EscalationEdit(Base):
    """One cell changed on Field Team & Escalation → Escalation Sheet: who changed which contact of which GP, from what
    to what. Edits change the active import's contacts in place (escalation_contacts); a later Escalation Matrix
    upload replaces them (the sheet says so and offers an export of the edited matrix to upload again)."""

    __tablename__ = "escalation_edits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    import_id: Mapped[int] = mapped_column(ForeignKey("escalation_imports.id", ondelete="CASCADE"), index=True)
    gp_code: Mapped[str] = mapped_column(String(40), index=True)
    field: Mapped[str] = mapped_column(String(40))
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    edited_by_name: Mapped[str] = mapped_column(String(120))
    edited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class ImportReport(Base):
    """Upload report (JSON): what changed compared with the previous upload – GPs added / removed, new HOTO /
    AMC, changed dates, new weeks, sheets and columns. Kept for every upload (small), also after pruning."""

    __tablename__ = "import_reports"

    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), primary_key=True)
    previous_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    report: Mapped[str] = mapped_column(Text)


class ValidationIssue(Base):
    __tablename__ = "validation_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    sheet: Mapped[str] = mapped_column(String(60))
    row_number: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-based Excel row
    column: Mapped[str | None] = mapped_column(String(80), nullable=True)
    gp_code: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    severity: Mapped[str] = mapped_column(String(10))  # info|warning|critical
    code: Mapped[str] = mapped_column(String(40), index=True)
    message: Mapped[str] = mapped_column(Text)


class DatasetWeek(Base):
    __tablename__ = "dataset_weeks"

    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), primary_key=True)
    code: Mapped[str] = mapped_column(String(10), primary_key=True)  # "W-41"
    number: Mapped[int] = mapped_column(Integer)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)


class Gp(Base):
    __tablename__ = "gps"

    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), primary_key=True)
    gp_code: Mapped[str] = mapped_column(String(40), primary_key=True)
    source_row: Mapped[int] = mapped_column(Integer)
    location_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    name: Mapped[str] = mapped_column(String(160))
    circle: Mapped[str] = mapped_column(String(60), index=True)
    ba: Mapped[str | None] = mapped_column(String(80), nullable=True)
    district: Mapped[str] = mapped_column(String(80))
    block_name: Mapped[str] = mapped_column(String(120))
    block_code: Mapped[str] = mapped_column(String(40), index=True)
    block_hoto_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    np_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    gp_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    phase: Mapped[str | None] = mapped_column(String(40), nullable=True)
    lot: Mapped[str | None] = mapped_column(String(20), nullable=True)
    olt_location: Mapped[str | None] = mapped_column(String(160), nullable=True)
    bbnl_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    bsnl_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_rkm: Mapped[float | None] = mapped_column(Float, nullable=True)  # blank in the file = not reported
    hoto_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    lms_amc_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    letter_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    amc_category: Mapped[str | None] = mapped_column(String(20), nullable=True)  # AMC | INCREMENTAL
    amc_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    am_name: Mapped[str | None] = mapped_column(String(120), nullable=True)


class GpAmcPlan(Base):
    """GP-wise AMC conversion plan of the GP sheet ("Incremental AMC GPs Plan vs Achievement"): one row per GP in the
    plan. category = "5% Incremental" / "Additional Plan"; planned_date = target date; ach_date = date achieved."""

    __tablename__ = "gp_amc_plan"

    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), primary_key=True)
    gp_code: Mapped[str] = mapped_column(String(40), primary_key=True)
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    planned_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    ach_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    current_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    letter_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    letter_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # "Approval Status" of the letter: Letter to be submit / Pending by IE / Rejected BY IE / Approved By IE / Approved By BSNL
    approval_status: Mapped[str | None] = mapped_column(String(60), nullable=True)


class GpAvailability(Base):
    """Long-format availability values. kind: D=daily, W=weekly(AMC), M=monthly(all GPs), MA=monthly(AMC).
    `value` NULL means the source said NA / blank - it is never stored as 0."""

    __tablename__ = "gp_availability"

    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), primary_key=True)
    gp_code: Mapped[str] = mapped_column(String(40), primary_key=True)
    kind: Mapped[str] = mapped_column(String(2), primary_key=True)
    period: Mapped[str] = mapped_column(String(10), primary_key=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)


class GpAvailabilityPack(Base):
    """The same values as `gp_availability`, stored as one compressed GP × period matrix per dataset + kind.
    New imports write only this (a few MB instead of ~800k indexed rows); the analytics store loads it directly.
    `gp_availability` is still read for datasets imported before packs existed (they are packed on first load).
    `gp_codes` / `periods` are JSON lists; `values` is zlib-compressed little-endian float64, row-major, NaN = NA."""

    __tablename__ = "gp_availability_packs"

    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(2), primary_key=True)
    gp_codes: Mapped[str] = mapped_column(Text)
    periods: Mapped[str] = mapped_column(Text)
    values: Mapped[bytes] = mapped_column(LargeBinary)


class CircleSheetValue(Base):
    """One-Time-Up rows of the per-circle sheets ("Rajasthan", "Haryana", "Assam"), read at import so the
    dashboard never opens the workbook at request time. metric: oneTimeUpGps | oneTimeUpAmc | oneTimeUpNonAmc;
    period: "2026-09" (month) or "W-41" (week)."""

    __tablename__ = "circle_sheet_values"

    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), primary_key=True)
    circle: Mapped[str] = mapped_column(String(60), primary_key=True)
    metric: Mapped[str] = mapped_column(String(40), primary_key=True)
    period: Mapped[str] = mapped_column(String(10), primary_key=True)
    value: Mapped[float] = mapped_column(Float)


class ReportedNumber(Base):
    """'KEY NUMBERS' block of the O&M sheet, kept for reconciliation only."""

    __tablename__ = "reported_numbers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    state: Mapped[str] = mapped_column(String(60))
    metric: Mapped[str] = mapped_column(String(120))
    value_num: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_text: Mapped[str | None] = mapped_column(String(255), nullable=True)


class MasterBlock(Base):
    """Block-level figures from the 'Master Block' sheet (includes New GP counts not present GP-wise)."""

    __tablename__ = "master_blocks"

    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), primary_key=True)
    block_code: Mapped[str] = mapped_column(String(40), primary_key=True)
    state: Mapped[str] = mapped_column(String(60))
    block_name: Mapped[str] = mapped_column(String(120))
    total_gp_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    existing_gps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    new_gps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    block_status: Mapped[str | None] = mapped_column(String(60), nullable=True)


Index("ix_gp_dataset_block", Gp.dataset_id, Gp.block_code)


class GpDailyHistory(Base):
    """Daily GP availability kept across uploads, one compressed GP × day matrix per calendar month (same
    format as GpAvailabilityPack). The daily file drops its oldest day columns over time (the 21-10-26
    file starts on 16 Sep), so the previous month to date ("Sep-26 MTD") needs days that only earlier
    uploads had. Each import merges its daily columns in: for a day present in both, the file with the
    later data date wins; days the new file does not have are kept. Not tied to a dataset, so pruning
    old datasets never removes it."""

    __tablename__ = "gp_daily_history"

    month: Mapped[str] = mapped_column(String(7), primary_key=True)  # "2026-09"
    gp_codes: Mapped[str] = mapped_column(Text)
    periods: Mapped[str] = mapped_column(Text)  # ISO dates of the month present in the matrix
    values: Mapped[bytes] = mapped_column(LargeBinary)
    data_as_of: Mapped[date] = mapped_column(Date)  # data date of the newest file merged into this month
    source_file: Mapped[str] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ---------------------------------------------------------------- Ticket Management
# Work tickets an admin assigns to a dashboard user. Separate records for the ticket, each work submission, the files
# of a submission, the activity / status history and the in-app notifications. Users are never deleted (only
# deactivated), so the user links are kept; the names are also stored so a ticket stays readable on its own.


class Ticket(Base):
    """One work ticket. `code` (TKT-000123) is the ticket ID shown to people; `id` is never guessed from it.
    status: OPEN -> IN_PROGRESS -> PENDING_REVIEW -> CHANGES_REQUESTED -> PENDING_REVIEW … -> CLOSED (app.tickets.service)."""

    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)  # set right after the insert
    subject: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(10))  # LOW | MEDIUM | HIGH | CRITICAL
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    assignee_name: Mapped[str] = mapped_column(String(120))
    assignee_email: Mapped[str] = mapped_column(String(254))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by_name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # latest submission
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    closed_by_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    circle: Mapped[str | None] = mapped_column(String(80), nullable=True)  # Circle / State chosen when generating
    # Soft delete (admin): the ticket disappears from every list, KPI, monitor and notification; its GP rows, daily
    # progress, remarks and proof documents are kept as history (nothing is orphaned, nothing is reused)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    deleted_by_name: Mapped[str | None] = mapped_column(String(120), nullable=True)


class TicketRecipient(Base):
    """A person a generated ticket was sent to: CBH / SME / Area Manager of the Escalation Matrix (circle-wise) or another
    dashboard user. `user_id` = the active dashboard account with that e-mail at creation (None = e-mail only, no
    dashboard access). `can_work` = may start / submit / report progress (task ticket: the Area Manager only; the
    others follow it read-only). email_status: NONE (not requested) | PENDING | SENT | FAILED."""

    __tablename__ = "ticket_recipients"
    __table_args__ = (UniqueConstraint("ticket_id", "email", name="uq_ticket_recipient_email"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10))  # CBH | SME | AM | FE | USER | OTHER
    name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(254))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    can_work: Mapped[bool] = mapped_column(Boolean, default=False)
    attach_workbook: Mapped[bool] = mapped_column(Boolean, default=False)  # the Area Manager's own GP workbook
    email_status: Mapped[str] = mapped_column(String(10), default="NONE")
    email_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # last attempt
    # FE only: the Escalation Matrix mapping that decides the FE's GPs – parent Area Manager and the FE e-mail of
    # the matrix rows (None = rows without an FE e-mail); `email` is where the ticket e-mail goes
    am_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    fe_mail: Mapped[str | None] = mapped_column(String(200), nullable=True)


class TicketSubmission(Base):
    """One "Submit for Review" of the assigned user (version 1, 2 … after each change request) and the admin's
    review of it. review: PENDING | ACCEPTED | CHANGES_REQUESTED."""

    __tablename__ = "ticket_submissions"
    __table_args__ = (UniqueConstraint("ticket_id", "version", name="uq_ticket_submission_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    submitted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    submitted_by_name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    review: Mapped[str] = mapped_column(String(20), default="PENDING")
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_by_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class TicketAttachment(Base):
    """A file of a submission. Stored under DATA_DIR/tickets/<ticket id>/ with a random name (never the client's
    name, never a public folder); downloaded only through the API by the assignee or an admin."""

    __tablename__ = "ticket_attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("ticket_submissions.id", ondelete="CASCADE"), index=True)
    file_name: Mapped[str] = mapped_column(String(255))  # cleaned display name
    stored_name: Mapped[str] = mapped_column(String(80))
    content_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TicketEvent(Base):
    """Activity and status history of a ticket (created, started, submitted, changes requested, closed)."""

    __tablename__ = "ticket_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_name: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(30))
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class TicketNotification(Base):
    """In-app notification for one user about one ticket (shown under the header bell until read)."""

    __tablename__ = "ticket_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TicketTask(Base):
    """GP-wise weekly task of a ticket (optional, one per ticket): the Area Manager it was built for (Escalation Matrix),
    the reporting week, and the generated assignment workbook (kept unchanged as the reference document)."""

    __tablename__ = "ticket_tasks"

    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), primary_key=True)
    am_name: Mapped[str] = mapped_column(String(160))
    am_email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    week_code: Mapped[str] = mapped_column(String(10))
    week_start: Mapped[date] = mapped_column(Date)
    week_end: Mapped[date] = mapped_column(Date)
    data_as_of: Mapped[date] = mapped_column(Date)  # master data date the targets were taken from
    source_file: Mapped[str] = mapped_column(String(255))
    assignment_file: Mapped[str | None] = mapped_column(String(80), nullable=True)  # stored name under DATA_DIR/tickets/<id>/
    circle: Mapped[str | None] = mapped_column(String(80), nullable=True)
    cbh_name: Mapped[str | None] = mapped_column(String(160), nullable=True)  # CBH of the AM's GPs (Escalation Matrix)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TicketTaskGp(Base):
    """One GP of a task. The identification and the target are fixed at creation (never edited); `reported` (the Area
    Manager's cumulative achievement) and `remarks` move with the daily progress submissions."""

    __tablename__ = "ticket_task_gps"
    __table_args__ = (UniqueConstraint("ticket_id", "gp_code", name="uq_ticket_task_gp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    sort: Mapped[int] = mapped_column(Integer)
    gp_code: Mapped[str] = mapped_column(String(40))
    gp_name: Mapped[str] = mapped_column(String(160))
    circle: Mapped[str] = mapped_column(String(80))
    business_area: Mapped[str | None] = mapped_column(String(120), nullable=True)
    district: Mapped[str | None] = mapped_column(String(120), nullable=True)
    block: Mapped[str | None] = mapped_column(String(160), nullable=True)
    kind: Mapped[str] = mapped_column(String(10))  # WEEK = Planned Date in the week · PENDING = planned earlier, not achieved · ADDED = added by the FE / AM
    category: Mapped[str | None] = mapped_column(String(60), nullable=True)
    planned_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    ready_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # Ach Date at creation
    amc_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # AMC Date at creation
    target: Mapped[int] = mapped_column(Integer, default=1)
    base_achieved: Mapped[int] = mapped_column(Integer, default=0)  # achieved in the master data (AMC Date) at creation
    reported: Mapped[int] = mapped_column(Integer, default=0)  # achieved by the Area Manager's daily submissions
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)  # latest remark
    # Field Engineer of the GP in the Escalation Matrix at creation (None = no FE mapped)
    fe_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    fe_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Current GP classification chosen in the daily progress (A–E, app.tickets.task.CATEGORIES; None = not classified
    # yet). One value per GP of the ticket – a later choice replaces it; every choice stays in the progress lines.
    gp_category: Mapped[str | None] = mapped_column(String(1), nullable=True)
    # Review chain of the GP (app.tickets.review): None = with the FE / Area Manager · RETURNED (to the FE) ·
    # AM_APPROVED · SME_FORWARDED · LETTER_SUBMITTED · AMC_CONVERTED; each step is a TicketGpReview row
    review: Mapped[str | None] = mapped_column(String(20), nullable=True)
    review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    letter_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # COH: letter submitted on
    amc_on: Mapped[date | None] = mapped_column(Date, nullable=True)  # COH: AMC converted on
    # A GP the FE / Area Manager added to the ticket (kind ADDED, target 1) – who added it
    added_by: Mapped[str | None] = mapped_column(String(120), nullable=True)


class TicketGpReview(Base):
    """One step on one GP of a task: the FE / Area Manager edited or added it, the Area Manager approved or returned it,
    the SME forwarded it with the confirmed category, the COH recorded the letter submission / AMC conversion. Never
    edited – the GP's history."""

    __tablename__ = "ticket_gp_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    task_gp_id: Mapped[int] = mapped_column(ForeignKey("ticket_task_gps.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10))  # FE | AM | SME | COH | ADMIN
    action: Mapped[str] = mapped_column(String(20))  # EDIT | ADD | AM_APPROVE | AM_RETURN | SME_FORWARD | COH_LETTER | COH_AMC
    category: Mapped[str | None] = mapped_column(String(1), nullable=True)  # category after the step (A–E)
    on_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # letter / AMC date
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_name: Mapped[str] = mapped_column(String(120))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class TicketProgress(Base):
    """One "Submit Daily Progress" of the Area Manager (a separate record per submission – never overwritten)."""

    __tablename__ = "ticket_progress"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    submitted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    submitted_by_name: Mapped[str] = mapped_column(String(120))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class TicketProgressLine(Base):
    """A GP line of a daily submission: that day's achievement and remark, and the cumulative / gap right after it."""

    __tablename__ = "ticket_progress_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    progress_id: Mapped[int] = mapped_column(ForeignKey("ticket_progress.id", ondelete="CASCADE"), index=True)
    task_gp_id: Mapped[int] = mapped_column(ForeignKey("ticket_task_gps.id", ondelete="CASCADE"), index=True)
    achieved_today: Mapped[int] = mapped_column(Integer, default=0)
    cumulative: Mapped[int] = mapped_column(Integer)
    gap: Mapped[int] = mapped_column(Integer)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(1), nullable=True)  # GP classification chosen in this line (A–E)


class TicketProgressFile(Base):
    """A proof document the Area Manager attached to one GP line of a daily submission (e.g. the letter of a GP marked
    Done). Stored like the submission attachments (DATA_DIR/tickets/<ticket id>/<random name>, app.tickets.files) and
    downloaded only through the API after the ticket's permission check."""

    __tablename__ = "ticket_progress_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    progress_line_id: Mapped[int] = mapped_column(ForeignKey("ticket_progress_lines.id", ondelete="CASCADE"), index=True)
    task_gp_id: Mapped[int] = mapped_column(ForeignKey("ticket_task_gps.id", ondelete="CASCADE"), index=True)
    file_name: Mapped[str] = mapped_column(String(255))  # cleaned display name
    stored_name: Mapped[str] = mapped_column(String(80))
    content_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------- Non-Doable GP exception workflow (app.tickets.nondoable)
# FE → AM → SME → COH → Corporate Team – MGG. A case belongs to one GP of a task ticket (never a new ticket / GP);
# forms, review steps and evidence are separate rows that are never edited (complete history).


class NdCase(Base):
    """One Non-Doable proposal of a GP (round 1, 2 … after a rejection and revisit). `ref` (ND-000001) is shown to
    people. status: PROPOSED → E1_DONE → PENDING_AM → PENDING_SME → PENDING_COH → PENDING_MGG → APPROVED | REJECTED;
    RETURNED_FE / RETURNED_AM / RETURNED_SME on a return for correction; WITHDRAWN by the FE before the AM review."""

    __tablename__ = "nd_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ref: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)  # set right after the insert
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    task_gp_id: Mapped[int] = mapped_column(ForeignKey("ticket_task_gps.id", ondelete="CASCADE"), index=True)
    gp_code: Mapped[str] = mapped_column(String(40), index=True)
    round: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), index=True)
    physical_status: Mapped[str] = mapped_column(String(20), default="PENDING")  # PENDING | SUBMITTED
    evidence_status: Mapped[str] = mapped_column(String(20), default="NONE")  # NONE | SUBMITTED
    approval_status: Mapped[str] = mapped_column(String(20), default="NOT_SUBMITTED")  # NOT_SUBMITTED | IN_REVIEW | RETURNED | APPROVED | REJECTED | WITHDRAWN
    # after a rejection: COORDINATION (FE with the FRT team) → FRT_VISIT (waiting for the visit) → FRT_UPDATED (FE review) → REVIEWED
    revisit_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fe_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    fe_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by_name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decision: Mapped[str | None] = mapped_column(String(10), nullable=True)  # APPROVED | REJECTED (Corporate Team – MGG)
    decided_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_by_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_remark: Mapped[str | None] = mapped_column(Text, nullable=True)


class NdRecord(Base):
    """A form submitted by the FE: VERIFICATION (E1 physical verification), JUSTIFICATION (E2), REVISIT_COORDINATION /
    REVISIT_VISIT (FRT coordination and the new FRT site visit after a rejection). Each submission is a new row."""

    __tablename__ = "nd_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("nd_cases.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(25))
    visit_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    visitor_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    findings: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    frt_team: Mapped[str | None] = mapped_column(Text, nullable=True)
    frt_visit: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(1), nullable=True)  # REVISIT_VISIT: FRT outcome A / C / D
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by_name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NdEvent(Base):
    """Audit history of a case: every action with the status before / after, who (name and role), when, remarks,
    recommendation, decision, return / rejection reason and the form it came with."""

    __tablename__ = "nd_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("nd_cases.id", ondelete="CASCADE"), index=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    task_gp_id: Mapped[int] = mapped_column(ForeignKey("ticket_task_gps.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(4))  # E1 … E6 | RV (revisit)
    action: Mapped[str] = mapped_column(String(30), index=True)
    role: Mapped[str] = mapped_column(String(10))  # FE | AM | SME | COH | MGG
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20))
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)  # return / rejection reason
    decision: Mapped[str | None] = mapped_column(String(10), nullable=True)
    record_id: Mapped[int | None] = mapped_column(ForeignKey("nd_records.id", ondelete="SET NULL"), nullable=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_name: Mapped[str] = mapped_column(String(120))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class NdFile(Base):
    """Evidence / site photograph of a case form, stored like the ticket files (DATA_DIR/tickets/<ticket id>/<random
    name>, app.tickets.files) and downloaded only through the API after the case permission check."""

    __tablename__ = "nd_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("nd_cases.id", ondelete="CASCADE"), index=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    record_id: Mapped[int | None] = mapped_column(ForeignKey("nd_records.id", ondelete="SET NULL"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(10))  # EVIDENCE | PHOTO
    file_name: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(80))
    content_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    uploaded_by_name: Mapped[str] = mapped_column(String(120))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NdMggMember(Base):
    """A dashboard account authorised by an admin as Corporate Team – MGG (the final Non-Doable decision)."""

    __tablename__ = "nd_mgg_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    added_by_name: Mapped[str] = mapped_column(String(120))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())