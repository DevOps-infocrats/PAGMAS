"use client";

import { Download, History, Loader2, Replace, RotateCcw, Save, Info } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { TableSkeleton } from "@/components/feedback/states";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle, Select } from "@/components/ui/overlays";
import { Card, Input } from "@/components/ui/primitives";
import { useApiQuery } from "@/hooks/use-api-query";
import { useFilters } from "@/hooks/use-filters";
import { ApiError, api, type EscalationCellChange, type EscalationCellProblem, type EscalationSheet, type EscalationSheetColumn, type EscalationSheetRow } from "@/lib/api";
import { cn } from "@/lib/utils/cn";
import { formatCount, formatDate, formatDateTime } from "@/lib/utils/format";
import { FieldError, Pager, SearchBox } from "./field-parts";

const PAGE_SIZE = 100;
const BATCH = 300; // cells per save (backend limit)
type Draft = Record<string, { gpCode: string; field: string; old: string | null; value: string }>; // key = gpCode|field
const keyOf = (gp: string, field: string) => `${gp}|${field}`;
const norm = (v: string | null | undefined) => (v ?? "").replace(/\s+/g, " ").trim();

/**
 * Field Team & Escalation → Escalation Sheet: the active Escalation Matrix as a spreadsheet (backend:
 * app/analytics/escalation_sheet.py). Everyone can read (only their GPs, phones masked for non-admins) and export;
 * admins edit cells in place and save – the change is validated and written to the database, and every page that
 * uses the contacts (AM-wise targets, Generate Ticket, Field Team views) shows it at once.
 */
