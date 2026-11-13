"use client";

import { AlertTriangle, CheckCircle2, Columns3, FileSearch, Loader2, RotateCcw, Trash2, Upload, XCircle } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { StatusBadge } from "@/components/feedback/badges";
import { ErrorState, TableSkeleton } from "@/components/feedback/states";
import { SearchableSelect } from "@/components/filters/searchable-select";
import { SectionHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { DialogContent, DialogDescription, DialogTitle } from "@/components/ui/overlays";
import { Card } from "@/components/ui/primitives";
import { useApiQuery } from "@/hooks/use-api-query";
import { adminApi, type ColumnCheck, type ColumnCheckField, type ColumnCheckSection, type ColumnFit, type ColumnSectionKey } from "@/lib/api";
import { cn } from "@/lib/utils/cn";

export type ColumnSource = { file: File } | { runId: string } | { escalationId: string };

/** What the admin can do once the names are saved (depends on where the file came from). */
export interface ColumnNext {
  label: string;
  run: () => Promise<void> | void;
}

const NONE = "__none__";
const KIND_TEXT: Record<ColumnFit["kind"], string> = { date: "dates", number: "numbers", phone: "phone numbers", email: "e-mail addresses" };

/**
 * Column check of one workbook: which sheets / columns the importer recognises, and – for the ones it does not –
 * a pick from the file's own columns (the most similar one is pre-selected, never saved without the admin).
 * Saving adds the file's names to the column mapper (data/column_map.json); the check then runs again.
 */
export function ColumnCheckDialog({ source, fileName, next }: { source: ColumnSource; fileName: string; next?: ColumnNext }) {
  const [round, setRound] = useState(0);
  const key = "file" in source ? `col-check:file:${fileName}:${source.file.size}:${source.file.lastModified}` : "runId" in source ? `col-check:run:${source.runId}` : `col-check:esc:${source.escalationId}`;
  const q = useApiQuery(`${key}:${round}`, () => adminApi.checkColumns(source));
  const [saved, setSaved] = useState<string[] | null>(null);

  return (
    <DialogContent className="top-[4vh] max-h-[92vh] max-w-4xl overflow-y-auto">
      <div className="space-y-4 p-5">
        <div>
          <DialogTitle className="flex items-center gap-2 text-base font-bold">
            <Columns3 className="size-4" /> Check columns – {fileName}
          </DialogTitle>
          <DialogDescription className="text-[0.8125rem] text-muted-foreground">
            Shows which sheets and columns the importer recognises. When the file uses a new name for a column, pick it here and add it to the column mapper –
            nothing is imported or changed until you click Add.
          </DialogDescription>
        </div>
        {saved && saved.length > 0 && (
          <p role="status" className="rounded-md border border-good/40 bg-good-soft px-3 py-2 text-sm text-good-text">
            Added to the column mapper: {saved.join("; ")}
          </p>
        )}
        {q.error ? (
          <ErrorState error={q.error} onRetry={q.reload} />
        ) : !q.data ? (
          <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" /> Reading the file…
          </div>
        ) : (
          <CheckBody
            key={round}
            check={q.data}
            next={next}
            onSaved={(added) => {
              setSaved(added);
              setRound((n) => n + 1);
            }}
          />
        )}
      </div>
    </DialogContent>
  );
}

function CheckBody({ check, next, onSaved }: { check: ColumnCheck; next?: ColumnNext; onSaved: (added: string[]) => void }) {
  // Pre-select the suggestions (shown as such – the admin confirms with Add).
  const [cols, setCols] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {};
    for (const s of check.sections) for (const f of s.fields) if (f.status === "missing" && f.suggestion) init[`${s.key}:${f.field}`] = f.suggestion;
    return init;
  });
  const [sheets, setSheets] = useState<Record<string, string>>(() => Object.fromEntries(check.sheetMap.filter((x) => !x.sheet && x.suggestion).map((x) => [x.key, x.suggestion!])));
  const [showAll, setShowAll] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nextBusy, setNextBusy] = useState(false);

  const picks = Object.entries(cols).filter(([, v]) => v && v !== NONE);
  const sheetPicks = Object.entries(sheets).filter(([, v]) => v && v !== NONE);
  // One column of the file may feed one field only (the server refuses it too).
  const clash = useMemo(() => {
    const seen = new Map<string, string>();
    for (const [k, v] of picks) {
      const id = `${k.split(":")[0]}:${v.toLowerCase()}`;
      if (seen.has(id)) return v;
      seen.set(id, k);
    }
    return null;
  }, [picks]);

  if (!check.kind) {
    return (
      <p className="rounded-md border border-critical/30 bg-critical-soft px-3 py-2 text-sm text-critical-text">
        This workbook was not recognised as the master data file or the Escalation Matrix – no sheet has enough of the known column names. Please check that the right
        file was chosen. Sheets in the file: {check.sheets.join(", ") || "none"}.
      </p>
    );
  }

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await adminApi.addColumnNames({
        columns: picks.map(([k, name]) => {
          const [section, field] = k.split(":");
          return { section: section as ColumnSectionKey, field, name };
        }),
        sheets: sheetPicks.map(([key, name]) => ({ key, name })),
      });
      onSaved(res.added);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <Summary check={check} />
      {check.problems.length > 0 && <p className="text-xs text-warning-text">Column mapper file: {check.problems.join("; ")}</p>}

      {check.kind === "master" && (
        <fieldset className="space-y-2 rounded-lg border border-border p-3">
          <legend className="px-1 text-sm font-semibold">Sheets</legend>
          {check.sheetMap.map((x) => (
            <div key={x.key} className="grid grid-cols-1 items-center gap-2 text-sm sm:grid-cols-[13.75rem_1fr]">
              <span className="text-muted-foreground">{x.label}</span>
              {x.sheet ? (
                <span className="flex items-center gap-1.5">
                  <CheckCircle2 className="size-4 text-good" aria-hidden /> “{x.sheet}”
                </span>
              ) : (
                <div className="space-y-1">
                  <SearchableSelect
                    label={`Sheet for ${x.label}`}
                    hideLabel
                    value={sheets[x.key]}
                    onChange={(v) => setSheets((s) => ({ ...s, [x.key]: v ?? NONE }))}
                    options={[{ value: NONE, label: "— Not in this file —" }, ...check.sheets.map((n) => ({ value: n, label: n }))]}
                    placeholder="Which sheet is it?"
                  />
                  <p className="text-xs text-muted-foreground">
                    Not found under: {x.acceptedNames.join(", ")}
                    {x.suggestion && sheets[x.key] === x.suggestion ? " · suggested from its columns" : ""}
                  </p>
                </div>
              )}
            </div>
          ))}
        </fieldset>
      )}

      {check.sections.map((s) => (
        <SectionTable key={s.key} s={s} cols={cols} setCols={setCols} showAll={showAll} />
      ))}

      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> Show the recognised columns too
      </label>

      {clash && <p className="text-sm text-critical-text">“{clash}” is chosen for two fields – one column can only feed one field.</p>}
      {error && <p className="text-sm text-critical-text">{error}</p>}

      <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border pt-3">
        {(picks.length > 0 || sheetPicks.length > 0) && (
          <Button variant="primary" onClick={() => void save()} disabled={busy || !!clash}>
            {busy && <Loader2 className="animate-spin" />} Add {picks.length + sheetPicks.length} name{picks.length + sheetPicks.length > 1 ? "s" : ""} to the column mapper
          </Button>
        )}
        {next && picks.length === 0 && sheetPicks.length === 0 && (
          <Button
            variant={check.ready ? "primary" : "outline"}
            disabled={nextBusy || !check.ready}
            title={check.ready ? undefined : "Required sheets / columns are still missing"}
            onClick={async () => {
              setNextBusy(true);
              try {
                await next.run();
              } finally {
                setNextBusy(false);
              }
            }}
          >
            {nextBusy ? <Loader2 className="animate-spin" /> : next.label.startsWith("Upload") ? <Upload /> : <RotateCcw />} {next.label}
          </Button>
        )}
      </div>
    </div>
  );
}

