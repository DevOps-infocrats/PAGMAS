import type {
  AreaManager,
  Block,
  BlockSummary,
  Circle,
  CircleSummary,
  DataQualityIssue,
  DemoNotification,
  District,
  GpSnapshot,
  IngestionRun,
  KpiValue,
  Olt,
  Paginated,
  ReportingWeek,
  TrendSeries,
} from "@/types";

/**
 * API contracts shared by the mock client and the FastAPI client
 * (backend/app/analytics/views.py builds exactly these shapes).
 * Every page talks to `DashboardApi` only — `lib/api/index.ts` picks the implementation.
 */

export interface MetaResponse {
  weeks: ReportingWeek[];
  latestWeekId: string;
  circles: Circle[];
  districts: District[];
  blocks: Pick<Block, "id" | "name" | "code" | "circleId" | "districtId">[];
  /** Last day with data in the imported file (live mode only) */
  dataAsOf?: string;
  datasetFileName?: string;
  importedAt?: string | null;
  thresholds?: { healthy: number; penalty: number };
}

export interface PeriodParams {
  weekId: string;
  compareWeekId: string;
}

/** Every figure shown on the Circle Overview (backend: views._detail). */
export interface OverviewDetail {
  states: number;
  blocks: number;
  existingGps: number;
  /** From the Master Block sheet; null when that sheet was not available */
  newGps: number | null;
  totalGps: number | null;
  revisedExisting: number;
  convertedOrClosed: number;
  convertedNp: number;
  permanentlyClosed: number;
  deductedGps: number;
  hotoDoneBlocks: number;
  hotoPendingBlocks: number;
  hotoDoneGps: number;
  hotoPendingGps: number;
  /** AMC GPs not classified Incremental in the source column (= amcOriginalGps) */
  amcAtHotoGps: number;
  amcGps: number;
  amcOriginalGps: number;
  incrementalGps: number;
  nonAmcGps: number;
  amcPct: number | null;
  availability: number | null;
  gpsAbove98: number;
  gpsAtZero: number;
  naGps: number;
  penaltyBlocks: number;
  /** AMC GPs with MTD availability below the penalty threshold (0% included) */
  gpsBelowPenalty: number;
  /** Blocks whose mean AMC GP availability (MTD) is above the healthy threshold */
  blocksAbove98: number;
  /** AMC GPs / blocks with an MTD availability value (base of the availability percentages) */
  reportingGps: number;
  reportingBlocks: number;
  oneTimeUp: number;
  totalRkm: number;
  bsnlRkm: number;
  bbnlRkm: number;
  amcRkm: number;
  rkmPartsDifference: number | null;
}

export interface OverviewResponse {
  summary?: OverviewDetail;
  stateDetails?: (OverviewDetail & { id: string; name: string })[];
  /** Date the MTD figures run up to */
  asOf?: string;
  weeks: ReportingWeek[];
  kpis: KpiValue[];
  circles: CircleSummary[];
  circlesPrevious: CircleSummary[];
  areaManagers: {
    circleId: string;
    manager: AreaManager;
    gps: number;
    amcGps?: number;
    availability: number | null;
    gpsAbove98: number;
    gpsAtZero?: number;
    penaltyBlocks: number;
    blocks?: number;
    revisedExisting?: number;
  }[];
}

export interface CircleInsightsResponse {
  circle: Circle;
  weeks: ReportingWeek[];
  kpis: KpiValue[];
  blocks: BlockSummary[];
  hotoAmc: {
    districtId: string;
    districtName: string;
    applicable: number;
    hotoDone: number;
    hotoPending: number;
    amc: number;
    nonAmc: number;
    blocks?: number;
    hotoDoneBlocks?: number;
    existingGps?: number;
    newGps?: number | null;
    amcOriginal?: number;
    incremental?: number;
  }[];
  gpUptimeTrend: TrendSeries[];
  blockUptimeTrend: TrendSeries[];
  /** Full source availability bands per week (live mode) */
  gpBandTable?: BandTableRow[];
  blockBandTable?: BandTableRow[];
  /** Day-by-day bands for the days of the selected week that have data */
  gpDailyBands?: BandTableRow[];
  blockDailyBands?: BandTableRow[];
  bands?: string[];
  summary?: OverviewDetail & { districts: number };
  asOf?: string;
  currentWeek?: ReportingWeek;
  /** Month-wise + week-wise progress and uptime bands, computed from GP-level data */
  periodTable?: PeriodTable;
}

export interface PeriodBands {
  counts: Record<string, number>;
  /** GPs / blocks with a value */
  reported: number;
  /** AMC GPs (or HOTO-done blocks) without a value */
  na: number;
  average: number | null;
}

export interface PeriodTable {
  /** kind "ptd" = previous month to the same day as the current TD (e.g. Sep-26 TD = 1–8 Sep) */
  periods: { key: string; label: string; kind: "month" | "ptd" | "mtd" | "week"; endDate: string }[];
  hotoAmc: { hotoDoneBlocks: number; hotoDoneGps: number; amcGps: number; amcRkm: number }[];
  rfpTarget: { value: number; periodKey: string | null; basis: string };
  gpBands: PeriodBands[];
  blockBands: PeriodBands[];
}

export interface BandTableRow {
  weekId?: string;
  date: string;
  /** e.g. "W-41" or "Fri 02 Oct" */
  label?: string;
  counts: Record<string, number>;
  /** GPs / blocks with a value (excludes NA) */
  reported?: number;
  /** Mean availability of the reported values */
  average?: number | null;
}

