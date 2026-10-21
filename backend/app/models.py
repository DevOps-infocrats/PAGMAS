"""Database schema.

Every imported workbook becomes a *dataset*. GP rows, availability values and
validation issues are stored per dataset, so a failed import never touches the
dataset currently served to the dashboard (only one dataset is `is_active`).

Personal contact data present in the source (splicer / FE / AM / SPOC phone
numbers) is deliberately NOT imported. Only the Area Manager name is kept,
because area-manager performance is a dashboard requirement.
"""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, String, Text, func
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
    district: Mapped[str | None] = mapped_column(String(80), nullable=True)
    block_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    block_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    gp_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    frt_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    splicer_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    splicer_phone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    fe_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    fe_phone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    am_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    am_phone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    shq_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    shq_phone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    coh_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    coh_phone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    cbh_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cbh_phone: Mapped[str | None] = mapped_column(String(80), nullable=True)


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
    total_rkm: Mapped[float] = mapped_column(Float, default=0.0)
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