function Summary({ check }: { check: ColumnCheck }) {
  const what = check.kind === "escalation" ? "Escalation Matrix" : "Master data workbook";
  if (check.ready && check.missingOptional === 0) {
    return (
      <p className="flex items-center gap-2 rounded-md border border-good/40 bg-good-soft px-3 py-2 text-sm text-good-text">
        <CheckCircle2 className="size-4" aria-hidden /> {what}: every sheet and column is recognised.
      </p>
    );
  }
  if (check.ready) {
    return (
      <p className="flex items-center gap-2 rounded-md border border-warning/50 bg-warning-soft px-3 py-2 text-sm text-warning-text">
        <AlertTriangle className="size-4 shrink-0" aria-hidden /> {what}: all required columns are recognised; {check.missingOptional} optional column
        {check.missingOptional > 1 ? "s are" : " is"} not – that data stays empty until the name is added (or the column is added to the file).
      </p>
    );
  }
  return (
    <p className="flex items-center gap-2 rounded-md border border-critical/30 bg-critical-soft px-3 py-2 text-sm text-critical-text">
      <XCircle className="size-4 shrink-0" aria-hidden /> {what}: {check.missingRequired ? `${check.missingRequired} required column${check.missingRequired > 1 ? "s" : ""} not recognised` : "a required sheet is not recognised"} –
      the file cannot be imported until it is mapped below (or the file is corrected).
    </p>
  );
}