export function EscalationSheetView() {
  const { filters } = useFilters();
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [tick, setTick] = useState(0);
  const scope = `${filters.circle}|${filters.district}|${filters.block}|${search}`;
  const [lastScope, setLastScope] = useState(scope);
  if (scope !== lastScope) {
    setLastScope(scope);
    setPage(1);
  }
  const q = { circleId: filters.circle, districtId: filters.district, blockId: filters.block, search: search || undefined, page, pageSize: PAGE_SIZE };
  const sheet = useApiQuery(`esc-sheet:${scope}:${page}:${tick}`, () => api.getEscalationSheet(q));
  const data = sheet.data ?? sheet.staleData;

  const [draft, setDraft] = useState<Draft>({});
  const [problems, setProblems] = useState<Record<string, EscalationCellProblem>>({});
  const [saving, setSaving] = useState<{ done: number; total: number } | null>(null);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const [dialog, setDialog] = useState<"replace" | "history" | null>(null);
  const pending = Object.values(draft).filter((d) => norm(d.value) !== norm(d.old));
  const dirty = pending.length > 0;

  if (sheet.error && !data) return <FieldError error={sheet.error} onRetry={sheet.reload} />;

  const edit = (row: EscalationSheetRow, col: EscalationSheetColumn, value: string) => {
    const k = keyOf(row.gpCode, col.key);
    setDraft((d) => ({ ...d, [k]: { gpCode: row.gpCode, field: col.key, old: d[k]?.old ?? row.values[col.key] ?? null, value } }));
    if (problems[k]) setProblems((p) => Object.fromEntries(Object.entries(p).filter(([x]) => x !== k)));
  };
  const discard = () => {
    setDraft({});
    setProblems({});
    setNotice(null);
  };
  const save = async () => {
    if (!data || !dirty) return;
    const changes: EscalationCellChange[] = pending.map((d) => ({ gpCode: d.gpCode, field: d.field, old: d.old, new: norm(d.value) || null }));
    setSaving({ done: 0, total: changes.length });
    setNotice(null);
    let saved = 0;
    try {
      for (let i = 0; i < changes.length; i += BATCH) {
        const part = changes.slice(i, i + BATCH);
        const r = await api.saveEscalationSheet(data.source.importId, part);
        saved += r.saved;
        setDraft((d) => Object.fromEntries(Object.entries(d).filter(([k]) => !part.some((c) => keyOf(c.gpCode, c.field) === k))));
        setSaving({ done: i + part.length, total: changes.length });
      }
      setProblems({});
      setNotice({ ok: true, text: `${formatCount(saved)} cell${saved === 1 ? "" : "s"} saved – the change is used everywhere (Field Team, AMC Conversion AM tables, Generate Ticket).` });
      setTick((t) => t + 1);
    } catch (e) {
      const list = e instanceof ApiError ? ((e.body as { problems?: EscalationCellProblem[] } | undefined)?.problems ?? []) : [];
      setProblems(Object.fromEntries(list.map((p) => [keyOf(p.gpCode, p.field), p])));
      setNotice({ ok: false, text: `${saved ? `${formatCount(saved)} cell(s) were saved; ` : ""}${e instanceof Error ? e.message : "Could not save"}${list.length ? " – the cells are marked red; hover them for the reason." : ""}` });
      if (saved) setTick((t) => t + 1);
    } finally {
      setSaving(null);
    }
  };

  const exportHref = api.escalationSheetExportUrl(q);
  const pages = data ? Math.max(1, Math.ceil(data.total / data.pageSize)) : 1;
  return (
    <div className="space-y-4">
      {data && (
        <div className={cn("flex items-start gap-2 rounded-lg border px-4 py-2.5 text-[0.78125rem]", data.canEdit ? "border-warning/40 bg-warning-soft/50" : "border-border bg-muted/40")}>
          <Info className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
          <p className="text-muted-foreground">
            Source: <b className="text-foreground">{data.source.fileName}</b>
            {data.source.importedAt && ` (uploaded ${formatDate(data.source.importedAt)})`}
            {data.source.edits > 0 && ` · ${formatCount(data.source.edits)} cell(s) edited here${data.source.lastEditAt ? `, last ${formatDateTime(data.source.lastEditAt)}` : ""}`}.{" "}
            {data.canEdit ? (
              <>
                Saved changes update the database at once and every page uses them. A new Escalation Matrix upload replaces these contacts –{" "}
                <b className="text-foreground">export the sheet and use it as the next upload</b> to keep your corrections.
              </>
            ) : (
              <>View only{data.phonesMasked ? " · phone numbers masked" : ""} – only an admin can edit.</>
            )}
          </p>
        </div>
      )}

      <Card className="overflow-hidden p-0">
        <div className="flex flex-col gap-3 border-b border-border px-4 py-3 lg:flex-row lg:items-end lg:justify-between">
          <div className="w-full max-w-md">
            <SearchBox onSearch={setSearch} placeholder="GP code, GP, block, FE, AM, phone, e-mail…" />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {data?.canEdit && (
              <>
                <Button variant="outline" size="sm" onClick={() => setDialog("replace")} disabled={dirty || !!saving} title={dirty ? "Save or discard your changes first" : undefined}>
                  <Replace /> Find &amp; replace
                </Button>
                <Button variant="outline" size="sm" onClick={() => setDialog("history")}>
                  <History /> Edit history
                </Button>
              </>
            )}
            <Button asChild variant="outline" size="sm">
              <a href={exportHref} download>
                <Download /> Export to Excel
              </a>
            </Button>
          </div>
        </div>

        {data?.canEdit && (dirty || saving || notice) && (
          <div className={cn("flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2 text-[0.8125rem]", notice && !notice.ok ? "bg-critical-soft" : dirty ? "bg-warning-soft/60" : "bg-good-soft")}>
            <span className={cn(notice && !notice.ok ? "text-critical-text" : dirty ? "text-warning-text" : "text-good-text", "font-medium")}>
              {saving ? `Saving ${formatCount(saving.done)} / ${formatCount(saving.total)}…` : notice && !dirty ? notice.text : notice && !notice.ok ? notice.text : `${formatCount(pending.length)} unsaved change${pending.length === 1 ? "" : "s"}`}
            </span>
            {dirty && (
              <span className="flex gap-2">
                <Button size="sm" variant="ghost" onClick={discard} disabled={!!saving}>
                  <RotateCcw /> Discard
                </Button>
                <Button size="sm" variant="primary" onClick={() => void save()} disabled={!!saving}>
                  {saving ? <Loader2 className="animate-spin" /> : <Save />} Save changes
                </Button>
              </span>
            )}
          </div>
        )}

        {!data ? (
          <div className="p-4">
            <TableSkeleton rows={10} />
          </div>
        ) : data.rows.length === 0 ? (
          <p className="px-4 py-6 text-center text-sm text-muted-foreground">No GP matches the filters.</p>
        ) : (
          <Grid data={data} draft={draft} problems={problems} onEdit={edit} busy={!!saving || sheet.loading} />
        )}
        {data && (
          <div className={cn(dirty && "pointer-events-none opacity-50")} title={dirty ? "Save or discard your changes before changing the page" : undefined}>
            <Pager page={data.page} pages={pages} total={data.total} pageSize={data.pageSize} onPage={setPage} busy={sheet.loading || dirty} />
          </div>
        )}
      </Card>

      <Dialog open={dialog !== null} onOpenChange={(o) => !o && setDialog(null)}>
        {dialog === "replace" && data && (
          <ReplaceDialog
            sheet={data}
            scope={{ circle: filters.circle, district: filters.district, block: filters.block }}
            onDone={(text) => {
              setDialog(null);
              setNotice({ ok: true, text });
              setTick((t) => t + 1);
            }}
          />
        )}
        {dialog === "history" && <HistoryDialog />}
      </Dialog>
    </div>
  );
}

