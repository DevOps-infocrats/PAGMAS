import type { AreaManager, Block, Circle, District, Gp, IngestionRun, Olt, ReportingWeek } from "@/types";
import { CIRCLE_SEEDS, placeName } from "./names";
import { createRandom, round, type Random } from "./random";
import { FIRST_WEEK, LATEST_WEEK, addYears, buildWeeks, weekEnd, weekId } from "./weeks";

export interface MockDataset {
  weeks: ReportingWeek[];
  circles: Circle[];
  districts: District[];
  areaManagers: AreaManager[];
  blocks: Block[];
  olts: Olt[];
  gps: Gp[];
  ingestionRuns: IngestionRun[];
}

const SEED = 20261011;

type Profile = { min: number; max: number; zero?: boolean };

function pickProfile(rng: Random, health: number): Profile {
  const r = rng.next();
  if (r < 0.03 * (2 - health)) return { min: 0, max: 0, zero: true };
  if (r < 0.15 * (2 - health)) return { min: 55, max: 85 };
  if (r < 0.38) return { min: 85, max: 97.6 };
  return { min: 97.6, max: 100 };
}

function generateAvailability(
  rng: Random,
  profile: Profile,
  blockPenalty: number,
  fromWeek: number,
  untilWeek: number,
): Record<string, number | null> {
  const out: Record<string, number | null> = {};
  for (let w = Math.max(fromWeek, FIRST_WEEK); w <= untilWeek; w++) {
    if (rng.chance(0.022)) {
      out[weekId(w)] = null; // not reported this week → NA
      continue;
    }
    if (profile.zero) {
      out[weekId(w)] = rng.chance(0.85) ? 0 : round(rng.float(5, 40));
      continue;
    }
    let v = rng.float(profile.min, profile.max) + (w - FIRST_WEEK) * 0.12 - blockPenalty;
    if (rng.chance(0.05)) v -= rng.float(8, 30);
    out[weekId(w)] = round(Math.min(100, Math.max(0, v)));
  }
  return out;
}

