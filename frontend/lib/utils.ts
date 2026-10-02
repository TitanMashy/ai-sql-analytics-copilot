export function cn(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

export function formatMetricValue(value: number | string | null | undefined, format: string) {
  if (value === null || value === undefined || value === "") return "—";

  const numeric = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(numeric)) {
    return String(value);
  }

  switch (format) {
    case "currency":
      return new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: numeric >= 1000 ? 0 : 2,
      }).format(numeric);
    case "percentage":
      return `${numeric.toFixed(1)}%`;
    case "integer":
      return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(numeric);
    case "decimal":
      return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(numeric);
    default:
      return String(value);
  }
}

export function formatCompactCurrency(value: number | string | null | undefined) {
  if (value === null || value === undefined || value === "") return "—";
  const numeric = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(numeric)) return String(value);

  if (Math.abs(numeric) >= 1_000_000) {
    return `$${(numeric / 1_000_000).toFixed(1)}M`;
  }
  if (Math.abs(numeric) >= 1_000) {
    return `$${(numeric / 1_000).toFixed(1)}K`;
  }
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(numeric);
}

export function formatLabel(value: string) {
  return value
    .replace(/_/g, " ")
    .replace(/\s+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}