function SectionTable({ s, cols, setCols, showAll }: { s: ColumnCheckSection; cols: Record<string, string>; setCols: React.Dispatch<React.SetStateAction<Record<string, string>>>; showAll: boolean }) {
  const rows = s.fields
    .filter((f) => showAll || f.status === "missing" || (f.fit && f.fit.warning))
    .sort((a, b) => Number(b.status === "missing") - Number(a.status === "missing") || Number(b.required) - Number(a.required));
  const byHeader = new Map(s.columns.map((c) => [c.header, c]));
  return (
    <fieldset className="space-y-2 rounded-lg border border-border p-3">
      <legend className="px-1 text-sm font-semibold">
        {s.label} {s.sheet && <span className="font-normal text-muted-foreground">– sheet “{s.sheet}”{s.headerRow ? `, header row ${s.headerRow}` : ""}</span>}
      </legend>
      {!s.sheet ? (
        <p className="text-sm text-muted-foreground">{s.key === "masterBlock" ? "Sheet not found – optional (reconciliation and new GPs use it)." : "Sheet not found – choose it above."}</p>
      ) : !s.headerFound ? (
        <p className="text-sm text-critical-text">The header row (column names) was not found in the first 15 rows of “{s.sheet}”.</p>
      ) : rows.length === 0 ? (
        <p className="flex items-center gap-1.5 text-sm text-good-text">
          <CheckCircle2 className="size-4" aria-hidden /> All {s.fields.length} columns recognised.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[45rem] text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground">
                <th className="py-1.5 pr-3 font-medium">Field</th>
                <th className="py-1.5 pr-3 font-medium">In this file</th>
                <th className="py-1.5 font-medium">Sample values</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((f) => (
                <FieldRow key={f.field} s={s} f={f} value={cols[`${s.key}:${f.field}`]} onChange={(v) => setCols((c) => ({ ...c, [`${s.key}:${f.field}`]: v }))} byHeader={byHeader} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </fieldset>
  );
}

function FieldRow({
  s,
  f,
  value,
  onChange,
  byHeader,
}: {
  s: ColumnCheckSection;
  f: ColumnCheckField;
  value: string | undefined;
  onChange: (v: string) => void;
  byHeader: Map<string, ColumnCheckSection["columns"][number]>;
}) {
  const chosen = value && value !== NONE ? byHeader.get(value) : undefined;
  const fit = f.status === "found" ? f.fit : chosen?.fit[f.field];
  return (
    <tr className="border-b border-border/60 align-top last:border-0">
      <td className="py-2 pr-3">
        <span className="font-medium">{f.label}</span>
        {f.required ? (
          <StatusBadge tone="critical" className="ml-1.5">
            Required
          </StatusBadge>
        ) : (
          <span className="ml-1.5 text-xs text-muted-foreground">optional</span>
        )}
        <div className="text-xs text-muted-foreground">Known as: {f.acceptedNames.join(", ")}</div>
      </td>
      <td className="w-[18.75rem] py-2 pr-3">
        {f.status === "found" ? (
          <span className="flex items-center gap-1.5">
            <CheckCircle2 className="size-4 text-good" aria-hidden /> “{f.header}”
          </span>
        ) : (
          <div className="space-y-1">
            <SearchableSelect
              label={`Column for ${f.label}`}
              hideLabel
              value={value}
              onChange={(v) => onChange(v ?? NONE)}
              options={[{ value: NONE, label: "— Not in this file —" }, ...s.columns.map((c) => ({ value: c.header, label: c.header, hint: c.samples.slice(0, 2).join(", ") }))]}
              placeholder="Choose the file's column…"
            />
            {f.suggestion && value === f.suggestion && <p className="text-xs text-muted-foreground">Suggested – {f.similarity}% similar name. Check the values before adding.</p>}
          </div>
        )}
      </td>
      <td className="py-2 text-xs">
        <span className="text-muted-foreground">{(f.status === "found" ? f.samples : chosen?.samples)?.join(" · ") || "—"}</span>
        {fit?.warning && (
          <p className="mt-1 flex items-center gap-1 text-warning-text">
            <AlertTriangle className="size-3.5 shrink-0" aria-hidden /> Only {fit.pct}% of the values look like {KIND_TEXT[fit.kind]} – is this the right column?
          </p>
        )}
      </td>
    </tr>
  );
}

/** Data Operations card: check any workbook's columns, and the names admins added to the built-in ones. */
export function ColumnMapperCard({ onCheckFile }: { onCheckFile: (file: File) => void }) {
  const [tick, setTick] = useState(0);
  const q = useApiQuery(`column-map:${tick}`, () => adminApi.getColumnMap());
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  return (
    <section className="space-y-4" aria-labelledby="ops-columns">
      <SectionHeader
        id="ops-columns"
        title="Column names"
        description="When a file uses a new name for a sheet or column, check the file and add its names here – no code change. Built-in names always keep working."
        action={
          <>
            <input
              ref={input}
              type="file"
              accept=".xlsb,.xlsx,.xlsm"
              className="hidden"
              aria-hidden
              tabIndex={-1}
              onChange={(e) => {
                const f = e.target.files?.[0];
                e.target.value = "";
                if (f) onCheckFile(f);
              }}
            />
            <Button variant="outline" onClick={() => input.current?.click()}>
              <FileSearch /> Check a file
            </Button>
          </>
        }
      />
      <Card className="p-5">
        {error && <p className="mb-3 text-sm text-critical-text">{error}</p>}
        {q.error ? (
          <ErrorState error={q.error} onRetry={q.reload} />
        ) : !q.data ? (
          <TableSkeleton rows={2} />
        ) : q.data.names.length === 0 ? (
          <p className="text-sm text-muted-foreground">No names added yet – the built-in names are used.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[35rem] text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted-foreground">
                  <th className="py-1.5 pr-3 font-medium">Where</th>
                  <th className="py-1.5 pr-3 font-medium">Field</th>
                  <th className="py-1.5 pr-3 font-medium">Name added</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {q.data.names.map((n) => {
                  const id = `${n.section}:${n.field}:${n.name}`;
                  return (
                    <tr key={id} className="border-b border-border/60 last:border-0">
                      <td className="py-2 pr-3">{n.sectionLabel}</td>
                      <td className="py-2 pr-3">{n.fieldLabel}</td>
                      <td className="py-2 pr-3 font-medium">“{n.name}”</td>
                      <td className="py-2 text-right">
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={busy === id}
                          aria-label={`Remove ${n.name}`}
                          onClick={async () => {
                            if (!window.confirm(`Remove “${n.name}”? Files that still use this name will not be recognised any more.`)) return;
                            setBusy(id);
                            setError(null);
                            try {
                              await adminApi.removeColumnName({ section: n.section, field: n.field, name: n.name });
                              setTick((t) => t + 1);
                            } catch (e) {
                              setError(e instanceof Error ? e.message : "Could not remove");
                            } finally {
                              setBusy(null);
                            }
                          }}
                        >
                          {busy === id ? <Loader2 className="animate-spin" /> : <Trash2 />}
                        </Button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {q.data && q.data.problems.length > 0 && <p className={cn("mt-3 text-xs text-warning-text")}>{q.data.problems.join("; ")}</p>}
      </Card>
    </section>
  );
}
