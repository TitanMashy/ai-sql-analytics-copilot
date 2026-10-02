"use client";

import { useState } from "react";
import { Check, ChevronDown, Copy, Database, Gauge, Rows3, Timer } from "lucide-react";

import { ChartRenderer } from "@/components/charts/chart-renderer";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { formatLabel, formatMetricValue } from "@/lib/utils";
import type { AskResponse } from "@/types/api";

interface AnalyticsResultsProps {
  result: AskResponse;
}

function formatCell(value: unknown) {
  if (typeof value === "number") return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value);
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

export function AnalyticsResults({ result }: AnalyticsResultsProps) {
  const [sqlOpen, setSqlOpen] = useState(true);
  const [copied, setCopied] = useState(false);

  async function copySql() {
    try {
      await navigator.clipboard.writeText(result.sql);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }

  return (
    <section aria-label="Analytics results" className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-cyan-700">Query result</p>
          <h2 className="mt-1 text-xl font-semibold text-slate-900">{result.visualization?.title ?? "Analytics overview"}</h2>
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-slate-500">
          <span className="flex items-center gap-1.5"><Timer className="size-3.5" /> {Math.round(result.execution_time_ms)} ms</span>
          <span className="flex items-center gap-1.5"><Rows3 className="size-3.5" /> {result.row_count} rows</span>
          <span className="flex items-center gap-1.5"><Database className="size-3.5" /> {result.tables_used.join(", ") || "Analytics"}</span>
        </div>
      </div>

      {result.summary && (
        <div className="flex gap-3 rounded-lg border-l-4 border-cyan-600 bg-cyan-50/70 px-4 py-3">
          <Gauge className="mt-0.5 size-4 shrink-0 text-cyan-800" />
          <p className="text-sm leading-6 text-slate-700">{result.summary}</p>
        </div>
      )}

      {result.kpi && (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <article className="rounded-lg border border-slate-200 bg-white p-4">
            <p className="text-xs font-medium text-slate-500">{result.kpi.label}</p>
            <p className="mt-2 text-2xl font-semibold tabular-nums text-slate-900">
              {formatMetricValue(result.kpi.value, result.kpi.format)}
            </p>
          </article>
          <article className="rounded-lg border border-slate-200 bg-white p-4">
            <p className="text-xs font-medium text-slate-500">Rows analyzed</p>
            <p className="mt-2 text-2xl font-semibold tabular-nums text-slate-900">{result.row_count.toLocaleString()}</p>
          </article>
          <article className="rounded-lg border border-slate-200 bg-white p-4">
            <p className="text-xs font-medium text-slate-500">Data sources</p>
            <p className="mt-2 truncate text-base font-semibold text-slate-900" title={result.tables_used.join(", ")}>
              {result.tables_used.length ? result.tables_used.map(formatLabel).join(", ") : "Analytics"}
            </p>
          </article>
        </div>
      )}

      {result.visualization && result.rows.length > 0 && result.visualization.type !== "table" && result.visualization.type !== "kpi" && (
        <div className="rounded-lg border border-slate-200 bg-white p-4 sm:p-5">
          <ChartErrorBoundary key={`${result.question}-${result.row_count}`}>
            <ChartRenderer data={result.rows} visualization={result.visualization} />
          </ChartErrorBoundary>
        </div>
      )}

      {result.rows.length > 0 ? (
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
          <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
            <h3 className="text-sm font-semibold text-slate-800">Result set</h3>
            <span className="text-xs text-slate-500">Showing {result.rows.length} of {result.row_count} rows</span>
          </div>
          <div className="max-h-[420px] overflow-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="sticky top-0 bg-slate-50 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                <tr>
                  {result.columns.map((column) => (
                    <th key={column} scope="col" className="whitespace-nowrap px-4 py-3">{formatLabel(column)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.rows.map((row, rowIndex) => (
                  <tr key={`${rowIndex}-${Object.values(row).join("-")}`} className="border-t border-slate-100 even:bg-slate-50/50">
                    {result.columns.map((column) => (
                      <td key={`${column}-${rowIndex}`} className="max-w-[360px] whitespace-nowrap px-4 py-3 text-slate-700">
                        {formatCell(row[column])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!result.rows.length && <p className="p-5 text-sm text-slate-500">The query returned no rows.</p>}
        </div>
      ) : (
        <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-sm text-slate-500">No rows returned for this query.</div>
      )}

      {result.warnings.length > 0 && (
        <div role="status" className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-amber-900">Data notes</p>
          <ul className="mt-2 list-inside list-disc space-y-1 text-sm text-amber-900">
            {result.warnings.map((warning, index) => <li key={`${index}-${warning}`}>{warning}</li>)}
          </ul>
        </div>
      )}

      {result.sql && (
        <section className="overflow-hidden rounded-lg border border-slate-800 bg-[#111b29] text-slate-100">
          <div className="flex items-center justify-between border-b border-slate-700 px-4 py-3">
            <button type="button" onClick={() => setSqlOpen((open) => !open)} className="flex items-center gap-2 text-sm font-medium">
              <ChevronDown className={`size-4 transition ${sqlOpen ? "" : "-rotate-90"}`} /> Generated SQL
            </button>
            <button
              type="button"
              onClick={copySql}
              aria-label={copied ? "SQL copied" : "Copy SQL"}
              title={copied ? "Copied" : "Copy SQL"}
              className="rounded-md p-1.5 text-slate-400 transition hover:bg-slate-700 hover:text-white"
            >
              {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
            </button>
          </div>
          {sqlOpen && <pre className="max-h-72 overflow-auto p-4 text-xs leading-6 text-cyan-100"><code>{result.sql}</code></pre>}
        </section>
      )}
    </section>
  );
}
