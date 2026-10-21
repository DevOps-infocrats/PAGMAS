"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Fragment, useState } from "react";
import { TableSkeleton } from "@/components/feedback/states";
import { Segmented } from "@/components/ui/controls";
import { Card } from "@/components/ui/primitives";
import { useApiQuery } from "@/hooks/use-api-query";
import { useFilters } from "@/hooks/use-filters";
import { api, type FieldPerson, type FieldRole } from "@/lib/api";
import { cn } from "@/lib/utils/cn";
import { formatCount, formatPercent } from "@/lib/utils/format";
import { BODY_ROW, HEAD_ROW, RowHead, TableCard, Td, Th } from "@/features/amc-conversion/table-ui";
import { FieldError, MaskNote, SearchBox } from "./field-parts";

export const ROLE_TABS: { value: FieldRole; label: string; plural: string }[] = [
  { value: "am", label: "Area manager", plural: "Area managers" },
  { value: "splicer", label: "Splicer", plural: "Splicers" },
  { value: "frt", label: "FRT team", plural: "FRT teams" },
  { value: "fe", label: "FE", plural: "FEs" },
];

export function roleFrom(v: string | null): FieldRole {
  return ROLE_TABS.some((r) => r.value === v) ? (v as FieldRole) : "am";
}

/** Count + the first names; the full list is in the expanded row. */
function Preview({ names, unit }: { names: string[] | undefined; unit: string }) {
  if (!names || names.length === 0) return <span className="text-subtle-foreground">—</span>;
  const shown = names.slice(0, 2).join(", ");
  return (
    <span className="block max-w-[200px]">
      <span className="font-semibold">{formatCount(names.length)}</span> <span className="text-muted-foreground">{unit}</span>
      <span className="block truncate text-[11px] text-muted-foreground" title={names.join(", ")}>
        {shown}
        {names.length > 2 && ` +${names.length - 2} more`}
      </span>
    </span>
  );
}

function Names({ title, names }: { title: string; names: string[] | undefined }) {
  if (!names || names.length === 0) return null;
  return (
    <div className="min-w-0">
      <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        {title} ({formatCount(names.length)})
      </p>
      <p className="mt-1 text-[13px] leading-relaxed">{names.join(" · ")}</p>
    </div>
  );
}

/** Expanded row: districts with their blocks, then the teams / people linked to this person. */
function Detail({ p }: { p: FieldPerson }) {
  return (
    <div className="grid gap-4 bg-muted/30 px-4 py-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
      <div className="min-w-0">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          Districts ({formatCount(p.districtCount)}) and blocks ({formatCount(p.blockCount)})
        </p>
        <dl className="mt-1.5 space-y-1.5 text-[13px]">
          {p.districts.map((d) => (
            <div key={d.name} className="grid grid-cols-[150px_minmax(0,1fr)] gap-3">
              <dt className="font-medium">
                {d.name} <span className="font-normal text-muted-foreground">({d.blocks.length})</span>
              </dt>
              <dd className="text-muted-foreground">{d.blocks.join(" · ")}</dd>
            </div>
          ))}
        </dl>
      </div>
      <div className="min-w-0 space-y-3">
        <Names title="Area manager" names={p.ams} />
        <Names title="FRT teams" names={p.frtTeams} />
        <Names title="FEs" names={p.fes} />
        <Names title="Splicers" names={p.splicers} />
        {p.spellings.length > 0 && <p className="text-xs text-muted-foreground">Written in the file as: {p.spellings.join(" / ")} – counted once.</p>}
        {p.phoneShared && <p className="text-xs text-warning-text">⚠ This phone number is also listed under another name in the file.</p>}
      </div>
    </div>
  );
}

/**
 * Team Directory: area managers / splicers / FRT teams / FEs, each counted once (same state + same name ignoring case,
 * spaces and punctuation). A row opens the districts and blocks the person covers and the teams linked to them.
 */
