"use client";

import { ErrorState, TableSkeleton } from "@/components/feedback/states";
import { Card } from "@/components/ui/primitives";
import { useApiQuery } from "@/hooks/use-api-query";
import { useFilters } from "@/hooks/use-filters";
import { api, type AmcAreaManagerRow } from "@/lib/api";
import { cn } from "@/lib/utils/cn";
import { formatCount, formatDate, formatPercent } from "@/lib/utils/format";
import { BODY_ROW, HEAD_ROW, RowHead, TOTAL_ROW, TableCard, Td, Th } from "./table-ui";

const dayMonth = (iso: string) => formatDate(iso).slice(0, 6);
/** Area managers at or above this achievement % are highlighted. */
const GOOD_PCT = 50;
/** Achieved % in green (this table only); — when there is no target. */
const GreenPct = ({ pct }: { pct: number | null }) => (pct == null ? <span className="text-muted-foreground">—</span> : <span className="font-medium text-good-text">{formatPercent(pct, 1)}</span>);

/**
 * One state's AMC conversion per area manager, under the state table of Monthly / Weekly Plan vs Execution.
 * Monthly: the current month's target (Planned Date in the month) and achieved so far (Ach Date, 1st – data date).
 * Weekly: the selected week's target and achieved. GP counts (blocks, existing, AMC, non-AMC) are the same in both.
 * AM names come from the Escalation Matrix (the master data's AM Name when no matrix has been uploaded).
 */
