import type { BlockSummary, CircleSummary, Gp, GpSnapshot, KpiValue, ReportingWeek, TrendSeries } from "@/types";
import { FIRST_WEEK, getDataset, type IndexedDataset, weekEnd } from "@/lib/mock-data";
import {
  amcAt,
  availabilityAt,
  blockAvailability,
  blockBands,
  existsAt,
  gpBands,
  groupBy,
  hotoAt,
  inScope,
  lifecycleAt,
  summarize,
} from "@/lib/metrics/compute";
import { METRICS, THRESHOLDS, type SummaryMetricsShape } from "@/lib/metrics/definitions";
import type {
  DashboardApi,
  OverviewDetail,
  GpDetailResponse,
  OverviewResponse,
  ReportComparisonRow,
  SearchResult,
  WeeklyReportResponse,
} from "./contracts";
import { ApiError } from "./errors";

/** Number of weekly points shown in sparklines / trend charts. */
const HISTORY_WEEKS = 8;

const delay = (ms = 220 + Math.random() * 260) => new Promise((r) => setTimeout(r, ms));

export const weekNumber = (id: string) => {
  const n = Number(id.split("-W")[1]);
  if (!Number.isFinite(n)) throw new ApiError(400, `Invalid week id: ${id}`);
  return n;
};

const summaryCache = new Map<string, SummaryMetricsShape>();

function cachedSummary(scope: string, gps: Gp[], w: number) {
  const key = `${scope}|${w}`;
  let s = summaryCache.get(key);
  if (!s) {
    s = summarize(gps, w);
    summaryCache.set(key, s);
  }
  return s;
}

function historyWeeks(ds: IndexedDataset, w: number): ReportingWeek[] {
  return ds.weeks.filter((wk) => wk.number <= w && wk.number > w - HISTORY_WEEKS && wk.number >= FIRST_WEEK);
}

function buildKpis(scope: string, gps: Gp[], w: number, prev: number, keys: string[], weeks: ReportingWeek[]): KpiValue[] {
  const current = cachedSummary(scope, gps, w);
  const previous = cachedSummary(scope, gps, prev);
  const hist = weeks.map((wk) => cachedSummary(scope, gps, wk.number));
  return keys.map((key) => {
    const k = key as keyof SummaryMetricsShape;
    return { key, value: current[k] ?? null, previous: previous[k] ?? null, history: hist.map((h) => h[k] ?? null) };
  });
}

function toSnapshot(ds: IndexedDataset, gp: Gp, w: number): GpSnapshot {
  const block = ds.blockById.get(gp.blockId)!;
  const district = ds.districtById.get(gp.districtId)!;
  const circle = ds.circleById.get(gp.circleId)!;
  const hoto = hotoAt(gp, w);
  const amc = amcAt(gp, w);
  return {
    id: gp.id,
    lgdCode: gp.lgdCode,
    name: gp.name,
    circleId: circle.id,
    circleName: circle.name,
    districtId: district.id,
    districtName: district.name,
    blockId: block.id,
    blockName: block.name,
    classification: gp.classification,
    lifecycle: lifecycleAt(gp, w),
    hotoStatus: hoto,
    hotoDate: hoto === "DONE" && gp.hotoWeek != null ? weekEnd(gp.hotoWeek) : null,
    amcStatus: amc,
    amcStartDate: amc === "AMC" && gp.amcStartWeek != null ? weekEnd(gp.amcStartWeek) : null,
    amcEndDate: amc === "AMC" ? gp.amcEndDate : null,
    bsnlRkm: gp.bsnlRkm,
    bbnlRkm: gp.bbnlRkm,
    totalRkm: Math.round((gp.bsnlRkm + gp.bbnlRkm) * 100) / 100,
    availability: availabilityAt(gp, w),
    oltId: gp.oltId,
    oltLocation: gp.oltId ? (ds.oltById.get(gp.oltId)?.location ?? null) : null,
  };
}