export function TeamDirectory() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const role = roleFrom(params.get("role"));
  const { period, filters } = useFilters();
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const q = useApiQuery(period ? `field-people:${role}:${period.weekId}:${filters.circle}:${search}` : null, () =>
    api.getFieldPeople(role, { weekId: period!.weekId, circleId: filters.circle, search: search || undefined }),
  );
  const d = q.data ?? q.staleData;
  const setRole = (r: FieldRole) => {
    const next = new URLSearchParams(params.toString());
    next.set("role", r);
    setOpen(null);
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  };
  if (q.error) return <FieldError error={q.error} onRetry={q.reload} />;
  const tab = ROLE_TABS.find((t) => t.value === role)!;
  const cols = 1 + 1 + (role !== "frt" ? 1 : 0) + (role !== "am" ? 1 : 0) + (role === "splicer" || role === "frt" ? 1 : 0) + 2 + (role !== "frt" ? 1 : 0) + (role === "am" ? 2 : 0) + (role === "fe" ? 1 : 0) + (role === "frt" ? 1 : 0) + 3;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <SearchBox onSearch={setSearch} placeholder={`${tab.label} name, district or block`} />
      </div>
      {d && <MaskNote masked={d.phonesMasked && role !== "frt"} />}
      {!d ? (
        <Card className="p-4">
          <TableSkeleton rows={8} />
        </Card>
      ) : (
        <TableCard
          title={`${formatCount(d.count)} ${tab.plural}`}
          description={[
            Object.entries(d.byState)
              .map(([id, n]) => `${d.items.find((x) => x.circleId === id)?.circle ?? id} ${formatCount(n)}`)
              .join(" · "),
            d.vacantPosts ? `${formatCount(d.vacantPosts)} vacant post${d.vacantPosts > 1 ? "s" : ""}` : "",
            d.gpsWithout ? `${formatCount(d.gpsWithout)} GPs without a ${tab.label.toLowerCase()} in the file` : "",
            "click a row for its districts, blocks and teams",
          ]
            .filter(Boolean)
            .join(" · ")}
          actions={<Segmented<FieldRole> ariaLabel="Role" value={role} onChange={setRole} options={ROLE_TABS.map((t) => ({ value: t.value, label: t.plural }))} />}
        >
          <div className={cn("overflow-x-auto rounded-lg border border-border", q.loading && "opacity-60")}>
            <table className="w-full min-w-[1000px] text-[13px]">
              <caption className="sr-only">{tab.plural}</caption>
              <thead>
                <tr className={HEAD_ROW}>
                  <Th first>{tab.label}</Th>
                  <Th className="text-left">State</Th>
                  {role !== "frt" && <Th className="text-left">Phone</Th>}
                  {role !== "am" && <Th className="text-left">Area manager</Th>}
                  {(role === "splicer" || role === "frt") && <Th className="text-left">FE</Th>}
                  <Th group className="text-left">
                    Districts
                  </Th>
                  <Th className="text-left">Blocks</Th>
                  {role !== "frt" && <Th className="text-left">FRT teams</Th>}
                  {role === "am" && <Th className="text-left">FEs</Th>}
                  {(role === "am" || role === "fe" || role === "frt") && <Th className="text-left">Splicers</Th>}
                  <Th group>GPs</Th>
                  <Th>AMC GPs</Th>
                  <Th>Availability (MTD)</Th>
                </tr>
              </thead>
              <tbody>
                {d.items.map((p) => {
                  const isOpen = open === p.id;
                  const blocks = p.districts.flatMap((x) => x.blocks);
                  return (
                    <Fragment key={p.id}>
                      <tr
                        tabIndex={0}
                        aria-expanded={isOpen}
                        aria-label={`${isOpen ? "Hide" : "Show"} districts and blocks of ${p.name}`}
                        onClick={() => setOpen(isOpen ? null : p.id)}
                        onKeyDown={(e) => e.key === "Enter" && setOpen(isOpen ? null : p.id)}
                        className={cn(BODY_ROW, "cursor-pointer align-top", isOpen && "bg-primary-soft/40", p.vacant && "text-muted-foreground")}
                      >
                        <RowHead>
                          <span className="flex items-start gap-1.5">
                            {isOpen ? <ChevronDown className="mt-0.5 size-3.5 shrink-0 text-primary" /> : <ChevronRight className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />}
                            <span className="min-w-0">
                              <span className={cn("block max-w-[200px] truncate", p.vacant && "italic")} title={p.name}>
                                {p.name}
                              </span>
                              {p.vacant && <span className="mt-0.5 inline-block rounded bg-warning-soft px-1.5 text-[10px] font-semibold uppercase text-warning-text">Vacant post</span>}
                            </span>
                          </span>
                        </RowHead>
                        <Td className="text-left">{p.circle}</Td>
                        {role !== "frt" && (
                          <Td className="text-left text-xs text-muted-foreground">
                            {p.phone ?? "—"}
                            {p.phoneShared && <span className="ml-1 text-warning-text" title="Also listed under another name">⚠</span>}
                          </Td>
                        )}
                        {role !== "am" && <Td className="whitespace-normal text-left">{p.ams?.length ? p.ams.join(", ") : <span className="text-subtle-foreground">—</span>}</Td>}
                        {(role === "splicer" || role === "frt") && <Td className="whitespace-normal text-left">{p.fes?.length ? p.fes.join(", ") : "—"}</Td>}
                        <Td group className="whitespace-normal text-left">
                          <Preview names={p.districts.map((x) => x.name)} unit={p.districtCount === 1 ? "district" : "districts"} />
                        </Td>
                        <Td className="whitespace-normal text-left">
                          <Preview names={blocks} unit={blocks.length === 1 ? "block" : "blocks"} />
                        </Td>
                        {role !== "frt" && (
                          <Td className="whitespace-normal text-left">
                            <Preview names={p.frtTeams} unit="teams" />
                          </Td>
                        )}
                        {role === "am" && (
                          <Td className="whitespace-normal text-left">
                            <Preview names={p.fes} unit="FEs" />
                          </Td>
                        )}
                        {(role === "am" || role === "fe" || role === "frt") && (
                          <Td className="whitespace-normal text-left">
                            <Preview names={p.splicers} unit="splicers" />
                          </Td>
                        )}
                        <Td group className="tabular font-semibold">
                          {formatCount(p.gps)}
                        </Td>
                        <Td className="tabular">{formatCount(p.amcGps)}</Td>
                        <Td className="tabular">{p.availability == null ? "NA" : formatPercent(p.availability, 1)}</Td>
                      </tr>
                      {isOpen && (
                        <tr className="border-b border-border/70">
                          <td colSpan={cols} className="p-0">
                            <Detail p={p} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </TableCard>
      )}
    </div>
  );
}
