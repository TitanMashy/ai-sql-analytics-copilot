/**
 * CSV export of a result set.
 *
 * Cells that start with `=`, `+`, `-`, `@`, tab, or carriage return are prefixed with an apostrophe:
 * spreadsheet programs treat those as formulas, so an exported value such as `=HYPERLINK(...)`
 * (from data or from a model-produced alias) must not execute when the file is opened.
 */
const FORMULA_PREFIXES = new Set(["=", "+", "-", "@", "\t", "\r"]);

function neutralize(text: string): string {
  return FORMULA_PREFIXES.has(text.charAt(0)) ? `'${text}` : text;
}

function escapeCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  const raw = typeof value === "number" ? String(value) : neutralize(String(value));
  return /[",\n\r]/.test(raw) ? `"${raw.replace(/"/g, '""')}"` : raw;
}

export function toCsv(columns: string[], rows: Record<string, unknown>[]): string {
  const header = columns.map((column) => escapeCell(column)).join(",");
  const lines = rows.map((row) => columns.map((column) => escapeCell(row[column])).join(","));
  return [header, ...lines].join("\r\n") + "\r\n";
}

export function csvFilename(title: string, now = new Date()): string {
  const slug = title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
  return `${slug || "analytics-result"}-${now.toISOString().slice(0, 10)}.csv`;
}

export function downloadCsv(filename: string, csv: string): void {
  // The BOM makes Excel read the file as UTF-8.
  const blob = new Blob(["﻿", csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