export function AreaManagerTable({ view, circleId }: { view: "monthly" | "weekly"; circleId: string }) {
  const { period } = useFilters();
  const q = useApiQuery(period ? `amc-am:${period.weekId}:${circleId}` : null, () => api.getAmcAreaManagers(period!.weekId, circleId));
  const r = q.data ?? q.staleData;
  const monthly = view === "monthly";

  if (q.error)
    return (
      <Card>
        <ErrorState error={q.error} onRetry={q.reload} />
      </Card>
    );
  if (!r || r.circle.id !== circleId)
    return (
      <Card className="p-4">
        <TableSkeleton rows={6} />
      </Card>
    );

  const periodLabel = monthly ? r.month.label : `${r.week.label} (${dayMonth(r.week.start)} – ${dayMonth(r.week.end)})`;
  const achievedRange = monthly ? `1 – ${dayMonth(r.month.asOf)}` : `${dayMonth(r.week.start)} – ${dayMonth(r.week.asOf)}`;
  const target = (x: AmcAreaManagerRow) => (monthly ? x.monthTarget : x.weekTarget);
  const achieved = (x: AmcAreaManagerRow) => (monthly ? x.monthAchieved : x.weekAchieved);
  const pct = (x: AmcAreaManagerRow) => (monthly ? x.monthAchievedPct : x.weekAchievedPct);
  const named = r.rows.filter((x) => x.assigned).length;
  // Highest achievement % among real area managers (not "Not assigned" / "Vacant"); nothing is highlighted at 0%.
  const best = Math.max(0, ...r.rows.filter((x) => x.assigned && pct(x) != null).map((x) => pct(x) as number));
  const isTop = (x: AmcAreaManagerRow) => best > 0 && x.assigned && pct(x) === best;
  // 50% or more achieved (area managers only) is highlighted; the best one stronger still
  const isGood = (x: AmcAreaManagerRow) => x.assigned && (pct(x) ?? 0) >= GOOD_PCT;
  const source = r.amSource === "escalation" ? "Escalation Matrix" : "master data";

  return (
    <TableCard
      title={`Area manager-wise target vs achieved – ${r.circle.name}, ${periodLabel}`}
      description={
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span>
            {formatCount(named)} area manager{named === 1 ? "" : "s"} ({source}) · Target = Planned Date · Achieved = Ach Date {achievedRange}
          </span>
          <span className="inline-flex items-center gap-1.5 text-xs">
            <span className="size-3 rounded-sm bg-good-soft ring-1 ring-good/40" aria-hidden /> ≥ {GOOD_PCT}% achieved
          </span>
          <span className="inline-flex items-center gap-1.5 text-xs">
            <span className="size-3 rounded-sm bg-good" aria-hidden /> Best
          </span>
        </span>
      }
    >
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <caption className="sr-only">Area manager-wise AMC conversion of {r.circle.name}</caption>
          <thead>
            <tr className="bg-muted text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              <th scope="colgroup" colSpan={2} className="sticky left-0 bg-muted px-3 pt-2.5" />
              <th scope="colgroup" colSpan={4} className="border-l border-border/70 px-2.5 pt-2.5 text-center">
                GPs
              </th>
              <th scope="colgroup" colSpan={3} className="border-l border-border/70 px-2.5 pt-2.5 text-center text-primary">
                {monthly ? `${r.month.label} – target vs achieved` : `${r.week.label} – target vs achieved`}
              </th>
            </tr>
            <tr className={HEAD_ROW}>
              <Th className="w-10 text-left">#</Th>
              <Th first>Area manager</Th>
              <Th group>Blocks</Th>
              <Th>Existing GPs</Th>
              <Th>AMC GPs</Th>
              <Th>Non-AMC GPs</Th>
              <Th group current>
                Target
              </Th>
              <Th current>Achieved</Th>
              <Th current>Achieved %</Th>
            </tr>
          </thead>
          <tbody className="tabular">
            {r.rows.map((x, i) => (
              <tr
                key={x.name}
                className={cn(
                  BODY_ROW,
                  !x.assigned && "text-muted-foreground",
                  isGood(x) && !isTop(x) && "bg-good-soft/60 hover:bg-good-soft/60",
                  isTop(x) && "bg-good-soft font-semibold hover:bg-good-soft",
                )}
              >
                <Td className={cn("text-left text-subtle-foreground", isTop(x) ? "border-l-4 border-l-good" : isGood(x) && "border-l-4 border-l-good/40")}>{i + 1}</Td>
                <RowHead className={cn(isTop(x) ? "bg-good-soft font-bold text-good-text" : isGood(x) && "bg-good-soft/60")}>{x.assigned ? x.name : <span className="italic">{x.name}</span>}</RowHead>
                <Td group>{formatCount(x.blocks)}</Td>
                <Td>{formatCount(x.existingGps)}</Td>
                <Td>{formatCount(x.amcGps)}</Td>
                <Td className={cn(x.nonAmcGps > 0 && x.assigned && "text-warning-text")}>{formatCount(x.nonAmcGps)}</Td>
                <Td group current={!isGood(x)} className="font-semibold">
                  {formatCount(target(x))}
                </Td>
                <Td current={!isGood(x)} className="font-semibold text-good-text">
                  {formatCount(achieved(x))}
                </Td>
                <Td current={!isGood(x)}>
                  {/* best = solid green pill; ≥ 50% = light green pill; others = green text */}
                  {isTop(x) ? (
                    <span className="inline-block rounded-md bg-good px-2 py-0.5 text-[14px] font-extrabold text-white">{formatPercent(pct(x), 1)}</span>
                  ) : isGood(x) ? (
                    <span className="inline-block rounded-md bg-good-soft px-2 py-0.5 font-bold text-good-text ring-1 ring-good/40">{formatPercent(pct(x), 1)}</span>
                  ) : (
                    <GreenPct pct={pct(x)} />
                  )}
                </Td>
              </tr>
            ))}
          </tbody>
          <tfoot className="tabular">
            <tr className={TOTAL_ROW}>
              <Td className="text-left"> </Td>
              <RowHead total>Total – {r.circle.name}</RowHead>
              <Td group>{formatCount(r.total.blocks)}</Td>
              <Td>{formatCount(r.total.existingGps)}</Td>
              <Td>{formatCount(r.total.amcGps)}</Td>
              <Td>{formatCount(r.total.nonAmcGps)}</Td>
              <Td group current>
                {formatCount(target(r.total))}
              </Td>
              <Td current>{formatCount(achieved(r.total))}</Td>
              <Td current>
                <GreenPct pct={pct(r.total)} />
              </Td>
            </tr>
          </tfoot>
        </table>
      </div>
      {r.warnings.length > 0 && <p className="mt-2 px-1 text-xs text-warning-text">⚠ {r.warnings.join(" ")}</p>}
    </TableCard>
  );
}