export interface BlockInsightsResponse {
  circle: Circle;
  district: District;
  block: Block;
  weeks: ReportingWeek[];
  kpis: KpiValue[];
  gps: GpSnapshot[];
  olts: (Olt & { gpCount: number })[];
  uptimeTrend: TrendSeries[];
  classification: { label: string; count: number }[];
  incrementalByWeek: { weekId: string; date: string; added: number }[];
  /** Block KPIs (same rules as the circle summary; new GPs from the Master Block sheet) */
  summary?: OverviewDetail;
  /** GP-wise availability per period column and per day of the selected week */
  gpUptime?: BlockGpUptime;
  /** GP codes behind the AMC KPI (same masks as the counts) */
  amcGroups?: { amc: string[]; incremental: string[]; nonAmc: string[] };
  asOf?: string;
}

export interface BlockUptimeColumn {
  key: string;
  label: string;
  kind: "month" | "ptd" | "mtd" | "week" | "day";
  endDate: string;
  /** GPs under AMC by the column end */
  amcGps: number;
  reported: number;
  na: number;
  /** Block value = mean of its AMC GPs' values */
  average: number | null;
  counts: Record<string, number>;
}

export interface GpUptimeColumn {
  key: string;
  label: string;
  kind: "month" | "ptd" | "mtd" | "week" | "day";
  endDate: string;
  /** number, "NA" (under AMC, not reported) or null (not under AMC yet) */
  value: number | "NA" | null;
  band: string | null;
  blockAverage: number | null;
  /** Days spent in each band in this period (daily sheet, days under AMC); null when the daily sheet does not cover it */
  days: { counts: Record<string, number>; reported: number; na: number; underAmc: number } | null;
}

export interface GpUptime {
  columns: GpUptimeColumn[];
  bands: string[];
  thresholds: { healthy: number; penalty: number };
  /** First date of the daily sheet */
  dailyFrom?: string;
}

export interface BlockGpUptime {
  columns: BlockUptimeColumn[];
  /** values[i] for columns[i]: number, "NA" (under AMC, not reported) or null (not under AMC yet) */
  rows: { id: string; name: string; amcDate: string | null; amcCategory: string | null; values: (number | "NA" | null)[] }[];
  bands: string[];
  thresholds: { healthy: number; penalty: number };
}

export interface GpDetailResponse {
  gp: GpSnapshot;
  week: ReportingWeek;
  /** null = history unavailable for this GP */
  availabilityHistory: { weekId: string; date: string; value: number | null }[] | null;
  dailyHistory?: { date: string; value: number | null }[] | null;
  monthlyHistory?: { month: string; value: number | null; amcValue: number | null }[];
  hotoHistory: { date: string | null; event: string }[];
  olt: Olt | null;
  addedWeek: ReportingWeek | null;
  revisedExisting: boolean;
  issues: DataQualityIssue[];
  dataAsOf?: string;
  /** Availability per period column next to the GP's block value (live backend only) */
  uptime?: GpUptime;
}

export interface GpListQuery {
  circleId?: string;
  districtId?: string;
  blockId?: string;
  weekId: string;
  search?: string;
  page?: number;
  pageSize?: number;
}

export interface SearchResult {
  type: "circle" | "block" | "gp";
  id: string;
  label: string;
  sublabel: string;
  circleId: string;
  districtId?: string;
  blockId?: string;
}

export interface ReportParams extends PeriodParams {
  circleId?: string;
  districtId?: string;
  blockId?: string;
}

export interface ReportComparisonRow {
  key: string;
  label: string;
  unit: "count" | "percent" | "rkm";
  polarity: "up" | "down" | "neutral";
  previous: number | null;
  current: number | null;
}

export interface WeeklyReportResponse {
  scopeLabel: string;
  week: ReportingWeek;
  compareWeek: ReportingWeek;
  generatedAt: string;
  isDemo: boolean;
  dataAsOf?: string;
  sourceFile?: string;
  comparison: ReportComparisonRow[];
  ranking: { id: string; name: string; availability: number | null; previous: number | null; amcPct: number | null; penaltyBlocks: number }[];
  hotoProgress: { label: string; done: number; pending: number }[];
  penaltyBlocks: { id: string; name: string; circleName: string; districtName: string; availability: number | null; previous: number | null }[];
  lowAvailabilityGps: { id: string; name: string; blockName: string; availability: number }[];
  dataQuality: { label: string; count: number; severity: "warning" | "critical" }[];
  fibreChanges: { label: string; previous: number | null; current: number | null }[];
}

/* ---------------- Management Review (backend: analytics/review.py) ---------------- */

export type ReviewTrend = "better" | "worse" | "flat" | "up" | "down" | "na";

export interface ReviewChange {
  previous: number | null;
  current: number | null;
  delta: number | null;
  trend: ReviewTrend;
}

export interface ReviewPeriod {
  key: string;
  label: string;
  /** ptd = previous month to the same day as the month TD (e.g. "Sep-26 TD" = 1–8 Sep) */
  kind: "month" | "ptd" | "mtd" | "week";
  endDate: string;
}

export interface ReviewKpiRow {
  key: string;
  label: string;
  unit: "count" | "percent";
  polarity: "up" | "down" | "neutral";
  /** "computed" from GP-level data, or "circle sheet" (One-Time-Up, external report) */
  source: string;
  /** one value per period */
  values: (number | null)[];
}

export interface ReviewBandTable {
  bands: { band: string; values: number[] }[];
  scope: number[];
  total: number[];
  na: number[];
  belowPenalty: number[];
  average: (number | null)[];
}

export interface ReviewInsight extends ReviewChange {
  label: string;
  from: string;
  to: string;
  unit: "count" | "percent";
}

