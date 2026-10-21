import type { Block, Circle, District, Gp, Olt } from "@/types";
import { generateDataset, type MockDataset } from "./generate";

export type { MockDataset };
export { LATEST_WEEK, FIRST_WEEK, weekId, weekEnd } from "./weeks";

export interface IndexedDataset extends MockDataset {
  circleById: Map<string, Circle>;
  districtById: Map<string, District>;
  blockById: Map<string, Block>;
  oltById: Map<string, Olt>;
  gpById: Map<string, Gp>;
}

let cache: IndexedDataset | null = null;

/** Centralised DEMO dataset (generated once, deterministic). */
export function getDataset(): IndexedDataset {
  if (cache) return cache;
  const ds = generateDataset();
  cache = {
    ...ds,
    circleById: new Map(ds.circles.map((c) => [c.id, c])),
    districtById: new Map(ds.districts.map((d) => [d.id, d])),
    blockById: new Map(ds.blocks.map((b) => [b.id, b])),
    oltById: new Map(ds.olts.map((o) => [o.id, o])),
    gpById: new Map(ds.gps.map((g) => [g.id, g])),
  };
  return cache;
}
