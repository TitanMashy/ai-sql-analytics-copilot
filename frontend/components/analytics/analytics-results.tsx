"use client";

import { useState } from "react";
import {
  Check,
  ChevronDown,
  Copy,
  Database,
  Download,
  Gauge,
  Rows3,
  ThumbsDown,
  ThumbsUp,
  Timer,
  TriangleAlert,
} from "lucide-react";

import { ChartRenderer } from "@/components/charts/chart-renderer";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { csvFilename, downloadCsv, toCsv } from "@/lib/csv";
import { formatLabel, formatMetricValue } from "@/lib/utils";
import type { AskResponse } from "@/types/api";

/** Rows rendered per page. Pagination keeps a 1,000-row result from putting 1,000 rows in the DOM. */
export const PAGE_SIZE = 50;

interface AnalyticsResultsProps {
  result: AskResponse;
  /** Called with the rating; omit to hide the feedback buttons. */
  onFeedback?: (helpful: boolean) => Promise<void>;
}

function formatCell(value: unknown) {
  if (typeof value === "number") return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value);
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

type FeedbackState = "idle" | "sending" | "thanks" | "failed";

export function AnalyticsResults({ result, onFeedback }: AnalyticsResultsProps) {
  const [sqlOpen, setSqlOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [page, setPage] = useState(0);
  const [feedback, setFeedback] = useState<FeedbackState>("idle");

  const pageCount = Math.max(1, Math.ceil(result.rows.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount - 1);
  const firstRow = currentPage * PAGE_SIZE;
  const visibleRows = result.rows.slice(firstRow, firstRow + PAGE_SIZE);
  // The truncation banner replaces the backend's matching warning, so it is not shown twice.
  const warnings = result.warnings.filter((warning) => !warning.startsWith("Results were truncated"));
  const chartLabel = `${result.visualization?.type ?? "chart"} chart: ${result.visualization?.title ?? "query result"}. The same data is in the result table below.`;

  async function copySql() {
    try {
      await navigator.clipboard.writeText(result.sql);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }

  function exportCsv() {
    downloadCsv(csvFilename(result.visualization?.title ?? result.question), toCsv(result.columns, result.rows));
  }

  async function sendFeedback(helpful: boolean) {
    if (!onFeedback || feedback === "sending" || feedback === "thanks") return;
    setFeedback("sending");
    try {
      await onFeedback(helpful);
      setFeedback("thanks");
    } catch {
      setFeedback("failed");
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
          <span className="flex items-center gap-1.5"><Rows3 className="size-3.5" /> {result.row_count} rows{result.truncated ? " (truncated)" : ""}</span>
          <span className="flex items-center gap-1.5"><Database className="size-3.5" /> {result.tables_used.join(", ") || "Analytics"}</span>
        </div>
      </div>

      {result.summary && (
        <div className="flex gap-3 rounded-lg border-l-4 border-cyan-600 bg-cyan-50/70 px-4 py-3">
          <Gauge className="mt-0.5 size-4 shrink-0 text-cyan-800" />
          <p className="text-sm leading-6 text-slate-700">{result.summary}</p>
        </div>
      )}

      {result.truncated && (
        <div role="status" className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <TriangleAlert className="mt-0.5 size-4 shrink-0" />
          <p>
            The result was cut at {result.row_count.toLocaleString()} rows. Narrow the question (a date range, a customer, a top-N)
            to see everything you need.
          </p>
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
        <figure aria-label={chartLabel} className="rounded-lg border border-slate-200 bg-white p-4 sm:p-5">
          <ChartErrorBoundary key={`${result.question}-${result.row_count}`}>
            <ChartRenderer data={result.rows} visualization={result.visualization} label={chartLabel} />
          </ChartErrorBoundary>
          <figcaption className="sr-only">{chartLabel}</figcaption>
        </figure>
      )}

      {result.rows.length > 0 ? (
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-4 py-3">
            <h3 className="text-sm font-semibold text-slate-800">Result set</h3>
            <div className="flex items-center gap-3 text-xs text-slate-500">
              <span aria-live="polite">
                Rows {(firstRow + 1).toLocaleString()}–{(firstRow + visibleRows.length).toLocaleString()} of {result.rows.length.toLocaleString()}
              </span>
              <button
                type="button"
                onClick={exportCsv}
                className="flex items-center gap-1.5 rounded-md border border-slate-200 px-2.5 py-1.5 font-medium text-slate-700 hover:bg-slate-50"
              >
                <Download className="size-3.5" /> Export CSV
              </button>
            </div>
          </div>
          <div className="max-h-[420px] overflow-auto" tabIndex={0} aria-label="Result table, scrollable">
            <table className="min-w-full text-left text-sm">
              <caption className="sr-only">{result.visualization?.title ?? "Query result"}</caption>
              <thead className="sticky top-0 bg-slate-50 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                <tr>
                  {result.columns.map((column) => (
                    <th key={column} scope="col" className="whitespace-nowrap px-4 py-3">{formatLabel(column)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {visibleRows.map((row, index) => (
                  <tr key={firstRow + index} className="border-t border-slate-100 even:bg-slate-50/50">
                    {result.columns.map((column) => (
                      <td key={column} className="max-w-[360px] whitespace-nowrap px-4 py-3 text-slate-700">
                        {formatCell(row[column])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {pageCount > 1 && (
            <nav aria-label="Result pages" className="flex items-center justify-between border-t border-slate-200 px-4 py-2.5 text-xs text-slate-600">
              <button
                type="button"
                onClick={() => setPage(currentPage - 1)}
                disabled={currentPage === 0}
                className="rounded-md border border-slate-200 px-3 py-1.5 font-medium hover:bg-slate-50 disabled:opacity-40"
              >
                Previous
              </button>
              <span>Page {currentPage + 1} of {pageCount}</span>
              <button
                type="button"
                onClick={() => setPage(currentPage + 1)}
                disabled={currentPage >= pageCount - 1}
                className="rounded-md border border-slate-200 px-3 py-1.5 font-medium hover:bg-slate-50 disabled:opacity-40"
              >
                Next
              </button>
            </nav>
          )}
        </div>
      ) : (
        <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-sm text-slate-500">No rows returned for this query.</div>
      )}

      {warnings.length > 0 && (
        <div role="status" className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-amber-900">Data notes</p>
          <ul className="mt-2 list-inside list-disc space-y-1 text-sm text-amber-900">
            {warnings.map((warning, index) => <li key={`${index}-${warning}`}>{warning}</li>)}
          </ul>
        </div>
      )}

      {onFeedback && result.request_id && (
        <div role="group" aria-label="Was this answer helpful?" className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
          {feedback === "thanks" ? (
            <span role="status">Thanks for the feedback.</span>
          ) : (
            <>
              <span aria-hidden="true">Was this answer helpful?</span>
              <button
                type="button"
                aria-label="Helpful"
                disabled={feedback === "sending"}
                onClick={() => sendFeedback(true)}
                className="rounded-md border border-slate-200 p-1.5 text-slate-600 hover:bg-slate-50 disabled:opacity-50"
              >
                <ThumbsUp className="size-3.5" />
              </button>
              <button
                type="button"
                aria-label="Not helpful"
                disabled={feedback === "sending"}
                onClick={() => sendFeedback(false)}
                className="rounded-md border border-slate-200 p-1.5 text-slate-600 hover:bg-slate-50 disabled:opacity-50"
              >
                <ThumbsDown className="size-3.5" />
              </button>
              {feedback === "failed" && <span role="alert" className="text-red-700">Could not send feedback. Try again.</span>}
            </>
          )}
        </div>
      )}

      {result.sql && (
        <section className="overflow-hidden rounded-lg border border-slate-800 bg-[#111b29] text-slate-100">
          <div className="flex items-center justify-between border-b border-slate-700 px-4 py-3">
            <button type="button" onClick={() => setSqlOpen((open) => !open)} aria-expanded={sqlOpen} className="flex items-center gap-2 text-sm font-medium">
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
