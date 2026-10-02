export type AnalyticsFormat = "currency" | "integer" | "decimal" | "percentage" | "text";

export interface KPIResponse {
  label: string;
  value: number | string | null;
  format: AnalyticsFormat;
}

export interface VisualizationAxisResponse {
  field: string;
  format?: AnalyticsFormat;
}

export interface VisualizationResponse {
  type: "table" | "kpi" | "bar" | "line" | "area" | "pie";
  title: string;
  x_axis?: VisualizationAxisResponse | null;
  y_axis?: VisualizationAxisResponse | null;
}

export interface GeneratedQueryResponse {
  question: string;
  sql: string;
  explanation: string;
  tables_used: string[];
  schema_context: string[];
  provider: string;
  confidence?: number | null;
}

export interface AskResponse extends GeneratedQueryResponse {
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  execution_time_ms: number;
  summary?: string | null;
  kpi?: KPIResponse | null;
  visualization?: VisualizationResponse | null;
  warnings: string[];
}

export interface ConversationTurn {
  conversation_id: string;
  role: "user" | "assistant" | "system";
  content: string;
}

export interface ConversationResponse {
  conversation_id: string;
  turns: ConversationTurn[];
  context?: string | null;
}

export interface QuestionRequest {
  question: string;
  conversation_id?: string;
  conversation_context?: string;
}