function circleSummary(ds: IndexedDataset, circleId: string, gps: Gp[], w: number): CircleSummary {
  const c = ds.circleById.get(circleId)!;
  const s = cachedSummary(`c:${circleId}`, gps, w);
  return {
    id: c.id,
    name: c.name,
    code: c.code,
    districts: s.totalDistricts,
    blocks: s.totalBlocks,
    totalGps: s.totalGps,
    hotoDoneBlocks: s.hotoDoneBlocks,
    hotoDoneGps: s.hotoDoneGps,
    amcGps: s.amcGps,
    amcPct: s.amcPct,
    availability: s.availability,
    gpsAbove98: s.gpsAbove98,
    gpsAtZero: s.gpsAtZero,
    naGps: s.naGps,
    penaltyBlocks: s.penaltyBlocks,
    incrementalGps: s.incrementalGps,
    convertedNp: s.convertedNp,
    permanentlyClosed: s.permanentlyClosed,
    bsnlRkm: s.bsnlRkm,
    bbnlRkm: s.bbnlRkm,
  };
}

function blockSummary(ds: IndexedDataset, blockId: string, blockGps: Gp[], w: number): BlockSummary {
  const b = ds.blockById.get(blockId)!;
  const s = cachedSummary(`b:${blockId}`, blockGps, w);
  return {
    id: b.id,
    name: b.name,
    code: b.code,
    districtId: b.districtId,
    districtName: ds.districtById.get(b.districtId)!.name,
    totalGps: s.totalGps,
    hotoDone: s.hotoDoneGps,
    hotoPending: s.hotoPendingGps,
    amcGps: s.amcGps,
    availability: blockAvailability(inScope(blockGps, w), w),
    totalRkm: s.totalRkm,
  };
}

const series = (name: string, weeks: ReportingWeek[], value: (w: number) => number | null): TrendSeries => ({
  name,
  points: weeks.map((wk) => ({ weekId: wk.id, date: wk.endDate, value: value(wk.number) })),
});

function findWeek(ds: IndexedDataset, id: string): ReportingWeek {
  const wk = ds.weeks.find((x) => x.id === id);
  if (!wk) throw new ApiError(404, `Reporting week ${id} not found`);
  return wk;
}

function overviewDetail(s: SummaryMetricsShape): OverviewDetail {
  return {
    states: s.totalStates,
    blocks: s.totalBlocks,
    existingGps: s.totalGps,
    newGps: 0,
    totalGps: s.totalGps,
    revisedExisting: s.totalGps - s.convertedNp - s.permanentlyClosed,
    convertedOrClosed: s.convertedNp + s.permanentlyClosed,
    convertedNp: s.convertedNp,
    permanentlyClosed: s.permanentlyClosed,
    deductedGps: 0,
    hotoDoneBlocks: s.hotoDoneBlocks,
    hotoPendingBlocks: s.totalBlocks - s.hotoDoneBlocks,
    hotoDoneGps: s.hotoDoneGps,
    hotoPendingGps: s.hotoPendingGps,
    amcGps: s.amcGps,
    amcOriginalGps: s.amcGps - s.incrementalGps,
    incrementalGps: s.incrementalGps,
    nonAmcGps: s.nonAmcGps,
    amcPct: s.amcPct,
    availability: s.availability,
    gpsAbove98: s.gpsAbove98,
    gpsAtZero: s.gpsAtZero,
    naGps: s.naGps,
    penaltyBlocks: s.penaltyBlocks,
    oneTimeUp: s.oneTimeUp,
    totalRkm: s.totalRkm,
    bsnlRkm: s.bsnlRkm,
    bbnlRkm: s.bbnlRkm,
    amcRkm: s.amcRkm,
    rkmPartsDifference: 0,
  };
}

