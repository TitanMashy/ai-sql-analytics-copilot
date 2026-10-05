import type { VisualizationAxisResponse, VisualizationResponse } from "@/types/api";

/**
 * Categorical chart colours. The backend plots at most six pie slices and a handful of series,
 * so eight distinct colours guarantee that no colour repeats inside one chart.
 */
export const CHART_PALETTE = [
  "#2563eb",
  "#10b981",
  "#f59e0b",
  "#8b5cf6",
  "#ef4444",
  "#0891b2",
  "#db2777",
  "#65a30d",
] as const;

export function colorAt(index: number): string {
  return CHART_PALETTE[index % CHART_PALETTE.length];
}

/** The measures a chart plots: every series when there are several, otherwise the y axis. */
export function resolveSeries(visualization: VisualizationResponse): VisualizationAxisResponse[] {
  if (visualization.series && visualization.series.length > 0) {
    return visualization.series;
  }
  return visualization.y_axis ? [visualization.y_axis] : [{ field: "value" }];
}

function compareValues(left: unknown, right: unknown): number {
  if (left === right) return 0;
  if (left === null || left === undefined) return 1;
  if (right === null || right === undefined) return -1;
  if (typeof left === "number" && typeof right === "number") return left - right;
  // ISO-8601 timestamps sort correctly as strings.
  return String(left) < String(right) ? -1 : 1;
}

/** A sorted copy, so time series always read left to right whatever order the SQL returned. */
export function sortByField<T extends Record<string, unknown>>(rows: T[], field: string): T[] {
  return [...rows].sort((left, right) => compareValues(left[field], right[field]));
}

const MIDNIGHT_TIMESTAMP = /^(\d{4}-\d{2}-\d{2})T00:00:00(?:\.0+)?(?:Z|[+-]00:?00)?$/;

/** Shortens midnight ISO timestamps (what date_trunc returns) to a plain date for axis labels. */
export function formatAxisLabel(value: unknown): string {
  const text = String(value ?? "");
  const match = MIDNIGHT_TIMESTAMP.exec(text);
  return match ? match[1] : text;
}