export interface ReviewSection {
  id: string;
  name: string;
  code: string;
  kpis: ReviewKpiRow[];
  weekChange: (ReviewChange & { key: string; label: string; unit: "count" | "percent"; polarity: "up" | "down" | "neutral" })[];
  gpUptime: ReviewBandTable;
  blockUptime: ReviewBandTable;
  insights: { kpi: ReviewInsight[]; gp: ReviewInsight[]; block: ReviewInsight[] };
  /** Page 3 – monthly & weekly performance table (backend: analytics/review_critical.py) */
  critical?: {
    title: string;
    columns: { key: string; label: string; kind: "month" | "ptd" | "mtd" | "week"; endDate: string }[];
    rows: { key: string; label: string; polarity: "up" | "down" | "neutral"; scope: number | null; values: (number | null)[]; source: string }[];
    insight: { from: string; to: string; items: (ReviewChange & { label: string })[] };
  };
  detail: {
    penaltyBlocks: {
      id: string;
      name: string;
      districtName: string;
      amName: string | null;
      amcGps: number;
      availability: number | null;
      weekAvailability: number | null;
      previousWeek: number | null;
      gpsAtZero: number;
    }[];
    penaltyBlockCount: number;
    districts: { id: string; name: string; blocks: number; amcGps: number; availability: number | null; gpsAbove98: number; gpsAtZero: number; penaltyBlocks: number }[];
  } | null;
}

export interface ReviewTargetRow {
  id: string;
  name: string;
  code: string;
  revisedExisting: number;
  existingGps: number;
  hotoGps: number;
  amcGps: number;
  amcPct: number | null;
  target: number | null;
  targetGap: number | null;
  targetAchievedPct: number | null;
  targetCoveragePct: number | null;
  requiredPerDay: number | null;
  addedThisMonth: number;
  rfpTarget: number;
  rfpGap: number;
  rfpAchievedPct: number | null;
  pendingConversion: number;
}

export interface ReviewSummaryChange extends ReviewChange {
  /** % change; null when the comparison value is 0 */
  pctChange: number | null;
}

export interface ReviewRange {
  start: string;
  end: string;
  range: string;
}

export interface ReviewHighlightRow {
  id: string;
  code: string;
  name: string;
  currentAmc: number;
  /** one value per highlightTable.weeks entry: GPs achieved in that week by Ach Date (GP-wise plan, same as
   *  AMC Conversion → week achieved); null when the file has no GP-wise plan */
  weeklyConversions: (number | null)[];
  readyForIncremental: number;
  monthPlan: number | null;
}

export interface ReviewSummary {
  title: string;
  kicker: string;
  subtitle: string;
  periods: {
    week: ReviewRange & { id: string; number: number; label: string; title: string; complete: boolean };
    compareWeek: ReviewRange & { id: string; number: number; label: string; title: string };
    cutoff: string;
    month: ReviewRange;
    previousMonth: ReviewRange;
    warnings: string[];
  };
  latestAmcDate: string | null;
  kpis: (ReviewSummaryChange & {
    key: string;
    label: string;
    unitOfCount: "GPs" | "blocks";
    currentPct: number | null;
    previousPct: number | null;
    ppChange: number | null;
    currentDenominator: number;
    previousDenominator: number;
    breakdown: (ReviewSummaryChange & { id: string; code: string })[];
  })[];
  conversions: {
    id: string;
    code: string;
    name: string;
    week: { amc: ReviewSummaryChange; incremental: ReviewSummaryChange };
    month: { amc: ReviewSummaryChange; incremental: ReviewSummaryChange };
    uncategorised: number;
  }[];
  highlightTable: {
    targetMonth: string | null;
    targetLabel: string;
    targetSource: string | null;
    targetBasis: string;
    targetMonthMatches: boolean;
    rows: ({ weekAmc: number; weekIncremental: number; previousWeekAmc: number; target: number | null; amcGpsAsOfCutoff: number; targetProgressPct: number | null; targetGap: number | null } & ReviewHighlightRow)[];
    /** Key Highlights | AMC & monthly plan */
    title: string;
    /** last four weeks ending with the reporting week */
    weeks: { id: string; label: string; start: string; end: string }[];
    monthPlanLabel: string;
    cutoff: string;
    basis: string;
    total: ReviewHighlightRow;
  };
  insights: { kind: "observation" | "action" | "data"; text: string }[];
  checks: { name: string; ok: boolean; warningOnly?: boolean }[];
  valid: boolean;
  warnings: string[];
  definitions: string[];
}

export interface ReviewRoadmapRow {
  id: string;
  code: string;
  name: string;
  revisedScope: number | null;
  amcTillPrevMonth: number | null;
  mtdPlan: number | null;
  projection: number | null;
  projectedCoveragePct: number | null;
  planByMonth: number | null;
  cumulativeMtd: number | null;
  mtdAchieved: number | null;
  /** achieved against the plan: GPs whose Ach Date (GP-wise plan block) falls in the month, up to achievedAsOf –
   *  same count as AMC Conversion → "Achieved this month (MTD)"; null when the file has no GP-wise plan */
  planAchieved?: number | null;
  planAchievedPct?: number | null;
  gap: number | null;
  pendingAfterMonth: number | null;
  /** one value per roadmap.futureMonths entry */
  futurePlans: (number | null)[];
  /** overall row only: true when a circle has no plan for that month */
  futurePlansPartial?: boolean[];
  readyForIncremental: number | null;
}

export interface ReviewWeeklyCell {
  /** new target: GPs with a Planned Date in the week (master data file) */
  target: number | null;
  /** old target: the manually set weekly closure target (review_plan.json), when there is one */
  oldTarget?: number | null;
  /** new − old target; negative = new target below the old one (highlighted) */
  targetChange?: number | null;
  /** GPs with an Ach Date in the week, up to the cutoff; null = week not started */
  achieved: number | null;
  achievedPct: number | null;
}

