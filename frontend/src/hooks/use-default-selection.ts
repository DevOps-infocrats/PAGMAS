"use client";

import { useEffect } from "react";
import { useMeta } from "@/components/providers/data-provider";
import { useFilters, type Filters } from "./use-filters";

/**
 * When a page needs a circle/block but none is in the URL, select the first
 * available one (and write it to the URL so links and filters stay in sync).
 */
export function useDefaultSelection(level: "circle" | "block") {
  const meta = useMeta();
  const { filters, setFilters } = useFilters();

  useEffect(() => {
    if (!meta) return;
    const patch: Filters = {};
    const circle = filters.circle && meta.circles.some((c) => c.id === filters.circle) ? filters.circle : meta.circles[0]?.id;
    if (circle !== filters.circle) patch.circle = circle;
    if (level === "block") {
      const valid = meta.blocks.find((b) => b.id === filters.block && b.circleId === circle);
      if (!valid) {
        const first = meta.blocks.find((b) => b.circleId === circle && (!filters.district || b.districtId === filters.district))
          ?? meta.blocks.find((b) => b.circleId === circle);
        if (first) {
          patch.district = first.districtId;
          patch.block = first.id;
        }
      } else if (valid.districtId !== filters.district) {
        patch.district = valid.districtId;
      }
    }
    if (Object.keys(patch).length) setFilters(patch);
  }, [meta, level, filters.circle, filters.district, filters.block, setFilters]);
}
