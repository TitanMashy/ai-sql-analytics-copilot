import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { buildMockAskResponse } from "@/lib/mock-data";
import type { AskResponse } from "@/types/api";

import { AnalyticsResults, PAGE_SIZE } from "./analytics-results";

function bigResult(rowCount: number, overrides: Partial<AskResponse> = {}): AskResponse {
  const base = buildMockAskResponse("What are the top 10 customers by revenue?");
  const rows = Array.from({ length: rowCount }, (_, index) => ({
    customer_name: `Customer ${index + 1}`,
    revenue: 1000 + index,
  }));
  return { ...base, rows, row_count: rowCount, ...overrides };
}

describe("AnalyticsResults", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders only one page of a large result", () => {
    render(<AnalyticsResults result={bigResult(1000)} />);

    const table = screen.getByRole("table");
    // One header row plus a page of body rows, not 1,000.
    expect(within(table).getAllByRole("row")).toHaveLength(PAGE_SIZE + 1);
    expect(screen.getByText(/Rows 1–50 of 1,000/)).toBeInTheDocument();
    expect(screen.getByText("Page 1 of 20")).toBeInTheDocument();
  });

  it("moves between pages and never walks off the ends", () => {
    render(<AnalyticsResults result={bigResult(120)} />);
    const previous = screen.getByRole("button", { name: "Previous" });
    const next = screen.getByRole("button", { name: "Next" });

    expect(previous).toBeDisabled();
    fireEvent.click(next);
    expect(screen.getByText("Customer 51")).toBeInTheDocument();
    expect(screen.queryByText("Customer 1")).not.toBeInTheDocument();
    fireEvent.click(next);
    expect(screen.getByText("Page 3 of 3")).toBeInTheDocument();
    expect(screen.getByText(/Rows 101–120 of 120/)).toBeInTheDocument();
    expect(next).toBeDisabled();
    fireEvent.click(previous);
    expect(screen.getByText("Page 2 of 3")).toBeInTheDocument();
  });

  it("shows no pager for a result that fits on one page", () => {
    render(<AnalyticsResults result={bigResult(PAGE_SIZE)} />);

    expect(screen.queryByRole("navigation", { name: "Result pages" })).not.toBeInTheDocument();
  });

  it("exports the whole result, not just the visible page, as CSV", () => {
    const created: Blob[] = [];
    // jsdom has no object URLs; add just the two methods the download helper uses.
    Object.assign(URL, {
      createObjectURL: (blob: Blob) => {
        created.push(blob);
        return "blob:test";
      },
      revokeObjectURL: vi.fn(),
    });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    render(<AnalyticsResults result={bigResult(120)} />);

    fireEvent.click(screen.getByRole("button", { name: /export csv/i }));

    expect(click).toHaveBeenCalledTimes(1);
    expect(created).toHaveLength(1);
    expect(created[0].type).toBe("text/csv;charset=utf-8");
  });

  it("explains a truncated result and does not repeat the backend's warning", () => {
    const result = bigResult(1000, {
      truncated: true,
      warnings: ["Results were truncated to the first 1,000 rows; refine the question.", "Column 'x' contains many NULL values."],
    });
    render(<AnalyticsResults result={result} />);

    expect(screen.getByText(/The result was cut at 1,000 rows/)).toBeInTheDocument();
    expect(screen.getByText("Column 'x' contains many NULL values.")).toBeInTheDocument();
    expect(screen.queryByText(/Results were truncated to the first/)).not.toBeInTheDocument();
    expect(screen.getByText("1000 rows (truncated)")).toBeInTheDocument();
  });

  it("gives the chart an accessible description and a scrollable, labelled table", () => {
    render(<AnalyticsResults result={bigResult(5)} />);

    expect(screen.getByRole("figure", { name: /bar chart: top customers by revenue/i })).toBeInTheDocument();
    expect(screen.getByLabelText("Result table, scrollable")).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getAllByRole("columnheader")).toHaveLength(2);
  });

  it("hides the feedback buttons unless the caller can record feedback and the answer has an id", () => {
    const { rerender } = render(<AnalyticsResults result={bigResult(2)} />);
    expect(screen.queryByRole("button", { name: "Helpful" })).not.toBeInTheDocument();

    rerender(<AnalyticsResults result={bigResult(2, { request_id: null })} onFeedback={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Helpful" })).not.toBeInTheDocument();

    rerender(<AnalyticsResults result={bigResult(2)} onFeedback={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Helpful" })).toBeInTheDocument();
  });

  it("collapses the SQL by default and toggles it", () => {
    render(<AnalyticsResults result={bigResult(2)} />);
    const toggle = screen.getByRole("button", { name: /generated sql/i });

    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/SELECT c.company_name/)).not.toBeInTheDocument();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/SELECT c.company_name/)).toBeInTheDocument();
  });

  it("shows an empty state instead of an empty table", () => {
    render(<AnalyticsResults result={bigResult(0)} />);

    expect(screen.getByText("No rows returned for this query.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
