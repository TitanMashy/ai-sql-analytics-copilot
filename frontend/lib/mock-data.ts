import type { AskResponse } from "@/types/api";

export function buildMockAskResponse(question: string): AskResponse {
  const normalized = question.toLowerCase();

  if (normalized.includes("active vehicles")) {
    return {
      question,
      sql: "SELECT COUNT(*) AS active_vehicle_count FROM vehicles WHERE status = 'active';",
      explanation: "Count active fleet assets by status.",
      tables_used: ["vehicles"],
      schema_context: ["vehicles"],
      provider: "mock",
      confidence: 0.96,
      request_id: "req-mock-1",
      columns: ["active_vehicle_count"],
      rows: [{ active_vehicle_count: 128 }],
      row_count: 1,
      execution_time_ms: 189,
      truncated: false,
      summary: "We currently have 128 active vehicles across the fleet.",
      kpi: {
        label: "Active Vehicles",
        value: 128,
        format: "integer",
      },
      visualization: {
        type: "kpi",
        title: "Fleet activity",
        x_axis: null,
        y_axis: null,
      },
      warnings: [],
    };
  }

  if (normalized.includes("top 10 customers") || normalized.includes("revenue")) {
    return {
      question,
      sql: "SELECT c.company_name AS customer_name, SUM(i.total_amount) AS revenue FROM invoices i JOIN customers c ON c.id = i.customer_id GROUP BY c.company_name ORDER BY revenue DESC LIMIT 10;",
      explanation: "Summarize revenue by customer and rank the top accounts.",
      tables_used: ["customers", "invoices"],
      schema_context: ["customers", "invoices"],
      provider: "mock",
      confidence: 0.95,
      request_id: "req-mock-2",
      columns: ["customer_name", "revenue"],
      rows: [
        { customer_name: "Northstar Logistics", revenue: 1835000 },
        { customer_name: "Summit Transport", revenue: 1670000 },
        { customer_name: "BlueLine Freight", revenue: 1542000 },
        { customer_name: "Harbor Fleet", revenue: 1429000 },
      ],
      row_count: 4,
      execution_time_ms: 242,
      truncated: false,
      summary: "Revenue was strongest among Northstar Logistics, Summit Transport, and BlueLine Freight.",
      kpi: {
        label: "Total Revenue",
        value: 6476000,
        format: "currency",
      },
      visualization: {
        type: "bar",
        title: "Top customers by revenue",
        x_axis: { field: "customer_name", format: "text" },
        y_axis: { field: "revenue", format: "currency" },
      },
      warnings: [],
    };
  }

  return {
    question,
    sql: "SELECT DATE_TRUNC('month', trip_date) AS month, SUM(revenue) AS revenue FROM trips GROUP BY DATE_TRUNC('month', trip_date) ORDER BY month DESC LIMIT 6;",
    explanation: "Prepare a monthly trend for the requested fleet metric.",
    tables_used: ["trips"],
    schema_context: ["trips"],
    provider: "mock",
    confidence: 0.89,
    request_id: "req-mock-3",
    columns: ["month", "revenue"],
    rows: [
      { month: "2025-05", revenue: 820000 },
      { month: "2025-04", revenue: 790000 },
      { month: "2025-03", revenue: 760000 },
      { month: "2025-02", revenue: 705000 },
    ],
    row_count: 4,
    execution_time_ms: 214,
    truncated: false,
    summary: "Revenue is trending upward over the most recent months.",
    kpi: {
      label: "Monthly Revenue",
      value: 820000,
      format: "currency",
    },
    visualization: {
      type: "line",
      title: "Monthly revenue trend",
      x_axis: { field: "month", format: "text" },
      y_axis: { field: "revenue", format: "currency" },
    },
    warnings: [],
  };
}
