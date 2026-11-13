"use client";

import { History, Loader2, Plus, RotateCcw, Save, Trash2 } from "lucide-react";
import { useState } from "react";
import { ErrorState, TableSkeleton } from "@/components/feedback/states";
import { SectionHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/controls";
import { Card, Input } from "@/components/ui/primitives";
import { useApiQuery } from "@/hooks/use-api-query";
import { adminApi, type PlanFile, type PlanFileVersion } from "@/lib/api";
import { formatDateTime } from "@/lib/utils/format";

type Cell = number | string | null;
type Grid = Record<string, Record<string, Cell>>;
type Draft = Record<string, unknown>;

const ROW_PATTERN = { month: /^\d{4}-(0[1-9]|1[0-2])$/, week: /^W-\d{1,2}$/ } as const;
const ROW_HINT = { month: "Month, e.g. 2027-02", week: "Week, e.g. W-50" } as const;

const clone = (d: Draft): Draft => JSON.parse(JSON.stringify(d)) as Draft;

/** Admin editor of the plan files (management plan, month targets). Every save is validated by the backend and kept
 * as a version, so an earlier one can be loaded and saved again. */
export function PlanFilesCard() {
  const [tick, setTick] = useState(0);
  const q = useApiQuery(`plan-files:${tick}`, () => adminApi.listPlanFiles());
  const [selected, setSelected] = useState<string | null>(null);
  const file = q.data?.find((f) => f.name === selected) ?? q.data?.[0];
  return (
    <section className="space-y-4" aria-labelledby="ops-plans">
      <SectionHeader
        id="ops-plans"
        title="Plan & targets"
        description="Management plan and month targets used by Management Review and AMC Conversion. Changes show on the dashboard at once; every save is kept in the history."
        action={
          q.data && q.data.length > 1 ? (
            <Segmented<string> ariaLabel="Plan file" value={file?.name ?? ""} onChange={setSelected} options={q.data.map((f) => ({ value: f.name, label: f.name }))} />
          ) : undefined
        }
      />
      <Card className="p-5">
        {q.error ? (
          <ErrorState error={q.error} onRetry={q.reload} />
        ) : !file ? (
          <TableSkeleton rows={3} />
        ) : (
          <PlanEditor key={`${file.name}:${file.updatedAt}`} file={file} onSaved={() => setTick((t) => t + 1)} />
        )}
      </Card>
    </section>
  );
}

function PlanEditor({ file, onSaved }: { file: PlanFile; onSaved: () => void }) {
  const [draft, setDraft] = useState<Draft>(() => clone(file.data));
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [showHistory, setShowHistory] = useState(false);

  const update = (fn: (d: Draft) => void) => {
    setDraft((d) => {
      const next = clone(d);
      fn(next);
      return next;
    });
    setDirty(true);
    setMsg(null);
  };

  const save = async () => {
    setBusy(true);
    setMsg(null);
    try {
      await adminApi.savePlanFile(file.name, draft);
      setDirty(false);
      setMsg({ tone: "ok", text: "Saved – the dashboard uses the new values now." });
      onSaved();
    } catch (e) {
      setMsg({ tone: "error", text: e instanceof Error ? e.message : "Could not save" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-0.5">
          <p className="text-sm font-semibold text-subheading">{file.label}</p>
          <p className="text-xs text-muted-foreground">
            {file.name} · {file.updatedAt ? `last saved ${formatDateTime(file.updatedAt)}` : "not created yet"}
          </p>
          {file.problem && <p className="text-xs text-critical-text">The saved file cannot be read: {file.problem}</p>}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={() => setShowHistory((s) => !s)}>
            <History /> History
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={!dirty || busy}
            onClick={() => {
              setDraft(clone(file.data));
              setDirty(false);
              setMsg(null);
            }}
          >
            <RotateCcw /> Discard
          </Button>
          <Button size="sm" disabled={!dirty || busy} onClick={save}>
            {busy ? <Loader2 className="animate-spin" /> : <Save />} Save
          </Button>
        </div>
      </div>

      {msg && <p className={msg.tone === "ok" ? "text-sm text-good-text" : "text-sm text-critical-text"}>{msg.text}</p>}

      {showHistory && (
        <PlanHistory
          name={file.name}
          onLoad={(v) => {
            setDraft(clone(v.content));
            setDirty(true);
            setShowHistory(false);
            setMsg({ tone: "ok", text: `Version of ${v.savedAt ? formatDateTime(v.savedAt) : "—"} loaded – check it and press Save to restore it.` });
          }}
        />
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="space-y-1 text-xs font-medium text-muted-foreground">
          Source (shown on the dashboard)
          <Input value={String(draft.source ?? "")} maxLength={200} onChange={(e) => update((d) => void (d.source = e.target.value))} />
        </label>
        {file.fields.map((f) => (
          <label key={f.key} className="space-y-1 text-xs font-medium text-muted-foreground">
            {f.label}
            <Input value={String(draft[f.key] ?? "")} maxLength={20} onChange={(e) => update((d) => void (d[f.key] = e.target.value))} />
          </label>
        ))}
      </div>

      {file.sections.map((s) => (
        <GridEditor
          key={s.key}
          label={s.label}
          rowKind={s.rowKind}
          grid={(draft[s.key] as Grid | undefined) ?? {}}
          onChange={(fn) =>
            update((d) => {
              const g = ((d[s.key] as Grid | undefined) ?? {}) as Grid;
              fn(g);
              d[s.key] = g;
            })
          }
        />
      ))}
    </div>
  );
}

function GridEditor({ label, rowKind, grid, onChange }: { label: string; rowKind: "month" | "week"; grid: Grid; onChange: (fn: (g: Grid) => void) => void }) {
  const rows = Object.keys(grid);
  const states = [...new Set(rows.flatMap((r) => Object.keys(grid[r] ?? {})))];
  const [newRow, setNewRow] = useState("");
  const [newState, setNewState] = useState("");
  const rowOk = ROW_PATTERN[rowKind].test(newRow.trim()) && !rows.includes(newRow.trim());
  const stateOk = newState.trim() !== "" && !states.includes(newState.trim().toUpperCase());

  return (
    <div className="space-y-2">
      <p className="text-[0.8125rem] font-semibold text-subheading">{label}</p>
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full min-w-[32.5rem] text-sm">
          <thead className="bg-muted/50">
            <tr className="text-left text-xs text-muted-foreground">
              <th className="px-3 py-2 font-medium">{rowKind === "month" ? "Month" : "Week"}</th>
              {states.map((st) => (
                <th key={st} className="px-3 py-2 text-right font-medium">
                  {st}
                </th>
              ))}
              <th className="w-10" />
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={states.length + 2} className="px-3 py-3 text-xs text-muted-foreground">
                  No rows yet.
                </td>
              </tr>
            )}
            {rows.map((r) => (
              <tr key={r} className="border-t border-border/60">
                <td className="tabular px-3 py-1.5 font-medium">{r}</td>
                {states.map((st) => (
                  <td key={st} className="px-2 py-1">
                    <Input
                      inputMode="numeric"
                      aria-label={`${r} ${st}`}
                      className="h-8 w-24 text-right tabular ml-auto"
                      value={grid[r]?.[st] == null ? "" : String(grid[r][st])}
                      placeholder="—"
                      onChange={(e) => {
                        const v = e.target.value.replace(/[^\d]/g, "");
                        onChange((g) => void ((g[r] ??= {})[st] = v === "" ? null : Number(v)));
                      }}
                    />
                  </td>
                ))}
                <td className="px-1 text-right">
                  <Button size="sm" variant="ghost" aria-label={`Remove ${r}`} onClick={() => window.confirm(`Remove ${r}?`) && onChange((g) => void delete g[r])}>
                    <Trash2 />
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Input className="h-8 w-44" placeholder={ROW_HINT[rowKind]} value={newRow} onChange={(e) => setNewRow(e.target.value)} />
        <Button
          size="sm"
          variant="outline"
          disabled={!rowOk}
          onClick={() => {
            const key = newRow.trim();
            onChange((g) => void (g[key] = Object.fromEntries(states.map((st) => [st, null]))));
            setNewRow("");
          }}
        >
          <Plus /> Add {rowKind}
        </Button>
        <Input className="ml-2 h-8 w-44" placeholder="State, e.g. ASSAM" value={newState} onChange={(e) => setNewState(e.target.value)} />
        <Button
          size="sm"
          variant="outline"
          disabled={!stateOk || rows.length === 0}
          onClick={() => {
            const st = newState.trim().toUpperCase();
            onChange((g) => rows.forEach((r) => void ((g[r] ??= {})[st] = null)));
            setNewState("");
          }}
        >
          <Plus /> Add state
        </Button>
      </div>
    </div>
  );
}

function PlanHistory({ name, onLoad }: { name: string; onLoad: (v: PlanFileVersion) => void }) {
  const q = useApiQuery(`plan-history:${name}`, () => adminApi.getPlanFileHistory(name));
  if (q.error) return <ErrorState error={q.error} onRetry={q.reload} />;
  if (!q.data) return <TableSkeleton rows={2} />;
  if (q.data.length === 0) return <p className="text-sm text-muted-foreground">No saved versions yet – the first save keeps the current file as the original.</p>;
  return (
    <div className="max-h-64 overflow-y-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <tbody>
          {q.data.map((v) => (
            <tr key={v.id} className="border-b border-border/60 last:border-0">
              <td className="px-3 py-2">{v.savedAt ? formatDateTime(v.savedAt) : "—"}</td>
              <td className="px-3 py-2 text-muted-foreground">{v.savedBy ?? "—"}</td>
              <td className="px-3 py-2 text-xs text-muted-foreground">{v.note === "original" ? "original file" : ""}</td>
              <td className="px-3 py-1.5 text-right">
                <Button size="sm" variant="ghost" onClick={() => onLoad(v)}>
                  Load
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
