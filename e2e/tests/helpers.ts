import { expect, type Page, type Route } from "@playwright/test";

export const COMPOSER = /ask a question about your fleet data/i;

export async function ask(page: Page, question: string) {
  await page.getByLabel(COMPOSER).fill(question);
  await page.getByRole("button", { name: /run analytics query/i }).click();
}

export function results(page: Page) {
  return page.getByRole("region", { name: "Analytics results" });
}

export async function expectAnswers(page: Page, count: number) {
  await expect(results(page)).toHaveCount(count);
}

export function jsonError(route: Route, status: number, code: string, message: string, headers: Record<string, string> = {}) {
  return route.fulfill({
    status,
    contentType: "application/json",
    headers,
    body: JSON.stringify({ error: { code, message, request_id: "e2e-request" } }),
  });
}

/** A syntactically valid ask response with `rowCount` rows, for tests that need a large result. */
export function fakeAskResponse(rowCount: number, overrides: Record<string, unknown> = {}) {
  const rows = Array.from({ length: rowCount }, (_, index) => ({
    customer_name: `Customer ${index + 1}`,
    revenue: 1000 + index,
  }));
  return {
    question: "Revenue by customer",
    sql: "SELECT customer_name, revenue FROM fake",
    explanation: "Revenue by customer.",
    tables_used: ["invoices"],
    schema_context: ["invoices"],
    provider: "e2e",
    confidence: null,
    request_id: "e2e-ask",
    columns: ["customer_name", "revenue"],
    rows,
    row_count: rowCount,
    execution_time_ms: 12,
    truncated: false,
    summary: "Customer 1 had the lowest revenue.",
    kpi: null,
    visualization: {
      type: "bar",
      title: "Revenue by Customer",
      x_axis: { field: "customer_name", format: "text" },
      y_axis: { field: "revenue", format: "currency" },
      series: [],
    },
    warnings: [],
    ...overrides,
  };
}
