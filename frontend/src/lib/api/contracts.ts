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
  /** Days between dataAsOf and today; the dashboard warns above staleAfterDays */
  dataAgeDays?: number;
  staleAfterDays?: number;
  /** Weeks whose availability was recomputed from the daily values (the file's weekly column did not match them) */
  recomputedWeeks?: { id: string; note: string }[];
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
  /** HOTO status of the GP's block (done = at least one GP of the block handed over by the week end); live backend only */
  blockHoto?: { done: boolean; hotoDoneGps: number; totalGps: number };
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

/** Bulk import of dashboard users from an Excel / CSV file (Name + Email columns) */
export interface UserImportItem {
  /** row number in the file, as Excel shows it */
  row: number;
  name: string;
  email: string;
  /** NEW = will be created (preview), CREATED = created, EXISTS = already a user (not changed), SKIPPED = problem in the row */
  status: "NEW" | "CREATED" | "EXISTS" | "SKIPPED";
  reason: string | null;
}

export interface UserImportResult {
  dryRun: boolean;
  fileName: string | null;
  total: number;
  new: number;
  created: number;
  exists: number;
  skipped: number;
  temporaryPassword: string;
  items: UserImportItem[];
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
  /** circles → districts → blocks of the active data (area picker of the extra recipients) */
  locations: UserLocations["circles"];
}

/** A person typed in on a schedule (not in the Escalation Matrix, no account); no areas = every circle. */
export interface MailExtraRecipient {
  email: string;
  name: string | null;
  areas: { level: ScopeLevel; id: string }[];
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
  extraRecipients: MailExtraRecipient[];
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

export type KpiListKind = "gps-above-98" | "gps-at-zero" | "gps-below-90" | "penalty-blocks" | "hoto-gps" | "hoto-blocks" | "existing-gps" | "new-gp-blocks" | "na-gps" | "one-time-up" | "hoto-pending-gps" | "hoto-pending-blocks" | "all-blocks" | "non-amc-gps" | "amc-original-gps" | "incremental-gps" | "amc-gps" | "removed-gps"
  | "amc-plan-month" | "amc-plan-mtd" | "amc-achieved-mtd" | "amc-plan-week" | "amc-achieved-week" | "amc-overdue" | "amc-converted-mtd" | "amc-converted-week";
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
  letterDate?: string | null;
  planStatus?: string | null;
  letterStatus?: string | null;
  approvalStatus?: string | null;
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
  /** "Approval Status" of the achieved GPs (MTD / week). IE accepted includes BSNL accepted (BSNL approves after IE). */
  mtdIeAccepted?: number;
  mtdBsnlAccepted?: number;
  mtdIeRejected?: number;
  mtdIePending?: number;
  weekIeAccepted?: number;
  weekBsnlAccepted?: number;
  weekIeRejected?: number;
  weekIePending?: number;
  /** Part of each figure whose plan category is "5% Incremental" (the rest is "Additional Plan") */
  incMonthTarget?: number;
  incMtdTarget?: number;
  incMtdAchieved?: number;
  incWeekTarget?: number;
  incWeekAchieved?: number;
  mtdAchievedPct: number | null;
  monthAchievedPct: number | null;
  weekAchievedPct: number | null;
  /** Management view – GP Ready = Ach Date (= mtdAchieved / weekAchieved), GP Achieved = AMC Date of the plan GPs, Gap = target − achieved */
  monthReady: number;
  weekReady: number;
  monthConverted: number;
  weekConverted: number;
  incMonthConverted: number;
  incWeekConverted: number;
  monthGap: number;
  weekGap: number;
  monthReadyPct: number | null;
  weekReadyPct: number | null;
  monthConvertedPct: number | null;
  weekConvertedPct: number | null;
  /** Letters of the GP Ready GPs: submitted = letter submission date filled, not submitted = the rest, accepted = AMC Date filled */
  monthReadyLetterSubmitted: number;
  monthReadyLetterNotSubmitted: number;
  monthReadyLetterAccepted: number;
  weekReadyLetterSubmitted: number;
  weekReadyLetterNotSubmitted: number;
  weekReadyLetterAccepted: number;
  /** the same letter split for the 5% Incremental part of the GP Ready GPs */
  incMonthReadyLetterSubmitted: number;
  incMonthReadyLetterNotSubmitted: number;
  incWeekReadyLetterSubmitted: number;
  incWeekReadyLetterNotSubmitted: number;
}