export interface ReviewTargetsPage {
  title: string;
  month: string;
  monthLabel: string;
  cutoff: string;
  /** date the plan achievement (Ach Date) is counted up to */
  achievedAsOf?: string;
  previousMonthEnd: string;
  daysLeft: number;
  planSource: string | null;
  roadmap: {
    title: string;
    subtitle: string;
    planHeader: string;
    liquidationHeader: string;
    columns: Record<"amcTillPrevMonth" | "mtdPlan" | "planAchieved" | "projection" | "projectedCoveragePct" | "planByMonth" | "cumulativeMtd" | "gap" | "pendingAfterMonth" | "readyForIncremental", string>;
    futureMonths: string[];
    rows: ReviewRoadmapRow[];
    total: ReviewRoadmapRow;
  };
  weekly: {
    title: string;
    weeks: { id: string; label: string; start: string; end: string; status: "done" | "in progress" | "not started"; current?: boolean }[];
    rows: { id: string; code: string; name: string; pendingScope: number; frt: number | null; weeks: ReviewWeeklyCell[] }[];
    total: { id: string; code: string; name: string; pendingScope: number; frt: number | null; weeks: ReviewWeeklyCell[] };
  };
  /** Rajasthan / Haryana / Assam – GPs converted to AMC (AMC + incremental, by AMC date) */
  circleCards?: {
    asOf: string;
    weekLabel: string;
    compareLabel: string;
    monthLabel: string;
    previousMonthLabel: string;
    baselineLabel: string | null;
    cards: {
      id: string;
      code: string;
      name: string;
      amcNow: number;
      revisedScope: number;
      amcPct: number | null;
      week: ReviewSummaryChange;
      month: ReviewSummaryChange;
      trend: { label: string; value: number }[];
      baseline: { label: string; value: number; sinceChange: number } | null;
    }[];
  };
  definitions: string[];
  warnings: string[];
}

export interface ReviewScopeTriple {
  scope: number;
  hoto: number;
  amc: number;
}

export interface ManagementReviewResponse {
  title: string;
  week: ReportingWeek;
  compareWeek: ReportingWeek;
  dataAsOf: string;
  asOf: string;
  sourceFile: string;
  generatedAt: string;
  thresholds: { healthy: number; penalty: number };
  periods: ReviewPeriod[];
  circles: { id: string; code: string; name: string }[];
  executive: {
    scope: { gps: ReviewScopeTriple; blocks: ReviewScopeTriple; rkm: ReviewScopeTriple };
    availability: { value: number | null; previous: number | null; compareLabel: string | null; breakdown: { code: string; value: number | null }[] };
    tiles: (Omit<ReviewChange, "current"> & { key: string; label: string; caption: string; value: number; compareLabel: string | null; breakdown: { code: string; value: number }[] })[];
    highlights: string[];
  };
  /** Page 1 – Executive Summary (backend: analytics/review_summary.py) */
  summary: ReviewSummary;
  /** Page 2 – Target & Achievement (backend: analytics/review_targets.py) */
  targetsPage: ReviewTargetsPage;
  targets: { label: string | null; source: string | null; monthEnd: string; daysLeft: number; rfpBasis: string; rows: ReviewTargetRow[] };
  operations: {
    label: string;
    endDate: string;
    circles: { circleId: string; code: string; blocks: ReviewScopeTriple & { gap: number }; gps: ReviewScopeTriple & { gap: number }; rkm: ReviewScopeTriple & { gap: number } }[];
  }[];
  /** keyed by circle id, plus "all" */
  sections: Record<string, ReviewSection>;
  dataNotes: {
    definitions: string[];
    reconciliation: { sourceMtdEnd: string | null; counts: Record<string, number>; rows: ReconciliationRow[] };
    dataQuality: { label: string; count: number; severity: string }[];
  };
}

export interface ReconciliationRow {
  state: string;
  metric: string;
  reported: number | null;
  computed: number | null;
  difference: number | null;
  status: "MATCH" | "EXPLAINED" | "MISMATCH" | "NO_REFERENCE";
  note: string | null;
}

export interface ReconciliationResponse {
  dataAsOf: string;
  sourceMtdEnd: string | null;
  penaltyThreshold: number;
  rows: ReconciliationRow[];
}

export interface RunIssuesResponse {
  total: number;
  summary: { code: string; severity: string; count: number }[];
  items: { row: number | null; column: string | null; gpCode: string | null; severity: string; code: string; message: string; sheet: string }[];
}

export type ScopeLevel = "circle" | "district" | "block";

/** One circle / district / block a viewer receives in the AMC Conversion e-mails. */
export interface UserScope {
  level: ScopeLevel;
  id: string;
  /** null when the area is no longer in the active data (then it is ignored) */
  label: string | null;
  valid: boolean;
}

export interface AppUser {
  id: number;
  email: string;
  name: string;
  role: "admin" | "viewer";
  isActive: boolean;
  lastLoginAt: string | null;
  locked: boolean;
  /** viewers only; admins receive every circle */
  scopes: UserScope[];
}

export interface UserLocations {
  hasData: boolean;
  circles: { id: string; name: string; districts: { id: string; name: string; blocks: { id: string; name: string }[] }[] }[];
}

export interface UserCreateBody {
  email: string;
  name: string;
  role: "admin" | "viewer";
  password: string;
  scopes?: { level: ScopeLevel; id: string }[];
}

export interface UserUpdateBody {
  name?: string;
  email?: string;
  role?: "admin" | "viewer";
  isActive?: boolean;
  password?: string;
  scopes?: { level: ScopeLevel; id: string }[];
}

/* ---------------------------------------------------------------- Mail Configuration */

/** CBH is stored from the Escalation Matrix as a backup only and is never mailed. */
export type MailAudience = "am" | "sme" | "coh" | "users";
export type MailFrequency = "daily" | "weekly" | "monthly";

export interface MailStatus {
  smtp: { configured: boolean; problems: string[]; server: string | null; port: number | null; security: "SSL" | "STARTTLS" | "none"; usernameSet: boolean; sender: string | null };
  /** AMC_REPORT_EMAILS_ENABLED – master switch of the scheduled e-mails */
  reportEmailsEnabled: boolean;
  approvalEmailsEnabled: boolean;
  schedulerRunning: boolean;
  timezone: string;
}

/** A person of the Escalation Matrix (Area Manager / SME / COH) */
export interface MailPerson {
  id: string;
  role: Exclude<MailAudience, "users">;
  roleLabel: string;
  name: string;
  circleId: string;
  circle: string;
  emails: string[];
  gps: number;
  businessAreas: string[];
}