export function generateDataset(): MockDataset {
  const rng = createRandom(SEED);
  const usedNames = new Set<string>();
  const weeks = buildWeeks();
  const circles: Circle[] = [];
  const districts: District[] = [];
  const areaManagers: AreaManager[] = [];
  const blocks: Block[] = [];
  const olts: Olt[] = [];
  const gps: Gp[] = [];

  CIRCLE_SEEDS.forEach((seed, ci) => {
    const circleId = seed.code.toLowerCase();
    circles.push({ id: circleId, code: seed.code, name: seed.name });
    const health = 0.75 + ((ci * 37) % 8) / 16; // 0.75 – 1.19, differs per circle
    let blockSeq = 0;

    for (let d = 0; d < seed.districts; d++) {
      const districtId = `${circleId}-d${d + 1}`;
      const amId = `${circleId}-am${Math.floor(d / 2) + 1}`;
      if (!areaManagers.some((a) => a.id === amId)) {
        areaManagers.push({
          id: amId,
          circleId,
          label: `AM-${seed.code}-${String(Math.floor(d / 2) + 1).padStart(2, "0")}`,
        });
      }
      districts.push({ id: districtId, circleId, name: placeName(rng, usedNames), areaManagerId: amId });

      const blockCount = rng.int(3, 5);
      for (let b = 0; b < blockCount; b++) {
        blockSeq += 1;
        const blockCode = `${seed.code}-${String(blockSeq).padStart(3, "0")}`;
        const blockId = blockCode.toLowerCase();
        const blockName = placeName(rng, usedNames);
        const oltCount = rng.int(1, 3);
        const oltIds: string[] = [];
        for (let o = 0; o < oltCount; o++) {
          const oltId = `OLT-${blockCode}-${o + 1}`;
          oltIds.push(oltId);
          olts.push({
            id: oltId,
            blockId,
            location: o === 0 ? `${blockName} Telephone Exchange` : `${placeName(rng, usedNames)} BTS Site`,
            ponPorts: rng.pick([8, 16, 16, 32]),
          });
        }
        blocks.push({ id: blockId, code: blockCode, circleId, districtId, name: blockName, oltIds });

        const blockPenalty = rng.chance(0.13) ? rng.float(6, 14) : 0;
        // GP names only need to be unique within their block.
        const gpNames = new Set<string>();
        const gpCount = Math.round(rng.int(9, 22) * seed.weight);

        for (let g = 0; g < gpCount; g++) {
          const incremental = rng.chance(0.18);
          const addedWeek = incremental ? (rng.chance(0.55) ? rng.int(20, FIRST_WEEK - 1) : rng.int(FIRST_WEEK + 1, LATEST_WEEK)) : null;
          const lr = rng.next();
          const lifecycle = lr < 0.02 ? "CONVERTED_NP" : lr < 0.03 ? "PERMANENTLY_CLOSED" : "ACTIVE";
          const lifecycleWeek = lifecycle === "ACTIVE" ? null : rng.int(FIRST_WEEK, LATEST_WEEK);
          const hotoApplicable = lifecycle === "ACTIVE" ? rng.chance(0.97) : false;

          let hotoWeek: number | null = null;
          if (hotoApplicable) {
            const hr = rng.next();
            const earliest = addedWeek ? addedWeek + 1 : 18;
            if (hr < 0.55) hotoWeek = rng.int(earliest, Math.max(earliest, FIRST_WEEK - 1));
            else if (hr < 0.86) hotoWeek = rng.int(Math.max(earliest, FIRST_WEEK), LATEST_WEEK);
            if (hotoWeek != null && hotoWeek > LATEST_WEEK) hotoWeek = null;
          }

          let amcStartWeek: number | null = null;
          if (hotoWeek != null && rng.chance(0.86)) {
            const s = hotoWeek + rng.int(1, 3);
            amcStartWeek = s <= LATEST_WEEK ? s : null;
          }

          const availability =
            amcStartWeek != null
              ? generateAvailability(rng, pickProfile(rng, health), blockPenalty, amcStartWeek, lifecycleWeek ? lifecycleWeek - 1 : LATEST_WEEK)
              : {};

          const gpSeq = String(g + 1).padStart(3, "0");
          gps.push({
            id: `${blockCode}-${gpSeq}`.toLowerCase(),
            lgdCode: String(100000 + ci * 90000 + blockSeq * 400 + g * 7),
            name: placeName(rng, gpNames),
            circleId,
            districtId,
            blockId,
            classification: incremental ? "INCREMENTAL" : "EXISTING",
            addedWeek,
            revisedExisting: !incremental && rng.chance(0.07),
            lifecycle,
            lifecycleWeek,
            hotoApplicable,
            hotoWeek,
            amcStartWeek,
            amcEndDate: amcStartWeek != null ? addYears(weekEnd(amcStartWeek), 5) : null,
            bsnlRkm: rng.chance(0.14) ? 0 : round(rng.float(0.4, 7.5)),
            bbnlRkm: rng.chance(0.1) ? 0 : round(rng.float(0.8, 9.5)),
            oltId: rng.chance(0.02) ? null : rng.pick(oltIds),
            oneTimeUpSept26: amcStartWeek != null && amcStartWeek <= 39 && rng.chance(0.93),
            availability,
          });
        }
      }
    }
  });

  return { weeks, circles, districts, areaManagers, blocks, olts, gps, ingestionRuns: generateIngestionRuns(rng, gps.length) };
}

function generateIngestionRuns(rng: Random, gpTotal: number): IngestionRun[] {
  const runs: IngestionRun[] = [];
  for (let w = LATEST_WEEK; w >= LATEST_WEEK - 9; w--) {
    const failed = w === LATEST_WEEK - 3;
    const partial = !failed && rng.chance(0.3);
    const rejected = failed ? 0 : partial ? rng.int(4, 38) : 0;
    const startedAt = `${weekEnd(w)}T0${rng.int(6, 8)}:${String(rng.int(0, 59)).padStart(2, "0")}:00Z`;
    runs.push({
      id: `run-${w}`,
      fileName: `GP_Uptime_HOTO_Report_W${w}_DEMO.xlsx`,
      startedAt,
      durationSec: failed ? rng.int(3, 9) : rng.int(38, 140),
      status: failed ? "FAILED" : partial ? "PARTIAL" : "SUCCESS",
      accepted: failed ? 0 : gpTotal - rejected,
      rejected,
      validationErrors: failed
        ? [{ row: 1, column: "—", message: "Header row not found: expected column 'GP LGD Code' (demo error)" }]
        : Array.from({ length: Math.min(rejected, 6) }, (_, i) => ({
            row: rng.int(12, gpTotal),
            column: rng.pick(["Availability %", "BSNL RKM", "OLT Location", "HOTO Date"]),
            message: rng.pick([
              "Value outside 0–100 range",
              "Non-numeric value",
              "Required value missing",
              "Date not parseable",
            ]) + (i === 0 ? " (demo)" : ""),
          })),
    });
  }
  return runs;
}