export interface AmcPlanSummary {
  hasPlan: boolean;
  /** the file has an "Approval Status" column with values (false for imports made before it was read) */
  hasApproval?: boolean;
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
  /** GPs whose Planned Date falls in the period (always – never the management plan) */
  target: number;
  /** always "excel" (Planned Date count); "plan" / "mixed" only from an older backend */
  targetSource: "excel" | "plan" | "mixed";
  /** months: the management plan (data/amc_month_targets.json) for reference only – not a target, total or gap */
  planTarget?: number | null;
  /** GPs whose Ach Date falls in the period, up to the data date; null = period not started */
  achieved: number | null;
  achievedPct: number | null;
  /** management view (null = not started): GP Ready = Ach Date (= achieved), GP Achieved = AMC Date, gap = target − converted */
  ready: number | null;
  converted: number | null;
  gap: number | null;
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
  /** GP Achieved = AMC Date of the plan GPs in the month (1st – data date) / week (an older backend: undefined) */
  monthConverted?: number;
  weekConverted?: number;
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

/** Data upload: which file the admin says it is (the server checks the content). */
export type UploadKind = "master" | "escalation";

export interface UploadIssue {
  row: number | null;
  severity: "critical" | "warning" | "info";
  code: string;
  column: string | null;
  gpCode: string | null;
  message: string;
  sheet?: string | null;
}

/** Validation report of a staged upload (step 1 of "preview, then confirm"); nothing is imported yet. */
export interface UploadPreview {
  token: string | null;
  kind: UploadKind;
  kindLabel: string;
  fileName: string;
  size: number;
  sha256: string;
  expiresInMinutes: number;
  canImport: boolean;
  /** first failing layer: file | kind | duplicate | template | structure; ok = can be imported */
  stage: "ok" | "file" | "kind" | "duplicate" | "template" | "structure";
  error: string | null;
  /** stage "template": every difference from the PAGMAS template (first 500), with sheet / row / column */
  templateErrors?: { sheet: string; row: number | null; column: string | null; severity: string; message: string }[];
  templateErrorCount?: number;
  counts?: { rows: number; accepted: number; rejected: number; critical: number; warning: number; info: number };
  facts?: { label: string; value: string }[];
  columns?: { missingOptional: string[]; unknown: string[]; mapProblems: string[] };
  crossCheck?: { state: string; metric: string; reported: number; computed: number; difference: number; match: boolean }[];
  issues?: UploadIssue[];
  issueSummary?: { code: string; severity: string; count: number }[];
}

/** Field Team & Escalation → Escalation Sheet */
export interface EscalationSheetColumn {
  key: string;
  label: string;
  kind: "text" | "phone" | "email";
  editable: boolean;
  maxLength: number;
}
export interface EscalationSheetRow {
  gpCode: string;
  values: Record<string, string | null>;
  inMaster?: boolean;
}
export interface EscalationSheet {
  source: { importId: number; fileName: string; importedAt: string | null; edits: number; lastEditAt: string | null };
  columns: EscalationSheetColumn[];
  rows: EscalationSheetRow[];
  total: number;
  page: number;
  pageSize: number;
  canEdit: boolean;
  phonesMasked: boolean;
}
export interface EscalationSheetQuery {
  circleId?: string;
  districtId?: string;
  blockId?: string;
  search?: string;
  page?: number;
  pageSize?: number;
}
export interface EscalationCellChange {
  gpCode: string;
  field: string;
  old: string | null;
  new: string | null;
}
export interface EscalationCellProblem {
  gpCode: string;
  field: string;
  message: string;
  conflict?: boolean;
  current?: string | null;
}
export interface EscalationEditItem {
  gpCode: string;
  field: string;
  label: string;
  old: string | null;
  new: string | null;
  by: string;
  at: string | null;
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
  /** Optional columns of the matrix were not found (left empty) -> offer "Check columns" */
  columnsMissing?: boolean;
}

/** Column mapper (Data Operations): what the importer recognises in a workbook. */
export type ColumnSectionKey = "gp" | "masterBlock" | "escalation";
export interface ColumnFit {
  kind: "date" | "number" | "phone" | "email";
  pct: number;
  warning: boolean;
}
export interface ColumnCheckField {
  field: string;
  label: string;
  required: boolean;
  kind: ColumnFit["kind"] | null;
  acceptedNames: string[];
  status: "found" | "missing";
  header?: string;
  samples?: string[];
  fit?: ColumnFit | null;
  duplicates?: string[];
  suggestion?: string | null;
  similarity?: number | null;
}
export interface ColumnCheckSection {
  key: ColumnSectionKey;
  label: string;
  sheet: string | null;
  sheetResolved: boolean;
  sheetSuggestion: string | null;
  headerFound: boolean;
  headerRow?: number;
  headerExact?: boolean;
  fields: ColumnCheckField[];
  columns: { header: string; samples: string[]; fit: Record<string, ColumnFit | null> }[];
}
export interface ColumnCheck {
  kind: "master" | "escalation" | null;
  sheets: string[];
  sheetMap: { key: "gp" | "masterBlock" | "om"; label: string; acceptedNames: string[]; sheet: string | null; suggestion: string | null }[];
  sections: ColumnCheckSection[];
  ready: boolean;
  missingRequired: number;
  missingOptional: number;
  problems: string[];
}
export interface ColumnMapName {
  section: ColumnSectionKey | "sheets";
  sectionLabel: string;
  field: string;
  fieldLabel: string;
  name: string;
}

/** Rows (month YYYY-MM or week W-41) → state → GPs; null = no value */
export type PlanGrid = Record<string, Record<string, number | null>>;
export interface PlanFile {
  name: string;
  label: string;
  exists: boolean;
  updatedAt: string | null;
  sections: { key: string; label: string; rowKind: "month" | "week" }[];
  fields: { key: string; label: string; pattern: string }[];
  data: Record<string, unknown>;
  /** Why the dashboard cannot read the saved file (null = fine) */
  problem: string | null;
}
export interface PlanFileVersion {
  id: string;
  savedAt: string | null;
  savedBy: string | null;
  note: string | null;
  content: Record<string, unknown>;
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
  /** Escalation Sheet: the active Escalation Matrix as an (admin-editable) sheet */
  getEscalationSheet(q: EscalationSheetQuery): Promise<EscalationSheet>;
  saveEscalationSheet(importId: number, changes: EscalationCellChange[]): Promise<{ saved: number; rows: EscalationSheetRow[] }>;
  replaceInEscalationSheet(body: {
    importId: number;
    field: string;
    find: string;
    replace: string;
    circle?: string;
    district?: string;
    block?: string;
    dryRun: boolean;
  }): Promise<{ matches: number; saved: number; sample: string[] }>;
  getEscalationSheetEdits(gpCode?: string): Promise<{ importId: number; items: EscalationEditItem[] }>;
  escalationSheetExportUrl(q: EscalationSheetQuery): string;
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
  /** Master data workbook or Escalation Matrix – the backend tells them apart by content (`kind`).
   *  `onProgress` gets the share of the file sent so far (0–1). */
  uploadWorkbook(file: File, onProgress?: (fraction: number) => void): Promise<{ id: string; status: string; fileName: string; kind?: "master" | "escalation" }>;
  /** Step 1: stage + validate the file completely (nothing is imported) */
  previewUpload(file: File, kind: UploadKind, onProgress?: (fraction: number) => void): Promise<UploadPreview>;
  /** Step 2: import the staged file of a preview */
  confirmUpload(token: string): Promise<{ id: string; status: string; fileName: string; kind: UploadKind }>;
  discardUpload(token: string): Promise<{ discarded: boolean }>;
  getEscalationImports(): Promise<EscalationImportRun[]>;
  /** Column mapper: check a workbook (nothing is imported or kept), a stored run or an Escalation Matrix import */
  checkColumns(source: { file: File } | { runId: string } | { escalationId: string }): Promise<ColumnCheck>;
  getColumnMap(): Promise<{ names: ColumnMapName[]; problems: string[] }>;
  addColumnNames(body: { columns: { section: ColumnSectionKey; field: string; name: string }[]; sheets: { key: string; name: string }[] }): Promise<{ added: string[]; names: ColumnMapName[] }>;
  removeColumnName(body: { section: string; field: string; name: string }): Promise<{ removed: string; names: ColumnMapName[] }>;
  listPlanFiles(): Promise<PlanFile[]>;
  savePlanFile(name: string, data: Record<string, unknown>): Promise<PlanFile>;
  getPlanFileHistory(name: string): Promise<PlanFileVersion[]>;
  /** Import a finished run's / Escalation Matrix's stored file again with the current column names */
  reprocessRun(runId: string): Promise<{ accepted: boolean; message: string }>;
  reprocessEscalation(id: string): Promise<{ accepted: boolean; message: string }>;
  getRunIssues(runId: string, params?: { severity?: string; code?: string; page?: number }): Promise<RunIssuesResponse>;
  /** Excel download of a run's issues (same filters) */
  runIssuesXlsxUrl(runId: string, params?: { severity?: string; code?: string }): string;
  /** What changed compared with the previous upload */
  getRunReport(runId: string): Promise<UploadReport>;
  getReconciliation(): Promise<ReconciliationResponse>;
  listUsers(): Promise<AppUser[]>;
  createUser(body: UserCreateBody): Promise<AppUser>;
  updateUser(id: number, body: UserUpdateBody): Promise<AppUser>;
  /** dryRun = preview only; otherwise creates the new Viewer accounts with the temporary password */
  importUsers(file: File, dryRun: boolean): Promise<UserImportResult>;
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

/* ---------------------------------------------------------------- Ticket Management (backend: app/tickets) */

export type TicketStatus = "OPEN" | "IN_PROGRESS" | "PENDING_REVIEW" | "CHANGES_REQUESTED" | "CLOSED";
export type TicketPriority = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
/** all = every ticket (admins only); mine = tickets assigned to the signed-in user */
export type TicketScope = "all" | "mine";

export interface TicketKpis {
  total: number;
  /** OPEN + IN_PROGRESS */
  open: number;
  /** PENDING_REVIEW */
  pending: number;
  closed: number;
  /** IN_PROGRESS */
  working: number;
  byStatus: Record<TicketStatus, number>;
}

export interface TicketSummary {
  id: number;
  code: string;
  subject: string;
  priority: TicketPriority;
  status: TicketStatus;
  assignee: { id: number | null; name: string; email: string };
  createdBy: { id: number | null; name: string };
  createdAt: string;
  updatedAt: string;
  submittedAt: string | null;
  closedAt: string | null;
  /** Circle / State chosen when the ticket was generated (null for older tickets) */
  circle: string | null;
  /** list rows only: GP-wise task Area Manager / week and number of recipients */
  areaManager?: string | null;
  week?: string | null;
  recipientCount?: number;
}

export type TicketRecipientRole = "CBH" | "SME" | "COH" | "AM" | "FE" | "USER" | "OTHER";

export interface TicketRecipient {
  id: number;
  role: TicketRecipientRole;
  name: string;
  email: string;
  /** dashboard = an active account has this e-mail (sees the ticket); email = e-mail only */
  access: "dashboard" | "email";
  canWork: boolean;
  /** the Area Manager's own GP workbook goes with the e-mail */
  workbook: boolean;
  emailStatus: "NONE" | "PENDING" | "SENT" | "FAILED";
  /** admins only */
  emailError: string | null;
  emailedAt: string | null;
  /** FE only: parent Area Manager in the Escalation Matrix */
  areaManager?: string | null;
}

export interface DirectoryEmail {
  email: string;
  user: { id: number; name: string; role: string } | null;
}

export interface DirectoryPerson {
  name: string;
  gps: number;
  emails: DirectoryEmail[];
  weekGps?: number;
  pendingGps?: number;
  businessAreas?: string[];
  /** Area Manager: the week's task GPs without a Field Engineer in the Escalation Matrix */
  unmappedFeGps?: number;
}

/** A Field Engineer of the circle = one Escalation Matrix mapping (Area Manager, FE name, FE e-mail of the GP rows) */
export interface DirectoryFe {
  name: string;
  /** parent Area Manager */
  am: string;
  /** FE e-mail of the matrix rows that decides the FE's GPs (null = rows without an FE e-mail) */
  mappedEmail: string | null;
  emails: DirectoryEmail[];
  gps: number;
  weekGps: number;
  pendingGps: number;
}

export interface TicketDirectory {
  circles: { name: string; gps: number }[];
  circle: string | null;
  week: string;
  /** escalation = Escalation Matrix upload; master = no matrix (AM names from the master data, no CBH / SME) */
  source: "escalation" | "master";
  cbh: DirectoryPerson[];
  sme: DirectoryPerson[];
  coh?: DirectoryPerson[];
  am: DirectoryPerson[];
  fe: DirectoryFe[];
}

export interface TicketCreateBody {
  assigneeId?: number | null;
  subject: string;
  description: string;
  priority: TicketPriority;
  task?: { amName?: string; week: string };
  circle?: string;
  /** FE: `am` + `feEmail` name the matrix mapping of the FE's GPs; `email` is where the ticket e-mail goes */
  recipients?: { role: "CBH" | "SME" | "COH" | "AM" | "FE" | "OTHER"; name: string; email: string; am?: string; feEmail?: string | null }[];
  sendEmail?: boolean;
}

export interface TicketAttachmentItem {
  id: number;
  fileName: string;
  contentType: string;
  size: number;
  uploadedAt: string;
  /** PDF / JPG / PNG open in the browser */
  previewable: boolean;
}

export interface TicketSubmissionItem {
  id: number;
  version: number;
  description: string;
  submittedAt: string;
  submittedBy: string;
  review: "PENDING" | "ACCEPTED" | "CHANGES_REQUESTED";
  reviewedBy: string | null;
  reviewedAt: string | null;
  reviewComment: string | null;
  attachments: TicketAttachmentItem[];
}

export interface TicketDetail extends TicketSummary {
  description: string;
  startedAt: string | null;
  closedBy: { id: number | null; name: string | null } | null;
  assigneeActive: boolean;
  assigneeRole: string | null;
  /** Latest admin feedback while the ticket is Changes Requested */
  feedback: { comment: string | null; by: string | null; at: string | null; version: number } | null;
  /** Newest first */
  submissions: TicketSubmissionItem[];
  events: { at: string; actor: string; action: string; from: TicketStatus | null; to: TicketStatus | null; note: string | null }[];
  /** What the signed-in user may do now (checked again by the backend) */
  /** GP-wise weekly task (null = a plain ticket) */
  task: TicketTask | null;
  /** CBH / SME / Area Manager / other users the ticket was sent to */
  recipients: TicketRecipient[];
  /** the signed-in user's role on this ticket (null = admin not on it) */
  myRole: TicketRecipientRole | "ASSIGNEE" | null;
  /** progress = daily GP progress (assigned Area Manager); close = an admin may close now; email = send / retry e-mails */
  /** reviewAs = review steps of the GPs this user may do (AM approve / return, SME forward, COH letter / AMC; admins: all) */
  can: { start: boolean; submit: boolean; review: boolean; progress: boolean; close: boolean; email: boolean; share?: boolean; reviewAs?: GpReviewRole[] };
}

export interface TicketTaskGp {
  id: number;
  gpCode: string;
  gpName: string;
  circle: string;
  businessArea: string | null;
  district: string | null;
  block: string | null;
  /** WEEK = Planned Date in the week · PENDING = planned earlier, not achieved yet · ADDED = added by the FE / AM */
  kind: "WEEK" | "PENDING" | "ADDED";
  category: string | null;
  plannedDate: string | null;
  readyDate: string | null;
  amcDate: string | null;
  target: number;
  /** achieved in the master data (AMC Date) when the task was created */
  baseAchieved: number;
  /** achieved by the Area Manager's daily submissions */
  reported: number;
  cumulative: number;
  gap: number;
  remarks: string | null;
  /** DONE once the cumulative achievement reached the target */
  status: GpStatus;
  /** proof documents of this GP (all daily submissions) */
  files: TicketProofFile[];
  /** latest daily submission with a line for this GP */
  lastUpdated: string | null;
  /** who submitted that line (Area Manager / FE) */
  lastUpdatedBy?: string | null;
  /** Field Engineer of the GP in the Escalation Matrix at creation (null = not mapped) */
  feName?: string | null;
  /** current classification chosen in the daily progress (null = not classified yet) */
  gpCategory?: GpCategory | null;
  /** review chain: null = with the FE; locked = approved by the Area Manager (no more daily changes) */
  review?: GpReviewState | null;
  reviewLabel?: string | null;
  reviewAt?: string | null;
  locked?: boolean;
  letterDate?: string | null;
  amcOn?: string | null;
  addedBy?: string | null;
  /** GP corrections, additions and review steps (oldest first) */
  trail?: GpReviewStep[];
  /** latest Non-Doable case of the GP (open = still in the Non-Doable workflow) */
  ndCase?: { id: number; ref: string; status: NdStatus; label: string; revisit: NdRevisit | null; open: boolean } | null;
}

export type GpReviewRole = "AM" | "SME" | "COH";
export type GpReviewState = "RETURNED" | "AM_APPROVED" | "SME_FORWARDED" | "LETTER_SUBMITTED" | "AMC_CONVERTED" | "ND_APPROVED";
export type GpReviewAction = "AM_APPROVE" | "AM_RETURN" | "SME_FORWARD" | "COH_LETTER" | "COH_AMC";
export interface GpReviewStep {
  role: "FE" | "AM" | "SME" | "COH" | "ADMIN";
  action: GpReviewAction | "EDIT" | "ADD";
  label: string;
  category: GpCategory | null;
  date: string | null;
  remark: string | null;
  by: string | null;
  at: string | null;
}

export interface ReviewContacts {
  circle: string | null;
  role: "SME" | "COH";
  /** Escalation Matrix people of the circle */
  people: { name: string; emails: { email: string; account: boolean; onTicket: boolean }[] }[];
  /** already on the ticket with this role, not in the matrix */
  onTicket: { name: string; email: string; account: boolean }[];
}

/** A GP the FE / Area Manager adds to the ticket (target 1; details from the master data when the code is in it) */
export interface NewTaskGp {
  gpCode: string;
  gpName?: string;
  block?: string;
  category?: "A" | "C" | "D";
  remark?: string;
}

export type GpStatus = "DONE" | "PENDING";
/** GP classification of the daily progress: A Rectification Done · B Ready for Letter Submitted · C Revisit Required ·
 * D Non-Doable – Proposed · E Letter Submission Done (the only one counted as achieved) */
export type GpCategory = "A" | "B" | "C" | "D" | "E";

export interface TicketProofFile {
  id: number;
  fileName: string;
  contentType: string;
  size: number;
  uploadedAt: string | null;
  previewable: boolean;
  /** monitoring rows: ticket the file was uploaded in */
  ticket?: string | null;
}

export interface GpMonitorFilters {
  circle?: string;
  areaManager?: string;
  /** Field Engineer name, or "FE not mapped" */
  fe?: string;
  block?: string;
  week?: string;
  ticket?: string;
  gpCode?: string;
  gpName?: string;
  search?: string;
  dateFrom?: string;
  dateTo?: string;
}

export interface GpMonitorKpis {
  total: number;
  done: number;
  pending: number;
  donePct: number | null;
  pendingPct: number | null;
  withoutProof: { done: number; pending: number };
  /** current category of each GP (each GP once) – the five category KPIs */
  categories: Record<GpCategory, number>;
  /** of those, GPs with at least one proof document */
  categoryWithDocument: Record<GpCategory, number>;
  notClassified: number;
}

export interface GpMonitorOptions {
  circles: string[];
  areaManagers: string[];
  fieldEngineers?: string[];
  blocks: string[];
  weeks: string[];
  tickets: string[];
}

/** One GP (each GP code once across all task tickets) */
export interface GpMonitorRow {
  gpCode: string;
  gpName: string;
  circle: string;
  district: string | null;
  block: string | null;
  businessArea: string | null;
  areaManager: string;
  fieldEngineer?: string | null;
  ticketId: number;
  ticket: string;
  ticketStatus: TicketStatus;
  week: string;
  weekStart: string;
  weekEnd: string;
  kind: "WEEK" | "PENDING";
  plannedDate: string | null;
  status: GpStatus;
  target: number;
  achieved: number;
  gap: number;
  completedAt: string | null;
  completedBy: string | null;
  lastUpdated: string | null;
  remarks: string | null;
  files: TicketProofFile[];
  tickets: string[];
  /** current category (latest chosen in any of its tickets), when and in which ticket */
  gpCategory: GpCategory | null;
  categoryAt: string | null;
  categoryTicket: string | null;
}

/** FE-wise Done / Pending of the filtered GPs */
export interface GpMonitorFeRow {
  areaManager: string;
  fieldEngineer: string;
  mapped: boolean;
  total: number;
  done: number;
  pending: number;
  withoutProof: number;
  donePct: number | null;
  categories: Record<GpCategory, number>;
  notClassified: number;
}

export type GpMonitorSort = "circle" | "areaManager" | "fe" | "gpCode" | "gpName" | "block" | "target" | "achieved" | "gap" | "date" | "ticket" | "week" | "category";

export interface GpMonitorPage {
  status: GpStatus | null;
  category: GpCategory | null;
  items: GpMonitorRow[];
  total: number;
  page: number;
  pageSize: number;
  kpis: GpMonitorKpis;
  options: GpMonitorOptions;
}

export interface GpMonitorDetail extends GpMonitorRow {
  ticketRows: { ticketId: number; ticket: string; ticketStatus: TicketStatus; week: string; weekStart: string; weekEnd: string; areaManager: string; kind: "WEEK" | "PENDING"; target: number; achieved: number; gap: number; status: GpStatus; gpCategory: GpCategory | null }[];
  history: { at: string | null; ticket: string; week: string; by: string; achievedToday: number; status: GpStatus; gpCategory?: GpCategory | null; remark: string | null; files: TicketProofFile[]; source: "progress" | "master" }[];
}

/** FE-wise allocation and progress of a task (name null = GPs without an FE in the Escalation Matrix) */
export interface TicketTaskFe {
  name: string | null;
  email: string | null;
  gps: number;
  target: number;
  achieved: number;
  gap: number;
  doneGps: number;
  pendingGps: number;
  proofFiles: number;
  lastUpdated: string | null;
  /** the FE is a recipient of this ticket */
  recipient: boolean;
  /** current status (A–E) of the FE's GPs */
  categories?: Record<GpCategory, number>;
  notClassified?: number;
  /** review chain: approved (or further) / returned by the Area Manager / classified A or D and waiting for the AM */
  approvedGps?: number;
  returnedGps?: number;
  awaitingGps?: number;
  addedGps?: number;
}

export interface TicketTask {
  areaManager: string;
  amEmail: string | null;
  /** a Field Engineer's view: only their GPs (null = the whole task) */
  scope?: { fieldEngineer: string; email: string | null } | null;
  /** FE-wise split (empty in a Field Engineer's view) */
  fes?: TicketTaskFe[];
  circle: string | null;
  cbhName: string | null;
  week: { id: string; start: string; end: string };
  dataAsOf: string;
  sourceFile: string;
  totals: { gps: number; target: number; achieved: number; gap: number; pct: number | null; weekGps: number; pendingGps: number; doneGps: number; openGps: number; proofFiles: number; categories?: Record<GpCategory, number>; notClassified?: number;
    addedGps?: number; review?: { awaiting: number; returned: number; amApproved: number; smeForwarded: number; letterSubmitted: number; amcConverted: number; ndOpen?: number; ndApproved?: number } };
  blocks: { block: string; gps: number; target: number; achieved: number; gap: number }[];
  gps: TicketTaskGp[];
  latestSubmission: string | null;
  history: { id: number; submittedAt: string; submittedBy: string; note: string | null; lines: { taskGpId: number; gpCode: string | null; gpName: string | null; block: string | null; achievedToday: number; cumulative: number; gap: number; remark: string | null; status: GpStatus; gpCategory?: GpCategory | null; files: TicketProofFile[] }[] }[];
}

export interface TaskAreaManager {
  name: string;
  emails: string[];
  circles: string[];
  businessAreas: string[];
  gps: number;
  weekGps: number;
  pendingGps: number;
  /** dashboard user whose e-mail is the Area Manager's e-mail (null = no account yet) */
  user: { id: number; name: string; email: string } | null;
}

export interface TaskPreviewRow {
  sort: number;
  gpCode: string;
  gpName: string;
  circle: string;
  businessArea: string | null;
  district: string | null;
  block: string | null;
  kind: "WEEK" | "PENDING";
  category: string | null;
  plannedDate: string | null;
  readyDate: string | null;
  amcDate: string | null;
  target: number;
  achieved: number;
  gap: number;
  feName?: string | null;
  feEmail?: string | null;
}

export interface SharePerson {
  name: string;
  emails: { email: string; account: boolean; onTicket: boolean }[];
}
export interface ShareContacts {
  circle: string | null;
  cbh: SharePerson[];
  sme: SharePerson[];
}

/** Counts of task GPs: ready = Ach Date filled, amc = AMC Date filled; toReady = gps − ready, toConvert = gps − amc */
export interface TaskFigure {
  gps: number;
  ready: number;
  amc: number;
  toReady: number;
  toConvert: number;
}

export interface TaskFigures {
  /** Planned Date in the selected week (Weekly Target) */
  week: TaskFigure;
  /** backlog: planned before the week, not converted before it – information only, NOT in the target / ticket */
  backlog: TaskFigure;
  /** the ticket's GPs (= the week's target) */
  total: TaskFigure;
}

/** Generate Ticket preview: the Area Manager's and each mapped FE's target and achievement for the week */
export interface TaskBreakdown {
  week: { id: string; number: number; start: string; end: string; asOf: string };
  readyAsOf: string;
  amcAsOf: string;
  am: TaskFigures & { name: string };
  fes: (TaskFigures & { name: string; email: string | null; emails: string[] })[];
  /** GPs without an FE in the Escalation Matrix (null = none) */
  unmapped: TaskFigures | null;
  /** the same AM on AMC Conversion → area manager-wise table (Ach / AMC Date inside the week) */
  page: { weekTarget: number; weekReady: number; weekConverted: number } | null;
  definitions: string[];
}

export interface TicketListQuery {
  scope: TicketScope;
  search?: string;
  status?: TicketStatus;
  priority?: TicketPriority;
  dateFrom?: string;
  dateTo?: string;
  circle?: string;
  areaManager?: string;
  week?: string;
  /** GP code or GP name */
  gp?: string;
  progressDate?: string;
  page?: number;
  pageSize?: number;
}

export interface TicketPage {
  items: TicketSummary[];
  total: number;
  page: number;
  pageSize: number;
}

export interface TicketAssignee {
  id: number;
  name: string;
  email: string;
  role: string;
}

export interface TicketNotificationItem {
  id: number;
  ticketId: number;
  kind: "ASSIGNED" | "SUBMITTED" | "CHANGES_REQUESTED" | "CLOSED" | "PROGRESS" | "REVIEW" | "NONDOABLE";
  title: string;
  body: string;
  createdAt: string;
  read: boolean;
  href: string;
}

export interface TicketApi {
  getKpis(scope: TicketScope): Promise<TicketKpis>;
  list(q: TicketListQuery): Promise<TicketPage>;
  get(id: number): Promise<TicketDetail>;
  /** Admin: active users a ticket can be assigned to */
  listAssignees(): Promise<TicketAssignee[]>;
  /** Several tickets are created for a GP-wise task with several Area Managers (one each) */
  create(body: TicketCreateBody): Promise<TicketSummary & { tickets: TicketSummary[]; emailQueued: number }>;
  /** Circle-wise CBH / SME / Area Managers from the database */
  getDirectory(circle: string | null, week?: string): Promise<TicketDirectory>;
  /** Admin list filters that occur in tickets */
  getFilterOptions(): Promise<{ circles: string[]; areaManagers: string[]; weeks: string[] }>;
  /** Send / retry the e-mail of one recipient */
  resendEmail(id: number, recipientId: number): Promise<TicketDetail>;
  /** GP-wise task: Area Managers of the week (with the matching dashboard user) and the GPs of one of them */
  getTaskAreaManagers(week: string): Promise<{ week: { id: string; label: string; start: string; end: string }; source: string; areaManagers: TaskAreaManager[] }>;
  getTaskPreview(am: string, week: string, circle?: string): Promise<{ rows: TaskPreviewRow[]; dataAsOf: string; emails: string[]; summary?: TaskBreakdown }>;
  /** Daily progress of the assigned Area Manager (each submission is kept) */
  submitProgress(id: number, items: { taskGpId: number; achievedToday: number; remark?: string | null }[], note?: string): Promise<TicketDetail>;
  /** Daily progress with Done / Pending per GP and proof documents per GP (upload progress 0–1) */
  submitProgressForm(
    id: number,
    items: { taskGpId: number; status?: GpStatus; category?: GpCategory; remark?: string | null; gpName?: string; block?: string | null }[],
    note: string | undefined,
    proofs: { taskGpId: number; file: File }[],
    onProgress?: (fraction: number) => void,
    newGps?: NewTaskGp[],
  ): Promise<TicketDetail>;
  /** Review step for GPs of a task ticket (AM approve / return, SME forward, COH letter / AMC) */
  reviewGps(id: number, body: { taskGpIds: number[]; action: GpReviewAction; remark?: string; category?: "B"; date?: string; to?: { name?: string; email: string }[] }): Promise<TicketDetail>;
  /** SME (for the Area Manager's approval) / COH (for the SME's forward) of the ticket's circle */
  getReviewContacts(id: number, role: "SME" | "COH"): Promise<ReviewContacts>;
  /** Same-origin URL of a GP proof document (download, or inline preview for PDF / images) */
  progressFileUrl(id: number, inline?: boolean): string;
  /** Admin: Done / Pending GPs of the GP-wise tasks (each GP once) */
  /** basis "category": the date filter = the day the category was chosen (as in the category tables) */
  getGpMonitorSummary(f: GpMonitorFilters, basis?: "status" | "category"): Promise<GpMonitorKpis & { options: GpMonitorOptions; byFe?: GpMonitorFeRow[] }>;
  /** GPs of one status (Done / Pending) or of one current category (A–E) */
  listGpMonitor(q: GpMonitorFilters & { status?: GpStatus; category?: GpCategory; sort?: GpMonitorSort; desc?: boolean; page?: number; pageSize?: number }): Promise<GpMonitorPage>;
  getGpMonitorDetail(gpCode: string): Promise<GpMonitorDetail>;
  /** assignment = the original generated workbook; progress = the latest report */
  taskWorkbookUrl(id: number, kind: "assignment" | "progress"): string;
  start(id: number): Promise<TicketDetail>;
  /** Work submission (description + files) with upload progress (0–1) */
  submit(id: number, description: string, files: File[], onProgress?: (fraction: number) => void): Promise<TicketDetail>;
  close(id: number, comment?: string): Promise<TicketDetail>;
  /** admin only: soft delete (the ticket leaves every list; its records stay as history) */
  remove(id: number, reason?: string): Promise<{ deleted: boolean; id: number; code: string }>;
  /** Area Manager: CBH / SME of the ticket's circle (Escalation Matrix) to share the ticket with */
  getShareContacts(id: number): Promise<ShareContacts>;
  /** Area Manager -> CBH / SME: latest GP sheet + remark by e-mail (read-only access with an account) */
  share(id: number, recipients: { role: "CBH" | "SME"; name: string; email: string }[], remark: string): Promise<TicketDetail & { emailQueued: number }>;
  requestChanges(id: number, comment: string): Promise<TicketDetail>;
  getNotifications(): Promise<{ unread: number; items: TicketNotificationItem[] }>;
  markNotificationsRead(): Promise<{ updated: number }>;
  /** Same-origin URL of an attachment (download, or inline preview for PDF / images) */
  attachmentUrl(id: number, inline?: boolean): string;
}

// ---------------------------------------------------------------- Non-Doable GP exception workflow (backend: app/tickets/nondoable.py)
// FE → AM → SME → COH → Corporate Team – MGG

export type NdStatus =
  | "PROPOSED"
  | "E1_DONE"
  | "PENDING_AM"
  | "RETURNED_FE"
  | "PENDING_SME"
  | "RETURNED_AM"
  | "RETURNED_SME"
  | "PENDING_COH"
  | "PENDING_MGG"
  | "APPROVED"
  | "REJECTED"
  | "WITHDRAWN";
export type NdRevisit = "COORDINATION" | "FRT_VISIT" | "FRT_UPDATED" | "REVIEWED";
export type NdRole = "FE" | "AM" | "SME" | "COH" | "MGG";
export type NdAction = "AM_FORWARD" | "AM_RETURN" | "SME_RECOMMEND" | "SME_RETURN" | "COH_FORWARD" | "COH_RETURN" | "MGG_APPROVE" | "MGG_REJECT" | "WITHDRAW";

export interface NdCaseRow {
  id: number;
  ref: string;
  ticketId: number;
  ticketCode: string | null;
  ticketStatus: TicketStatus | null;
  gpId: number;
  gpCode: string;
  gpName: string | null;
  block: string | null;
  circle: string | null;
  district: string | null;
  fe: string | null;
  round: number;
  status: NdStatus;
  statusLabel: string;
  revisit: NdRevisit | null;
  revisitLabel: string | null;
  physical: "PENDING" | "SUBMITTED";
  evidence: "NONE" | "SUBMITTED";
  approval: "NOT_SUBMITTED" | "IN_REVIEW" | "RETURNED" | "APPROVED" | "REJECTED" | "WITHDRAWN";
  /** FE / AM / SME / COH / "Corporate Team – MGG" (null = nobody, the case is decided) */
  pendingWith: string | null;
  /** waiting for an action of the signed-in user */
  mine: boolean;
  roles: NdRole[];
  createdAt: string | null;
  updatedAt: string | null;
  decision: "APPROVED" | "REJECTED" | null;
}

export interface NdFile {
  id: number;
  kind: "EVIDENCE" | "PHOTO";
  fileName: string;
  contentType: string;
  size: number;
  uploadedAt: string | null;
  uploadedBy: string;
  previewable: boolean;
}

export interface NdRecord {
  id: number;
  kind: "VERIFICATION" | "JUSTIFICATION" | "REVISIT_COORDINATION" | "REVISIT_VISIT";
  visitDate: string | null;
  location: string | null;
  visitorName: string | null;
  findings: string | null;
  reason: string | null;
  remarks: string | null;
  justification: string | null;
  frtTeam: string | null;
  frtVisit: string | null;
  outcome: "A" | "C" | "D" | null;
  by: string;
  at: string | null;
  files: NdFile[];
}

export interface NdEvent {
  id: number;
  stage: string;
  action: string;
  label: string;
  role: string;
  roleLabel: string;
  from: string | null;
  fromLabel: string | null;
  to: string;
  toLabel: string | null;
  remark: string | null;
  recommendation: string | null;
  reason: string | null;
  decision: string | null;
  recordId: number | null;
  by: string;
  at: string | null;
}

export interface NdCaseDetail {
  case: NdCaseRow & {
    physicalLabel: string;
    evidenceLabel: string;
    approvalLabel: string;
    feEmail: string | null;
    createdBy: string;
    decidedBy: string | null;
    decidedAt: string | null;
    decisionRemark: string | null;
  };
  ticket: { id: number; code: string; subject: string; status: TicketStatus; circle: string | null; areaManager: string | null; week: string | null };
  gp: { id: number; gpCode: string; gpName: string; block: string | null; district: string | null; circle: string; category: GpCategory | null; review: GpReviewState | null; target: number; remarks: string | null };
  tracker: { stage: string; label: string; state: "done" | "current" | "returned" | "pending" | "rejected" | "skipped"; by: string | null; at: string | null }[];
  records: NdRecord[];
  history: NdEvent[];
  otherRounds: { id: number; ref: string; round: number; status: NdStatus; statusLabel: string }[];
  can: { verify: boolean; justify: boolean; withdraw: boolean; revisitCoordination: boolean; revisitVisit: boolean; actions: NdAction[] };
  mggMembers: number;
}

export interface NdSummary {
  roles: NdRole[];
  isAdmin: boolean;
  isMgg: boolean;
  kpis: Partial<Record<NdRole, Record<string, number>>>;
}

export interface NdMggMember {
  userId: number;
  name: string;
  email: string;
  active: boolean;
  addedBy: string;
  addedAt: string | null;
}

export type NdFormKind = "verification" | "justification" | "revisit";

export interface NonDoableApi {
  getSummary(): Promise<NdSummary>;
  listCases(q: { status?: string; q?: string; mine?: boolean; ticket?: number; page?: number; size?: number }): Promise<{ total: number; page: number; size: number; items: NdCaseRow[] }>;
  getCase(id: number): Promise<NdCaseDetail>;
  getContacts(id: number, role: "SME" | "COH"): Promise<ReviewContacts>;
  /** E1 / E2 / revisit forms with evidence and site photographs (upload progress 0–1) */
  submitForm(
    id: number,
    kind: NdFormKind,
    data: Record<string, string>,
    files: { evidence: File[]; photos: File[] },
    revisit?: "COORDINATION" | "VISIT",
    onProgress?: (fraction: number) => void,
  ): Promise<NdCaseDetail>;
  act(id: number, body: { action: NdAction; remark?: string; reason?: string; target?: "FE" | "AM" | "SME"; to?: { name?: string; email: string }[] }): Promise<NdCaseDetail>;
  fileUrl(id: number, inline?: boolean): string;
  /** admin: Corporate Team – MGG members (existing accounts only) */
  listMgg(): Promise<{ members: NdMggMember[] }>;
  addMgg(userId: number): Promise<{ members: NdMggMember[] }>;
  removeMgg(userId: number): Promise<{ members: NdMggMember[] }>;
}