export interface MailOptions {
  hasData: boolean;
  hasMatrix: boolean;
  audiences: { id: MailAudience; label: string }[];
  filters: { circles: { id: string; name: string }[]; businessAreas: { name: string; circleId: string }[]; blocks: { id: string; circleId: string; name: string }[] };
  people: MailPerson[];
  users: { id: number; name: string; email: string; role: string }[];
  placeholders: { name: string; description: string; table: boolean }[];
}

export interface MailTemplateItem {
  id: number;
  key: string | null;
  builtIn: boolean;
  name: string;
  description: string | null;
  subject: string;
  body: string;
  usedBy: number;
  updatedAt: string | null;
}

export interface MailTemplateBody {
  name: string;
  description: string | null;
  subject: string;
  body: string;
}

export interface MailPreview {
  recipient: { name: string; role: string; emails: string[] };
  subject: string;
  html: string;
  text: string;
}

export interface MailConfigBody {
  name: string;
  templateId: number | null;
  audiences: MailAudience[];
  filterCircles: string[];
  filterBusinessAreas: string[];
  filterBlocks: string[];
  filterPeople: string[];
  userIds: number[];
  frequency: MailFrequency;
  startDate: string;
  sendTime: string;
  weekday: number | null;
  monthDay: number | null;
  enabled: boolean;
}