/** The sheet: sticky header and GP Code column, editable cells as inputs (Enter / ↑ / ↓ move between rows). */
function Grid({
  data,
  draft,
  problems,
  onEdit,
  busy,
}: {
  data: EscalationSheet;
  draft: Draft;
  problems: Record<string, EscalationCellProblem>;
  onEdit: (row: EscalationSheetRow, col: EscalationSheetColumn, value: string) => void;
  busy: boolean;
}) {
  const box = useRef<HTMLDivElement>(null);
  const cols = data.columns;
  const move = (e: React.KeyboardEvent<HTMLInputElement>, r: number, c: number) => {
    const dr = e.key === "ArrowDown" || e.key === "Enter" ? 1 : e.key === "ArrowUp" ? -1 : 0;
    if (!dr) return;
    e.preventDefault();
    box.current?.querySelector<HTMLInputElement>(`input[data-cell="${r + dr}:${c}"]`)?.focus();
  };
  return (
    <div ref={box} className={cn("max-h-[40rem] overflow-auto", busy && "opacity-70")}>
      <table className="w-max min-w-full border-separate border-spacing-0 text-[0.78125rem]">
        <caption className="sr-only">Escalation Matrix sheet</caption>
        <thead className="sticky top-0 z-20">
          <tr>
            <th scope="col" className="sticky left-0 z-30 w-10 border-b border-r border-border bg-muted px-2 py-2 text-right text-[0.6875rem] font-semibold text-muted-foreground">
              #
            </th>
            {cols.map((c) => (
              <th
                key={c.key}
                scope="col"
                className={cn(
                  "whitespace-nowrap border-b border-r border-border bg-muted px-2 py-2 text-left text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground",
                  c.key === "gp_code" && "sticky left-10 z-30",
                )}
                title={c.editable ? "Editable" : "Read only"}
              >
                {c.label}
                {!c.editable && data.canEdit && <span className="ml-1 font-normal normal-case text-subtle-foreground">(fixed)</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="tabular">
          {data.rows.map((row, r) => (
            <tr key={row.gpCode} className="group">
              <td className="sticky left-0 z-10 border-b border-r border-border bg-card px-2 py-1 text-right text-[0.6875rem] text-muted-foreground group-hover:bg-accent/40">
                {(data.page - 1) * data.pageSize + r + 1}
              </td>
              {cols.map((c, ci) => {
                const k = keyOf(row.gpCode, c.key);
                const d = draft[k];
                const value = d ? d.value : (row.values[c.key] ?? "");
                const changed = d && norm(d.value) !== norm(d.old);
                const problem = problems[k];
                const sticky = c.key === "gp_code" ? "sticky left-10 z-10 font-semibold text-primary" : "";
                if (!c.editable) {
                  return (
                    <td key={c.key} className={cn("whitespace-nowrap border-b border-r border-border bg-card px-2 py-1 group-hover:bg-accent/40", sticky, !row.values[c.key] && "text-subtle-foreground")}>
                      {row.values[c.key] ?? "—"}
                    </td>
                  );
                }
                return (
                  <td key={c.key} className={cn("border-b border-r border-border p-0", problem ? "bg-critical-soft" : changed ? "bg-warning-soft" : "bg-card group-hover:bg-accent/30")} title={problem?.message}>
                    <input
                      data-cell={`${r}:${ci}`}
                      value={value}
                      maxLength={c.maxLength}
                      disabled={busy}
                      onChange={(e) => onEdit(row, c, e.target.value)}
                      onKeyDown={(e) => move(e, r, ci)}
                      aria-label={`${c.label} of GP ${row.gpCode}`}
                      aria-invalid={!!problem}
                      inputMode={c.kind === "phone" ? "tel" : c.kind === "email" ? "email" : undefined}
                      className={cn(
                        "h-8 w-full min-w-[9rem] bg-transparent px-2 outline-none focus:bg-card focus:ring-2 focus:ring-inset focus:ring-ring/40",
                        c.kind === "email" && "min-w-[13rem]",
                        problem && "text-critical-text",
                      )}
                    />
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Whole-cell find and replace in one column within the current filters: count first, then replace. */
function ReplaceDialog({ sheet, scope, onDone }: { sheet: EscalationSheet; scope: { circle?: string; district?: string; block?: string }; onDone: (text: string) => void }) {
  const editable = useMemo(() => sheet.columns.filter((c) => c.editable), [sheet.columns]);
  const [field, setField] = useState(editable.find((c) => c.key === "am_name")?.key ?? editable[0]?.key);
  const [find, setFind] = useState("");
  const [replace, setReplace] = useState("");
  const [count, setCount] = useState<{ matches: number; sample: string[]; for: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const body = { importId: sheet.source.importId, field: field ?? "", find, replace, circle: scope.circle, district: scope.district, block: scope.block };
  const sig = JSON.stringify(body);
  const run = async (dryRun: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const r = await api.replaceInEscalationSheet({ ...body, dryRun });
      if (dryRun) setCount({ matches: r.matches, sample: r.sample, for: sig });
      else onDone(`Replaced in ${formatCount(r.saved)} GP${r.saved === 1 ? "" : "s"} – the change is used everywhere.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not replace");
    } finally {
      setBusy(false);
    }
  };
  const label = editable.find((c) => c.key === field)?.label ?? "";
  const counted = count && count.for === sig ? count : null;
  return (
    <DialogContent className="max-w-lg">
      <div className="space-y-4 p-6">
        <div>
          <DialogTitle className="text-lg font-bold">Find &amp; replace</DialogTitle>
          <DialogDescription className="mt-1 text-[0.8125rem] text-muted-foreground">
            Replaces the whole cell in one column (e.g. an Area Manager&apos;s name on all their GPs) – upper / lower case and extra spaces are ignored. Only the GPs of the current filters.
          </DialogDescription>
        </div>
        <label className="block space-y-1">
          <span className="text-xs font-semibold text-foreground/75">Column</span>
          <Select ariaLabel="Column" value={field} onValueChange={(v) => setField(v)} options={editable.map((c) => ({ value: c.key, label: c.label }))} className="w-full" />
        </label>
        <label className="block space-y-1">
          <span className="text-xs font-semibold text-foreground/75">Find (whole cell)</span>
          <Input value={find} onChange={(e) => setFind(e.target.value)} maxLength={200} placeholder="e.g. Anil Kumar Yadav" />
        </label>
        <label className="block space-y-1">
          <span className="text-xs font-semibold text-foreground/75">Replace with (empty = clear the cell)</span>
          <Input value={replace} onChange={(e) => setReplace(e.target.value)} maxLength={500} />
        </label>
        {counted && (
          <p className={cn("rounded-md px-3 py-2 text-[0.8125rem]", counted.matches ? "bg-warning-soft text-warning-text" : "bg-muted text-muted-foreground")}>
            {counted.matches ? `${formatCount(counted.matches)} GP(s) have “${find}” in ${label} (e.g. ${counted.sample.slice(0, 5).join(", ")}).` : `No GP has exactly “${find}” in ${label}.`}
          </p>
        )}
        {error && <p className="text-[0.8125rem] text-critical-text">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => void run(true)} disabled={busy || !find.trim()}>
            {busy && !counted ? <Loader2 className="animate-spin" /> : null} Count matches
          </Button>
          <Button variant="primary" onClick={() => void run(false)} disabled={busy || !counted?.matches}>
            {busy && counted ? <Loader2 className="animate-spin" /> : <Replace />} Replace {counted?.matches ? formatCount(counted.matches) : ""}
          </Button>
        </div>
      </div>
    </DialogContent>
  );
}

function HistoryDialog() {
  const q = useApiQuery("esc-sheet-edits", () => api.getEscalationSheetEdits());
  return (
    <DialogContent className="top-[6vh] max-h-[85vh] max-w-3xl overflow-y-auto">
      <div className="space-y-3 p-6">
        <DialogTitle className="text-lg font-bold">Edit history</DialogTitle>
        <DialogDescription className="text-[0.8125rem] text-muted-foreground">Latest changes made on this sheet to the active Escalation Matrix (who, when, old → new).</DialogDescription>
        {q.error ? (
          <p className="text-sm text-critical-text">{q.error.message}</p>
        ) : !q.data ? (
          <TableSkeleton rows={6} />
        ) : q.data.items.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nothing has been edited yet.</p>
        ) : (
          <div className="overflow-x-auto">
          <table className="w-full text-[0.78125rem]">
            <thead>
              <tr className="text-left text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground">
                <th className="py-1 pr-2">When</th>
                <th className="py-1 pr-2">By</th>
                <th className="py-1 pr-2">GP Code</th>
                <th className="py-1 pr-2">Column</th>
                <th className="py-1">Old → New</th>
              </tr>
            </thead>
            <tbody>
              {q.data.items.map((e, i) => (
                <tr key={i} className="border-t border-border/60 align-top">
                  <td className="whitespace-nowrap py-1 pr-2">{e.at ? formatDateTime(e.at) : "—"}</td>
                  <td className="py-1 pr-2">{e.by}</td>
                  <td className="py-1 pr-2 font-medium">{e.gpCode}</td>
                  <td className="py-1 pr-2">{e.label}</td>
                  <td className="py-1">
                    <span className="text-muted-foreground line-through">{e.old ?? "(empty)"}</span> → <b>{e.new ?? "(empty)"}</b>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        )}
      </div>
    </DialogContent>
  );
}
