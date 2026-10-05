import { describe, expect, it } from "vitest";

import { CHART_PALETTE, colorAt, formatAxisLabel, resolveSeries, sortByField } from "@/lib/chart-utils";
import type { VisualizationResponse } from "@/types/api";

describe("chart palette", () => {
  it("has enough distinct colours that a six-slice pie never repeats one", () => {
    expect(new Set(CHART_PALETTE).size).toBe(CHART_PALETTE.length);
    expect(CHART_PALETTE.length).toBeGreaterThanOrEqual(6);

    const sliceColours = Array.from({ length: 6 }, (_, index) => colorAt(index));
    expect(new Set(sliceColours).size).toBe(6);
  });

  it("wraps around instead of failing for unusually many series", () => {
    expect(colorAt(CHART_PALETTE.length)).toBe(colorAt(0));
  });
});

describe("resolveSeries", () => {
  const base: VisualizationResponse = {
    type: "bar",
    title: "Revenue by customer",
    x_axis: { field: "customer", format: "text" },
    y_axis: { field: "revenue", format: "currency" },
  };

  it("uses the y axis for a single measure", () => {
    expect(resolveSeries(base)).toEqual([{ field: "revenue", format: "currency" }]);
  });

  it("uses every series when the backend sends several", () => {
    const series = [
      { field: "revenue", format: "currency" as const },
      { field: "cost", format: "currency" as const },
    ];

    expect(resolveSeries({ ...base, series })).toEqual(series);
  });

  it("falls back to a default field when there is no y axis", () => {
    expect(resolveSeries({ type: "bar", title: "x" })).toEqual([{ field: "value" }]);
  });
});

describe("sortByField", () => {
  it("orders ISO timestamps and numbers without mutating the input", () => {
    const rows = [
      { month: "2025-03-01T00:00:00+00:00", value: 3 },
      { month: "2025-01-01T00:00:00+00:00", value: 1 },
      { month: "2025-02-01T00:00:00+00:00", value: 2 },
    ];

    expect(sortByField(rows, "month").map((row) => row.value)).toEqual([1, 2, 3]);
    expect(sortByField(rows, "value").map((row) => row.value)).toEqual([1, 2, 3]);
    expect(rows.map((row) => row.value)).toEqual([3, 1, 2]);
  });

  it("puts missing values last", () => {
    const rows = [{ day: null }, { day: "2025-01-02" }, { day: "2025-01-01" }];

    expect(sortByField(rows, "day").map((row) => row.day)).toEqual(["2025-01-01", "2025-01-02", null]);
  });
});

describe("formatAxisLabel", () => {
  it("shortens midnight timestamps to dates", () => {
    expect(formatAxisLabel("2025-03-01T00:00:00+00:00")).toBe("2025-03-01");
    expect(formatAxisLabel("2025-03-01T00:00:00Z")).toBe("2025-03-01");
  });

  it("leaves other values alone", () => {
    expect(formatAxisLabel("2025-03-01T08:30:00+00:00")).toBe("2025-03-01T08:30:00+00:00");
    expect(formatAxisLabel("Northstar")).toBe("Northstar");
    expect(formatAxisLabel(null)).toBe("");
  });
});