export const mockApi: DashboardApi = {
  async getMeta() {
    await delay(120);
    const ds = getDataset();
    return {
      weeks: ds.weeks,
      latestWeekId: ds.weeks[ds.weeks.length - 1].id,
      circles: ds.circles,
      districts: ds.districts,
      blocks: ds.blocks.map(({ id, name, code, circleId, districtId }) => ({ id, name, code, circleId, districtId })),
    };
  },

  async getOverview({ weekId: wid, compareWeekId }) {
    await delay();
    const ds = getDataset();
    const w = findWeek(ds, wid).number;
    const prev = findWeek(ds, compareWeekId).number;
    const weeks = historyWeeks(ds, w);
    const keys = [
      "totalGps", "amcPct", "gpsAbove98", "penaltyBlocks",
      "totalStates", "totalBlocks", "revisedExisting", "hotoDoneBlocks",
      "hotoDoneGps", "amcGps", "gpsAtZero", "oneTimeUp", "availability", "incrementalGps", "amcRkm",
    ];
    const byCircle = groupBy(ds.gps, (g) => g.circleId);
    const areaManagers: OverviewResponse["areaManagers"] = [];
    for (const am of ds.areaManagers) {
      const districtIds = new Set(ds.districts.filter((d) => d.areaManagerId === am.id).map((d) => d.id));
      const gps = (byCircle.get(am.circleId) ?? []).filter((g) => districtIds.has(g.districtId));
      const s = cachedSummary(`am:${am.id}`, gps, w);
      areaManagers.push({ circleId: am.circleId, manager: am, gps: s.totalGps, availability: s.availability, gpsAbove98: s.gpsAbove98, penaltyBlocks: s.penaltyBlocks });
    }
    return {
      summary: overviewDetail(cachedSummary("all", ds.gps, w)),
      stateDetails: ds.circles.map((c) => ({ id: c.id, name: c.name, ...overviewDetail(cachedSummary(`c:${c.id}`, byCircle.get(c.id) ?? [], w)) })),
      asOf: weekEnd(w),
      weeks,
      kpis: buildKpis("all", ds.gps, w, prev, keys, weeks),
      circles: ds.circles.map((c) => circleSummary(ds, c.id, byCircle.get(c.id) ?? [], w)),
      circlesPrevious: ds.circles.map((c) => circleSummary(ds, c.id, byCircle.get(c.id) ?? [], prev)),
      areaManagers,
    };
  },

  async getCircleInsights(circleId, { weekId: wid, compareWeekId }) {
    await delay();
    const ds = getDataset();
    const circle = ds.circleById.get(circleId);
    if (!circle) throw new ApiError(404, `Circle ${circleId} not found`);
    const w = findWeek(ds, wid).number;
    const prev = findWeek(ds, compareWeekId).number;
    const weeks = historyWeeks(ds, w);
    const gps = ds.gps.filter((g) => g.circleId === circleId);
    const scoped = inScope(gps, w);
    const byBlock = groupBy(gps, (g) => g.blockId);
    const blocks = ds.blocks
      .filter((b) => b.circleId === circleId)
      .map((b) => blockSummary(ds, b.id, byBlock.get(b.id) ?? [], w))
      .filter((b) => b.totalGps > 0);

    const hotoAmc = ds.districts
      .filter((d) => d.circleId === circleId)
      .map((d) => {
        const dg = scoped.filter((g) => g.districtId === d.id);
        const amc = dg.filter((g) => amcAt(g, w) === "AMC").length;
        return {
          districtId: d.id,
          districtName: d.name,
          applicable: dg.filter((g) => g.hotoApplicable).length,
          hotoDone: dg.filter((g) => hotoAt(g, w) === "DONE").length,
          hotoPending: dg.filter((g) => hotoAt(g, w) === "PENDING").length,
          amc,
          nonAmc: dg.length - amc,
        };
      });

    return {
      circle,
      weeks,
      summary: { ...overviewDetail(cachedSummary(`c:${circleId}`, gps, w)), districts: cachedSummary(`c:${circleId}`, gps, w).totalDistricts },
      asOf: weekEnd(w),
      currentWeek: findWeek(ds, wid),
      kpis: buildKpis(`c:${circleId}`, gps, w, prev, ["revisedExisting", "hotoDoneGps", "amcGps", "availability", "totalDistricts", "totalBlocks", "totalRkm", "penaltyBlocks", "amcRkm"], weeks),
      blocks,
      hotoAmc,
      gpUptimeTrend: [
        series("≥ 98%", weeks, (n) => gpBands(gps, n).above98),
        series(`${THRESHOLDS.penalty}–98%`, weeks, (n) => gpBands(gps, n).from85to98),
        series(`< ${THRESHOLDS.penalty}%`, weeks, (n) => gpBands(gps, n).below85),
        series("0%", weeks, (n) => gpBands(gps, n).zero),
      ],
      blockUptimeTrend: [
        series("≥ 98%", weeks, (n) => blockBands(gps, n).above98),
        series(`${THRESHOLDS.penalty}–98%`, weeks, (n) => blockBands(gps, n).from85to98),
        series(`< ${THRESHOLDS.penalty}% (penalty-prone)`, weeks, (n) => blockBands(gps, n).below85),
      ],
    };
  },

  async getBlockInsights(blockId, { weekId: wid, compareWeekId }) {
    await delay();
    const ds = getDataset();
    const block = ds.blockById.get(blockId);
    if (!block) throw new ApiError(404, `Block ${blockId} not found`);
    const w = findWeek(ds, wid).number;
    const prev = findWeek(ds, compareWeekId).number;
    const weeks = historyWeeks(ds, w);
    const gps = ds.gps.filter((g) => g.blockId === blockId);
    const scoped = inScope(gps, w);
    const snaps = scoped.map((g) => toSnapshot(ds, g, w));

    const amcSnaps = snaps.filter((s) => s.amcStatus === "AMC");
    const classification = [
      { label: "AMC (existing)", count: amcSnaps.filter((s) => s.classification === "EXISTING").length },
      { label: "Incremental", count: amcSnaps.filter((s) => s.classification === "INCREMENTAL").length },
      { label: "Non-AMC", count: snaps.filter((s) => s.amcStatus !== "AMC" && s.lifecycle === "ACTIVE").length },
      { label: "Converted / closed", count: snaps.filter((s) => s.lifecycle !== "ACTIVE").length },
    ];

    return {
      circle: ds.circleById.get(block.circleId)!,
      district: ds.districtById.get(block.districtId)!,
      block,
      weeks,
      kpis: buildKpis(
        `b:${blockId}`, gps, w, prev,
        ["revisedExisting", "totalRkm", "hotoDoneGps", "amcGps", "bsnlRkm", "bbnlRkm", "hotoPendingGps", "nonAmcGps", "availability", "gpsAbove98"],
        weeks,
      ),
      gps: snaps,
      olts: block.oltIds.map((id) => ({ ...ds.oltById.get(id)!, gpCount: scoped.filter((g) => g.oltId === id).length })),
      uptimeTrend: [
        series("Average availability", weeks, (n) => blockAvailability(inScope(gps, n), n)),
      ],
      classification,
      incrementalByWeek: weeks.map((wk) => ({
        weekId: wk.id,
        date: wk.endDate,
        added: gps.filter((g) => g.addedWeek === wk.number).length,
      })),
      summary: overviewDetail(cachedSummary(`b:${blockId}`, gps, w)),
    };
  },

  async getGpDetail(gpId, wid) {
    await delay();
    const ds = getDataset();
    const gp = ds.gpById.get(gpId);
    if (!gp) throw new ApiError(404, `GP ${gpId} not found`);
    const week = findWeek(ds, wid);
    const w = week.number;
    if (!existsAt(gp, w)) throw new ApiError(404, `GP ${gp.name} was not in scope in ${week.label}`);

    const history =
      gp.amcStartWeek == null || gp.amcStartWeek > w
        ? null
        : ds.weeks
            .filter((wk) => wk.number >= gp.amcStartWeek! && wk.number <= w)
            .map((wk) => ({ weekId: wk.id, date: wk.endDate, value: availabilityAt(gp, wk.number) }));

    const events: { week: number; event: string }[] = [];
    if (gp.addedWeek != null) events.push({ week: gp.addedWeek, event: "Added to scope as incremental GP" });
    if (gp.hotoWeek != null && gp.hotoWeek <= w) events.push({ week: gp.hotoWeek, event: "HOTO completed" });
    if (gp.amcStartWeek != null && gp.amcStartWeek <= w) events.push({ week: gp.amcStartWeek, event: "AMC coverage started" });
    if (gp.lifecycleWeek != null && gp.lifecycleWeek <= w)
      events.push({ week: gp.lifecycleWeek, event: gp.lifecycle === "CONVERTED_NP" ? "Converted to NP" : "Permanently closed" });

    const issues: GpDetailResponse["issues"] = [];
    if (!gp.oltId) issues.push({ code: "OLT_MISSING", message: "OLT location missing in source record", severity: "critical" });
    if (gp.bsnlRkm + gp.bbnlRkm === 0) issues.push({ code: "RKM_ZERO", message: "No fibre route (RKM) recorded for this GP", severity: "warning" });
    if (gp.revisedExisting) issues.push({ code: "REVISED", message: "Master record revised in the existing GP list", severity: "warning" });
    for (const p of history ?? []) {
      if (p.value == null) issues.push({ code: "NA_WEEK", message: `Availability not reported`, weekId: p.weekId, severity: "warning" });
    }

    return {
      gp: toSnapshot(ds, gp, w),
      week,
      availabilityHistory: history,
      hotoHistory: events.sort((a, b) => a.week - b.week).map((e) => ({ date: weekEnd(e.week), event: e.event })),
      olt: gp.oltId ? (ds.oltById.get(gp.oltId) ?? null) : null,
      addedWeek: gp.addedWeek != null ? (ds.weeks.find((x) => x.number === gp.addedWeek) ?? null) : null,
      revisedExisting: gp.revisedExisting,
      issues,
    };
  },

  async listGps({ circleId, districtId, blockId, weekId: wid, search, page = 1, pageSize = 50 }) {
    await delay(150);
    const ds = getDataset();
    const w = findWeek(ds, wid).number;
    const q = search?.trim().toLowerCase();
    const items = ds.gps
      .filter(
        (g) =>
          existsAt(g, w) &&
          (!circleId || g.circleId === circleId) &&
          (!districtId || g.districtId === districtId) &&
          (!blockId || g.blockId === blockId) &&
          (!q || g.name.toLowerCase().includes(q) || g.lgdCode.includes(q) || g.id.includes(q)),
      )
      .map((g) => toSnapshot(ds, g, w));
    return { items: items.slice((page - 1) * pageSize, page * pageSize), total: items.length, page, pageSize };
  },

  async search(query) {
    await delay(90);
    const ds = getDataset();
    const q = query.trim().toLowerCase();
    if (q.length < 2) return [];
    const out: SearchResult[] = [];
    for (const c of ds.circles) {
      if (c.name.toLowerCase().includes(q) || c.code.toLowerCase() === q)
        out.push({ type: "circle", id: c.id, label: c.name, sublabel: `Circle · ${c.code}`, circleId: c.id });
    }
    for (const b of ds.blocks) {
      if (out.length > 24) break;
      if (b.name.toLowerCase().includes(q) || b.code.toLowerCase().includes(q))
        out.push({
          type: "block", id: b.id, label: b.name,
          sublabel: `Block · ${b.code} · ${ds.districtById.get(b.districtId)!.name}, ${ds.circleById.get(b.circleId)!.name}`,
          circleId: b.circleId, districtId: b.districtId, blockId: b.id,
        });
    }
    for (const g of ds.gps) {
      if (out.length > 30) break;
      if (g.name.toLowerCase().includes(q) || g.lgdCode.includes(q))
        out.push({
          type: "gp", id: g.id, label: g.name,
          sublabel: `GP · LGD ${g.lgdCode} · ${ds.blockById.get(g.blockId)!.name} block`,
          circleId: g.circleId, districtId: g.districtId, blockId: g.blockId,
        });
    }
    return out;
  },

  async getKpiList() {
    // KPI lists are built from the real workbook only – never from generated demo data.
    throw new ApiError(501, "KPI lists need the live backend (NEXT_PUBLIC_API_MODE=live).");
  },

  async getFieldSummary() {
    throw new ApiError(501, "Field Team & Escalation needs the live backend (NEXT_PUBLIC_API_MODE=live).");
  },
  async getFieldLookup() {
    throw new ApiError(501, "Field Team & Escalation needs the live backend (NEXT_PUBLIC_API_MODE=live).");
  },
  async getFieldWorkload() {
    throw new ApiError(501, "Field Team & Escalation needs the live backend (NEXT_PUBLIC_API_MODE=live).");
  },
  async getFieldPeople() {
    throw new ApiError(501, "Field Team & Escalation needs the live backend (NEXT_PUBLIC_API_MODE=live).");
  },
  async getFieldDown() {
    throw new ApiError(501, "Field Team & Escalation needs the live backend (NEXT_PUBLIC_API_MODE=live).");
  },
  async getFieldGaps() {
    throw new ApiError(501, "Field Team & Escalation needs the live backend (NEXT_PUBLIC_API_MODE=live).");
  },

  async getAmcPlanTimeline() {
    throw new ApiError(501, "AMC conversion plan vs execution needs the live backend (NEXT_PUBLIC_API_MODE=live).");
  },

  async getAmcPlanSummary() {
    throw new ApiError(501, "AMC conversion plan vs execution needs the live backend (NEXT_PUBLIC_API_MODE=live).");
  },

  async getAmcConversion() {
    // The plan vs execution is computed from the real workbook and plan file only – never from generated demo data.
    throw new ApiError(501, "AMC conversion plan vs execution needs the live backend (NEXT_PUBLIC_API_MODE=live).");
  },

  async getManagementReview() {
    // The review is computed from the real workbook only – never from generated demo data.
    throw new ApiError(501, "Management Review needs the live backend (NEXT_PUBLIC_API_MODE=live).");
  },

  async getWeeklyReport({ weekId: wid, compareWeekId, circleId, districtId, blockId }) {
    await delay(400);
    const ds = getDataset();
    const week = findWeek(ds, wid);
    const compareWeek = findWeek(ds, compareWeekId);
    const w = week.number;
    const prev = compareWeek.number;
    const gps = ds.gps.filter(
      (g) => (!circleId || g.circleId === circleId) && (!districtId || g.districtId === districtId) && (!blockId || g.blockId === blockId),
    );
    const scopeKey = `r:${circleId ?? "*"}:${districtId ?? "*"}:${blockId ?? "*"}`;
    const cur = cachedSummary(scopeKey, gps, w);
    const old = cachedSummary(scopeKey, gps, prev);

    const scopeLabel = blockId
      ? `${ds.blockById.get(blockId)?.name} block`
      : districtId
        ? `${ds.districtById.get(districtId)?.name} district`
        : circleId
          ? (ds.circleById.get(circleId)?.name ?? "—")
          : "All circles";

    const comparisonKeys: (keyof SummaryMetricsShape)[] = [
      "totalGps", "hotoDoneGps", "hotoPendingGps", "hotoDoneBlocks", "amcGps", "amcPct", "availability",
      "gpsAbove98", "gpsAtZero", "naGps", "penaltyBlocks", "incrementalGps", "totalRkm",
    ];
    const comparison: ReportComparisonRow[] = comparisonKeys.map((k) => ({
      key: k,
      label: METRICS[k].label,
      unit: METRICS[k].unit,
      polarity: METRICS[k].polarity,
      previous: old[k] ?? null,
      current: cur[k] ?? null,
    }));

    // Ranking: circles when unscoped, otherwise blocks in scope.
    const rankUnits = circleId
      ? groupBy(gps, (g) => g.blockId)
      : groupBy(gps, (g) => g.circleId);
    const ranking = [...rankUnits.entries()]
      .map(([id, ug]) => {
        const sc = `rank:${id}`;
        const a = cachedSummary(sc, ug, w);
        const b = cachedSummary(sc, ug, prev);
        const name = circleId ? ds.blockById.get(id)!.name : ds.circleById.get(id)!.name;
        return { id, name, availability: a.availability, previous: b.availability, amcPct: a.amcPct, penaltyBlocks: a.penaltyBlocks };
      })
      .sort((x, y) => (y.availability ?? -1) - (x.availability ?? -1));

    const byBlock = groupBy(inScope(gps, w), (g) => g.blockId);
    const penaltyBlocks = [...byBlock.entries()]
      .map(([id, bg]) => ({ id, bg, availability: blockAvailability(bg, w) }))
      .filter((x) => x.availability != null && x.availability < THRESHOLDS.penalty)
      .sort((a, b) => a.availability! - b.availability!)
      .slice(0, 15)
      .map(({ id, bg, availability }) => {
        const b = ds.blockById.get(id)!;
        return {
          id,
          name: b.name,
          circleName: ds.circleById.get(b.circleId)!.name,
          districtName: ds.districtById.get(b.districtId)!.name,
          availability,
          previous: blockAvailability(inScope(bg, prev), prev),
        };
      });

    const lowAvailabilityGps = inScope(gps, w)
      .map((g) => ({ g, v: availabilityAt(g, w) }))
      .filter((x): x is { g: Gp; v: number } => x.v != null && x.v < THRESHOLDS.penalty)
      .sort((a, b) => a.v - b.v)
      .slice(0, 15)
      .map(({ g, v }) => ({ id: g.id, name: g.name, blockName: ds.blockById.get(g.blockId)!.name, availability: v }));

    const scoped = inScope(gps, w);
    const latestRun = ds.ingestionRuns[0];

    return {
      scopeLabel,
      week,
      compareWeek,
      generatedAt: new Date().toISOString(),
      isDemo: true,
      comparison,
      ranking,
      hotoProgress: [
        { label: compareWeek.label, done: old.hotoDoneGps, pending: old.hotoPendingGps },
        { label: week.label, done: cur.hotoDoneGps, pending: cur.hotoPendingGps },
      ],
      penaltyBlocks,
      lowAvailabilityGps,
      dataQuality: [
        { label: "AMC GPs with availability not reported (NA)", count: cur.naGps, severity: "warning" as const },
        { label: "GPs with OLT location missing", count: scoped.filter((g) => !g.oltId).length, severity: "critical" as const },
        { label: "GPs with no fibre route recorded", count: scoped.filter((g) => g.bsnlRkm + g.bbnlRkm === 0).length, severity: "warning" as const },
        { label: "Rows rejected in latest import (demo)", count: latestRun.rejected, severity: latestRun.status === "FAILED" ? ("critical" as const) : ("warning" as const) },
      ],
      fibreChanges: [
        { label: "BSNL existing RKM", previous: old.bsnlRkm, current: cur.bsnlRkm },
        { label: "BBNL existing RKM", previous: old.bbnlRkm, current: cur.bbnlRkm },
        { label: "Total fibre route RKM", previous: old.totalRkm, current: cur.totalRkm },
        { label: "Incremental GPs", previous: old.incrementalGps, current: cur.incrementalGps },
      ],
    } satisfies WeeklyReportResponse;
  },

  async getIngestionRuns() {
    await delay();
    return getDataset().ingestionRuns;
  },

  async retryIngestion(runId) {
    await delay(700);
    return {
      accepted: false,
      message: `Demo only: retry for ${runId} was not executed. Real ingestion will be handled by the Python backend in Phase 2.`,
    };
  },

  async getNotifications(wid) {
    await delay(100);
    const ds = getDataset();
    const week = findWeek(ds, wid);
    const s = cachedSummary("all", ds.gps, week.number);
    const run = ds.ingestionRuns[0];
    return [
      { id: "n1", severity: "critical", title: `${s.penaltyBlocks} penalty-prone blocks`, body: `Blocks below the penalty threshold in ${week.label} (demo data).`, href: "/dashboard/reports" },
      { id: "n2", severity: "warning", title: `${s.gpsAtZero} GPs at 0% MTD`, body: `AMC GPs reporting zero availability in ${week.label} (demo data).`, href: "/dashboard" },
      { id: "n3", severity: "info", title: `${s.naGps} AMC GPs not reported`, body: "Shown as NA, not 0%, in all charts (demo data)." },
      { id: "n4", severity: run.status === "SUCCESS" ? "info" : "warning", title: `Demo import: ${run.status.toLowerCase()}`, body: `${run.fileName} – placeholder record, no real file was processed.`, href: "/dashboard/operations" },
    ];
  },
};