export interface MailConfigItem extends MailConfigBody {
  id: number;
  templateName: string;
  summary: string;
  timezone: string;
  nextRunAt: string | null;
  lastRunAt: string | null;
  lastStatus: string | null;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface MailRecipientPreview {
  hasData: boolean;
  recipients: { name: string; roles: string; emails: string[]; areas: string[]; gps: number; breakdown: "block" | "am" }[];
  skipped: { name: string; role: string; reason: string }[];
}

export interface MailRunItem {
  id: number;
  configId: number;
  configName: string;
  scheduledFor: string | null;
  startedAt: string | null;
  finishedAt: string | null;
  status: "RUNNING" | "SUCCESS" | "PARTIAL" | "FAILED" | "SKIPPED";
  sent: number;
  failed: number;
  skipped: number;
  message: string | null;
}

/* ---------------------------------------------------------------- KPI drill-down lists */

export type KpiListKind = "gps-above-98" | "gps-at-zero" | "penalty-blocks" | "hoto-gps" | "hoto-blocks" | "existing-gps" | "new-gp-blocks" | "na-gps" | "one-time-up" | "hoto-pending-gps" | "hoto-pending-blocks" | "all-blocks" | "non-amc-gps" | "amc-original-gps" | "incremental-gps" | "amc-gps" | "removed-gps"
  | "amc-plan-month" | "amc-plan-mtd" | "amc-achieved-mtd" | "amc-plan-week" | "amc-achieved-week" | "amc-overdue";
/** value = the list's measure: MTD availability, HOTO date or HOTO coverage */
export type KpiListSort = "value-desc" | "value-asc" | "name";

export interface KpiListQuery {
  weekId: string;
  circleId?: string;
  districtId?: string;
  blockId?: string;
  search?: string;
  sort?: KpiListSort;
  page?: number;
  pageSize?: number;
}

/** One GP (unit "gp") or one block (unit "block") behind a KPI card. */
export interface KpiListItem {
  id: string;
  name: string;
  code: string;
  circleId: string;
  circle: string;
  districtId: string;
  district: string;
  blockId: string;
  block: string;
  /** MTD availability % (availability lists) */
  availability?: number | null;
  /** GP lists */
  amcDate?: string | null;
  /** Source AMC date (not hidden by the selected reporting-week cutoff) */
  amcSourceDate?: string | null;
  hotoDate?: string | null;
  /** penalty-prone block list */
  amcGps?: number;
  reportedGps?: number;
  /** HOTO block list */
  totalGps?: number;
  hotoGps?: number;
  hotoPct?: number | null;
  /** HOTO-pending block list: revised existing GPs in the block */
  revisedGps?: number;
  /** all-blocks list: AMC breakdown columns */
  amcOriginalGps?: number;
  incrementalGps?: number;
  totalAmcGps?: number;
  nonAmcGps?: number;
  /** Non-AMC GP list: "Done" / "Pending" */
  hotoStatus?: string;
  /** existing-GP / removed-GP lists: In scope / Converted to NP / Closed / Deducted */
  status?: string;
  /** removed-GP list: the source's "Converted to NP & Closed" text */
  remark?: string | null;
  /** HOTO-pending list: area manager (null = not assigned in source) */
  amName?: string | null;
  reason?: string;
  /** HOTO block list: all GP rows in the block, with HOTO dates for completed GPs */
  gpDetails?: { id: string; name: string; code: string; hotoDate: string | null }[];
  /** AMC plan lists (GP-wise plan of the GP sheet) */
  category?: string | null;
  plannedDate?: string | null;
  achDate?: string | null;
  planStatus?: string | null;
  letterStatus?: string | null;
  /** new-GP list (block-wise, Master Block sheet) */
  existingGps?: number | null;
  newGps?: number;
}

export interface KpiListResponse {
  kind: KpiListKind;
  unit: "gp" | "block";
  title: string;
  rule: string;
  week: { id: string; number: number; endDate: string };
  asOf: string;
  /** Unfiltered count – equals the number on the KPI card */
  cardTotal: number;
  /** Count after state / district / block / search */
  total: number;
  /** new-gp-blocks only: rows are blocks; these are the new GPs in them (unfiltered / filtered) */
  cardValueTotal?: number | null;
  valueTotal?: number | null;
  page: number;
  pageSize: number;
  pages: number;
  sort: KpiListSort;
  items: KpiListItem[];
  /** all-blocks only: aggregate totals across the filtered rows (for the mini KPI strip) */
  blockSummary?: {
    totalBlocks: number;
    hotoDoneBlocks: number;
    amcOriginalGps: number;
    incrementalGps: number;
    totalAmcGps: number;
    nonAmcGps: number;
  } | null;
}

/* ---------------------------------------------------------------- AMC conversion: plan vs execution */

export type PlanStatus = "done" | "in progress" | "not started";

export interface AmcMonthCell {
  plan: number | null;
  /** Overall row only: a circle has no plan for this month (Overall = sum of the others) */
  planPartial: boolean;
  /** GPs converted (AMC date in the month, up to the cutoff); null = month not started */
  achieved: number | null;
  achievedPct: number | null;
  gap: number | null;
  cumulativePlan: number | null;
  cumulativeAchieved: number | null;
}

export interface AmcConversionResponse {
  week: ReportingWeek;
  compareWeek: ReportingWeek;
  /** execution is counted up to this date */
  cutoff: string;
  monthLabel: string;
  daysLeft: number;
  planSource: string | null;
  headline: {
    revisedScope: number;
    underAmc: number;
    underAmcPct: number | null;
    monthPlan: number | null;
    monthAchieved: number | null;
    monthAchievedPct: number | null;
    projection: number | null;
    projectionGap: number | null;
    pendingScope: number;
    totalPlan: number | null;
    currentMonthIndex: number | null;
  };
  circles: { id: string; code: string; name: string }[];
  monthly: {
    months: { id: string; label: string; start: string; end: string; status: PlanStatus }[];
    baselineDate: string | null;
    rows: { id: string; code: string; name: string; months: AmcMonthCell[] }[];
    total: { id: string; code: string; name: string; months: AmcMonthCell[] };
  };
  weekly: {
    weeks: { id: string; label: string; start: string; end: string; status: PlanStatus }[];
    rows: { id: string; code: string; name: string; weeks: ReviewWeeklyCell[] }[];
    total: { id: string; code: string; name: string; weeks: ReviewWeeklyCell[] };
  };
  roadmap: ReviewTargetsPage["roadmap"];
  circleCards: NonNullable<ReviewTargetsPage["circleCards"]>;
  definitions: string[];
  warnings: string[];
}

/** GP-wise AMC conversion plan vs achievement (Planned Date / Ach Date of the GP sheet) – counts only. */
export interface AmcPlanCounts {
  id: string;
  code: string;
  name: string;
  planGps: number;
  withoutPlannedDate: number;
  monthTarget: number;
  mtdTarget: number;
  mtdAchieved: number;
  weekTarget: number;
  weekAchieved: number;
  overdue: number;
  /** Letter Status of the achieved GPs (MTD / week): Submitted, Pending, or blank / other text */
  mtdLetterSubmitted: number;
  mtdLetterPending: number;
  mtdLetterNotRecorded: number;
  weekLetterSubmitted: number;
  weekLetterPending: number;
  weekLetterNotRecorded: number;
  mtdAchievedPct: number | null;
  monthAchievedPct: number | null;
  weekAchievedPct: number | null;
}

export interface AmcPlanSummary {
  hasPlan: boolean;
  /** week cutoff: the selected week's end, capped at the last date with data */
  asOf: string;
  /** month KPIs (month target, MTD, overdue) are counted up to this date: the latest data date */
  monthAsOf: string;
  month: { id: string; label: string; start: string; end: string; daysElapsed: number; daysInMonth: number };
  week: { id: string; number: number; label: string; start: string; end: string; complete: boolean };
  /** dates that can be picked (every day with data), newest first */
  dates: string[];
  total: AmcPlanCounts;
  rows: AmcPlanCounts[];
  days: { date: string; planned: number; achieved: number | null; cumulativePlanned: number; cumulativeAchieved: number | null }[];
  categories: { label: string; gps: number }[];
  definitions: string[];
  warnings: string[];
}

export interface AmcPlanCell {
  /** GPs whose Planned Date falls in the period – or, for a month without Planned Dates yet, the targets file */
  target: number;
  /** excel = counted from Planned Date; plan = data/amc_month_targets.json; mixed = Overall of both */
  targetSource: "excel" | "plan" | "mixed";
  /** GPs whose Ach Date falls in the period, up to the data date; null = period not started */
  achieved: number | null;
  achievedPct: number | null;
  /** part of the target whose Planned Date is on or before the data date; null = not started */
  dueTarget: number | null;
  cumulativeTarget: number;
  cumulativeAchieved: number | null;
}

export interface AmcPlanPeriod {
  id: string;
  label: string;
  start: string;
  end: string;
  status: PlanStatus;
  current: boolean;
}

export interface AmcPlanTable {
  rows: { id: string; code: string; name: string; cells: AmcPlanCell[] }[];
  total: { id: string; code: string; name: string; cells: AmcPlanCell[] };
}

/** Month-wise and week-wise GP-wise AMC plan vs achievement (Planned Date / Ach Date) – counts only. */
/** One area manager of a state (AMC Conversion → Monthly / Weekly Plan vs Execution). */
export interface AmcAreaManagerRow {
  name: string;
  /** false for "Not assigned" / "Vacant (no AM)" */
  assigned: boolean;
  /** business areas (BA) of the AM's GPs: Escalation Matrix BA, else the master data's BA */
  businessAreas: string[];
  /** AM e-mail(s) from the Escalation Matrix; masked (sh*****@domain) unless the user is an admin */
  emails: string[];
  blocks: number;
  existingGps: number;
  /** under AMC as of the reporting week's end (same rule as the KPI cards) */
  amcGps: number;
  nonAmcGps: number;
  /** GP-wise plan: Planned Date in the current month / Ach Date from the 1st up to the data date */
  monthTarget: number;
  monthAchieved: number;
  monthAchievedPct: number | null;
  /** GP-wise plan: Planned Date in the selected week / Ach Date in the week up to the data date */
  weekTarget: number;
  weekAchieved: number;
  weekAchievedPct: number | null;
}

export interface AmcAreaManagers {
  circle: { id: string; name: string };
  /** where the AM names come from: the Escalation Matrix upload, else the master data's AM Name */
  amSource: "escalation" | "master";
  amSourceFile: string | null;
  /** the active Escalation Matrix has AM e-mails */
  hasEmails: boolean;
  emailsMasked: boolean;
  month: { id: string; label: string; start: string; end: string; asOf: string };
  week: { id: string; number: number; label: string; start: string; end: string; asOf: string; complete: boolean };
  amcAsOf: string;
  rows: AmcAreaManagerRow[];
  total: AmcAreaManagerRow;
  warnings: string[];
}

export interface AmcPlanTimeline {
  hasPlan: boolean;
  /** weeks are counted up to this date (selected week's end, capped at the data date) */
  asOf: string;
  /** months are counted up to this date (the latest data date) */
  monthAsOf: string;
  targetsSource: string | null;
  monthly: AmcPlanTable & { months: AmcPlanPeriod[] };
  weekly: AmcPlanTable & { weeks: AmcPlanPeriod[] };
  definitions: string[];
  warnings: string[];
}

/* ---------------------------------------------------------------- Field Team & Escalation (Escalation Matrix upload) */

export interface FieldMeta {
  source: { id: number; fileName: string; importedAt: string | null };
  week: { id: string; number: number; label: string };
  asOf: string;
}

/** One step of a GP's escalation chain; phone is masked (98XXXXX144) unless the user is an admin. */
export interface ChainStep {
  role: "frt" | "splicer" | "fe" | "am" | "shq" | "coh" | "cbh";
  label: string;
  name: string | null;
  phone: string | null;
  phoneValid: boolean | null;
}

export interface FieldGp {
  id: string;
  name: string;
  code: string;
  circleId: string;
  circle: string;
  districtId: string | null;
  district: string;
  blockId: string | null;
  block: string;
  chain: ChainStep[];
}

export interface FieldStateSummary {
  id: string;
  code: string;
  name: string;
  gps: number;
  frtTeams: number;
  splicers: number;
  fes: number;
  ams: number;
  shq: string[];
  coh: string[];
  cbh: string[];
  fieldComplete: number;
  fieldCompletePct: number | null;
  escalationComplete: number;
  escalationCompletePct: number | null;
  missingFrt: number;
  missingSplicer: number;
  missingFe: number;
  missingAm: number;
  /** AM column says "Vacant…": open posts (not counted as area managers) and their GPs */
  amVacantPosts: number;
  amVacantGps: number;
  invalidPhones: number;
  gpsPerSplicer: number | null;
  gpsPerFe: number | null;
  downGps: number;
  downWithoutSplicer: number;
  amDiffersFromMaster: number;
}

export interface FieldSummary extends FieldMeta {
  total: FieldStateSummary;
  states: FieldStateSummary[];
  notInMaster: number;
}

export interface FieldPage<T> extends FieldMeta {
  total: number;
  page: number;
  pageSize: number;
  pages: number;
  phonesMasked: boolean;
  items: T[];
}

export type FieldRole = "frt" | "splicer" | "fe" | "am";

export interface FieldWorkloadRow {
  id: string;
  circleId: string;
  circle: string;
  name: string;
  phone: string | null;
  numbers: number;
  gps: number;
  blocks: number;
  amcGps: number;
  availability: number | null;
  gpsAtZero: number;
  gpsBelow90: number;
}

export interface FieldWorkload extends FieldMeta {
  role: FieldRole;
  roleLabel: string;
  people: number;
  unassignedGps: number;
  avgGps: number | null;
  maxGps: number | null;
  phonesMasked: boolean;
  items: FieldWorkloadRow[];
}

/** Team Directory row: one person / FRT team (same state + same name ignoring case, spaces and punctuation). */
export interface FieldPerson {
  id: string;
  circleId: string;
  circle: string;
  name: string;
  /** spellings in the file merged into this person (empty when only one) */
  spellings: string[];
  /** AM column "Vacant…": an open post */
  vacant: boolean;
  phone: string | null;
  /** the phone number is also used under another name (possible data error) */
  phoneShared: boolean;
  districts: { name: string; blocks: string[] }[];
  districtCount: number;
  blockCount: number;
  gps: number;
  amcGps: number;
  availability: number | null;
  gpsAtZero: number;
  frtTeams?: string[];
  fes?: string[];
  splicers?: string[];
  ams?: string[];
}

export interface FieldPeople extends FieldMeta {
  role: FieldRole;
  roleLabel: string;
  /** people counted once (vacant AM posts excluded) */
  count: number;
  vacantPosts: number;
  byState: Record<string, number>;
  /** GPs with nobody of this role in the file */
  gpsWithout: number;
  phonesMasked: boolean;
  items: FieldPerson[];
}

export interface FieldDown extends FieldPage<FieldGp & { availability: number | null; noSplicer: boolean }> {
  mode: "zero" | "below90";
  withoutSplicer: number;
}

export interface FieldGaps extends FieldMeta {
  states: { id: string; name: string }[];
  issues: { id: string; label: string; counts: Record<string, number>; total: number }[];
  issue: string | null;
  total?: number;
  page?: number;
  pageSize?: number;
  pages?: number;
  phonesMasked?: boolean;
  items?: (FieldGp & { masterAm: string | null })[];
}

export interface FieldQuery {
  weekId: string;
  circleId?: string;
  districtId?: string;
  blockId?: string;
  search?: string;
  page?: number;
}

export interface EscalationImportRun {
  id: string;
  fileName: string;
  startedAt: string | null;
  durationSec: number | null;
  status: "PROCESSING" | "SUCCESS" | "FAILED";
  message: string | null;
  rows: number;
  rejected: number;
  isActive: boolean;
}

export interface DashboardApi {
  getMeta(): Promise<MetaResponse>;
  getOverview(p: PeriodParams): Promise<OverviewResponse>;
  getCircleInsights(circleId: string, p: PeriodParams): Promise<CircleInsightsResponse>;
  getBlockInsights(blockId: string, p: PeriodParams): Promise<BlockInsightsResponse>;
  getGpDetail(gpId: string, weekId: string): Promise<GpDetailResponse>;
  listGps(q: GpListQuery): Promise<Paginated<GpSnapshot>>;
  search(query: string): Promise<SearchResult[]>;
  getWeeklyReport(p: ReportParams): Promise<WeeklyReportResponse>;
  /** Management Review (live backend only) – the same payload the PPT deck is built from */
  getManagementReview(p: PeriodParams): Promise<ManagementReviewResponse>;
  getIngestionRuns(): Promise<IngestionRun[]>;
  retryIngestion(runId: string): Promise<{ accepted: boolean; message: string }>;
  getNotifications(weekId: string): Promise<DemoNotification[]>;
  /** GPs / blocks behind a Circle Overview KPI card (live backend only) */
  getKpiList(kind: KpiListKind, q: KpiListQuery): Promise<KpiListResponse>;
  /** AMC conversion plan vs execution (live backend only) */
  getAmcConversion(p: PeriodParams): Promise<AmcConversionResponse>;
  /** GP-wise AMC plan vs achievement of the master data file (live backend only) */
  getAmcPlanSummary(weekId: string): Promise<AmcPlanSummary>;
  getAmcPlanTimeline(weekId: string): Promise<AmcPlanTimeline>;
  getAmcAreaManagers(weekId: string, circleId: string): Promise<AmcAreaManagers>;
  /** Field Team & Escalation (live backend only) */
  getFieldSummary(weekId: string): Promise<FieldSummary>;
  getFieldLookup(q: FieldQuery): Promise<FieldPage<FieldGp & { fieldComplete: boolean }>>;
  getFieldWorkload(role: FieldRole, q: FieldQuery): Promise<FieldWorkload>;
  getFieldPeople(role: FieldRole, q: FieldQuery): Promise<FieldPeople>;
  getFieldDown(mode: "zero" | "below90", q: FieldQuery): Promise<FieldDown>;
  getFieldGaps(issue: string | null, q: FieldQuery): Promise<FieldGaps>;
}

/** Admin-only operations (live backend). The mock implementation explains they are unavailable. */
/* ---------------------------------------------------------------- upload report */

export interface UploadReportGp {
  code: string;
  name: string;
  circle: string;
}

export interface UploadReportListDiff {
  /** false = the previous upload had no report to compare with */
  compared: boolean;
  added: string[];
  removed: string[];
}

/** What changed compared with the previous upload (backend: ingestion/report.py). */
export interface UploadReport {
  runId: string;
  createdAt: string | null;
  fileName: string;
  error?: string;
  previous: { id: string; fileName: string; dataAsOf: string | null } | null;
  dataAsOf: { current: string | null; previous: string | null; newDays: number | null };
  sheets: UploadReportListDiff & { found: string[] };
  columns: UploadReportListDiff & { notUsed: string[]; missingOptional: string[] };
  gps: {
    current: number;
    previous: number | null;
    added: number;
    removed: number;
    addedSample: UploadReportGp[];
    removedSample: UploadReportGp[];
    hotoNew: number;
    amcNew: number;
    hotoDateChanged: number;
    hotoDateChangedSample: (UploadReportGp & { from: string | null; to: string | null })[];
    amcDateChanged: number;
    amcDateChangedSample: (UploadReportGp & { from: string | null; to: string | null })[];
    byCircle: { circle: string; current: number; previous: number | null }[];
  };
  weeks: UploadReportListDiff & { current: string[] };
  issues: { current: Record<"critical" | "warning" | "info", number>; previous: Record<"critical" | "warning" | "info", number> | null };
  notes: string[];
}

export interface AdminApi {
  /** Master data workbook or Escalation Matrix – the backend tells them apart by content (`kind`). */
  uploadWorkbook(file: File): Promise<{ id: string; status: string; fileName: string; kind?: "master" | "escalation" }>;
  getEscalationImports(): Promise<EscalationImportRun[]>;
  getRunIssues(runId: string, params?: { severity?: string; code?: string; page?: number }): Promise<RunIssuesResponse>;
  /** What changed compared with the previous upload */
  getRunReport(runId: string): Promise<UploadReport>;
  getReconciliation(): Promise<ReconciliationResponse>;
  listUsers(): Promise<AppUser[]>;
  createUser(body: UserCreateBody): Promise<AppUser>;
  updateUser(id: number, body: UserUpdateBody): Promise<AppUser>;
  getUserLocations(): Promise<UserLocations>;
  getMailStatus(): Promise<MailStatus>;
  getMailOptions(): Promise<MailOptions>;
  sendTestMail(to: string): Promise<{ ok: boolean; message: string }>;
  listMailTemplates(): Promise<MailTemplateItem[]>;
  createMailTemplate(body: MailTemplateBody): Promise<MailTemplateItem>;
  updateMailTemplate(id: number, body: MailTemplateBody): Promise<MailTemplateItem>;
  resetMailTemplate(id: number): Promise<MailTemplateItem>;
  deleteMailTemplate(id: number): Promise<{ deleted: number }>;
  previewMailTemplate(body: { subject: string; body: string; configId?: number; personId?: string }): Promise<MailPreview>;
  listMailConfigs(): Promise<MailConfigItem[]>;
  createMailConfig(body: MailConfigBody): Promise<MailConfigItem>;
  updateMailConfig(id: number, body: MailConfigBody): Promise<MailConfigItem>;
  setMailConfigEnabled(id: number, enabled: boolean): Promise<MailConfigItem>;
  deleteMailConfig(id: number): Promise<{ deleted: number }>;
  previewMailRecipients(id: number): Promise<MailRecipientPreview>;
  listMailRuns(): Promise<MailRunItem[]>;
}
