"use client";

import { ChevronDown, ChevronRight, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { Segmented } from "@/components/ui/controls";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/overlays";
import type { BlockInsightsResponse } from "@/lib/api";
import { THRESHOLDS } from "@/lib/metrics/definitions";
import { cn } from "@/lib/utils/cn";
import { formatDate, formatPercent } from "@/lib/utils/format";
import type { GpSnapshot } from "@/types";

type Group = "nonAmc" | "amc" | "incremental";
type Groups = NonNullable<BlockInsightsResponse["amcGroups"]>;

const GROUP_LABEL: Record<Group, string> = {
  nonAmc: "Non-AMC",
  amc: "AMC",
  incremental: "Incremental",
};
const GROUP_COLOR: Record<Group, string> = {
  nonAmc: "var(--na)",
  amc: "var(--series-2)",
  incremental: "var(--series-4)",
};
const GROUP_NOTE: Record<Group, string> = {
  nonAmc:
    "Revised existing GPs not yet under AMC on the week end. HOTO shows whether handover is done – the usual next step before AMC.",
  amc: "GPs from the original AMC list, under AMC on the week end. Availability = month to date.",
  incremental:
    "GPs added through the incremental AMC letter, under AMC on the week end. Availability = month to date.",
};

/**
 * "View GPs" dropdown of the AMC KPI: which GPs are AMC, incremental or non-AMC.
 * The GP codes come from the backend with the same rules as the KPI counts, so the lists always add up.
 */
export function AmcGpList({
  groups,
  gps,
  onOpenGp,
}: {
  groups?: Groups;
  gps: GpSnapshot[];
  onOpenGp: (gp: GpSnapshot) => void;
}) {
  const [group, setGroup] = useState<Group>("nonAmc");
  const [q, setQ] = useState("");
  const byId = useMemo(() => new Map(gps.map((g) => [g.id, g])), [gps]);
  const list = useMemo(() => {
    const ids = groups?.[group] ?? [];
    const needle = q.trim().toLowerCase();
    return ids
      .map((id) => byId.get(id))
      .filter(
        (g): g is GpSnapshot =>
          !!g &&
          (!needle ||
            g.name.toLowerCase().includes(needle) ||
            g.lgdCode.includes(needle)),
      )
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [groups, group, q, byId]);

  if (!groups) return null;
  const count = (g: Group) => groups[g].length;

  return (
    <Popover onOpenChange={(open) => !open && setQ("")}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1 text-xs font-medium text-foreground shadow-sm transition-colors hover:border-primary/40 hover:bg-primary-soft/60 data-[state=open]:border-primary/50 data-[state=open]:bg-primary-soft/60"
        >
          View GP list
          <ChevronDown className="size-3.5 text-muted-foreground" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[min(92vw,400px)] p-0">
        <div className="space-y-3 border-b border-border p-3">
          <div>
            <p className="text-sm font-semibold">GPs by AMC status</p>
            <p className="text-xs text-muted-foreground">
              Pick a group to see its GPs · click a GP to open it
            </p>
          </div>
          <Segmented<Group>
            ariaLabel="AMC group"
            value={group}
            onChange={(g) => {
              setGroup(g);
              setQ("");
            }}
            options={(["nonAmc", "amc", "incremental"] as Group[]).map((g) => ({
              value: g,
              label: `${GROUP_LABEL[g]} · ${count(g)}`,
            }))}
          />
          {count(group) > 8 && (
            <label className="flex items-center gap-2 rounded-md border border-input px-2.5">
              <Search className="size-3.5 text-subtle-foreground" />
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search GP name or LGD code"
                aria-label="Search GPs"
                className="h-8 w-full bg-transparent text-sm outline-none placeholder:text-subtle-foreground"
              />
            </label>
          )}
        </div>

        <ul
          className="max-h-72 overflow-y-auto py-1"
          aria-label={`${GROUP_LABEL[group]} GPs`}
        >
          {list.length === 0 ? (
            <li className="px-3 py-6 text-center text-sm text-muted-foreground">
              {count(group) === 0
                ? `No ${GROUP_LABEL[group].toLowerCase()} GPs in this block.`
                : "No GP matches the search."}
            </li>
          ) : (
            list.map((g) => {
              const v = g.availability;
              const tone =
                v == null
                  ? ""
                  : v > THRESHOLDS.healthy
                    ? "text-good-text"
                    : v >= THRESHOLDS.penalty
                      ? "text-warning-text"
                      : "text-critical-text";
              return (
                <li key={g.id}>
                  <button
                    type="button"
                    onClick={() => onOpenGp(g)}
                    className="group flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-accent focus-visible:bg-accent"
                  >
                    <span
                      className="size-2 shrink-0 rounded-full"
                      style={{ background: GROUP_COLOR[group] }}
                      aria-hidden
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">
                        {g.name}
                      </span>
                      <span className="block text-xs text-subtle-foreground">
                        LGD {g.lgdCode}
                      </span>
                    </span>
                    <span className="shrink-0 text-right text-xs">
                      {group === "nonAmc" ? (
                        g.hotoStatus === "DONE" ? (
                          <>
                            <span className="block font-medium text-good-text">
                              HOTO done
                            </span>
                            <span className="block text-subtle-foreground">
                              {formatDate(g.hotoDate)}
                            </span>
                          </>
                        ) : (
                          <span className="block font-medium text-warning-text">
                            HOTO pending
                          </span>
                        )
                      ) : (
                        <>
                          <span
                            className={cn(
                              "tabular block font-semibold",
                              tone || "text-muted-foreground",
                            )}
                          >
                            {v == null ? "NA" : formatPercent(v, 2)}
                          </span>
                          <span className="block text-subtle-foreground">
                            AMC {formatDate(g.amcStartDate)}
                          </span>
                        </>
                      )}
                    </span>
                    <ChevronRight className="size-4 shrink-0 text-subtle-foreground opacity-0 transition-opacity group-hover:opacity-100" />
                  </button>
                </li>
              );
            })
          )}
        </ul>
        <p className="border-t border-border px-3 py-2 text-[11px] leading-relaxed text-muted-foreground">
          {GROUP_NOTE[group]}
        </p>
      </PopoverContent>
    </Popover>
  );
}
