import { getAuthToken } from "@/lib/auth";
import type {
  AskResponse,
  ConversationResponse,
  ErrorDebug,
  QuestionRequest,
} from "@/types/api";

const apiBaseUrl = process.env.NEXT_PUBLIC_API_URL ?? "";
// The backend gives up on a question after REQUEST_DEADLINE_SECONDS (25 by default). Keep this
// above that, so the server reports the timeout before the browser abandons the request.
const requestTimeoutMs = 30_000;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly requestId: string | null = null,
    readonly retryable = false,
    readonly debug: ErrorDebug | null = null,
    readonly retryAfterSeconds: number | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), requestTimeoutMs);
  let response: Response;
  try {
    const token = getAuthToken();
    response = await fetch(`${apiBaseUrl}${path}`, {
      ...init,
      signal: init?.signal ?? controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(init?.headers ?? {}),
      },
    });
  } catch (requestError) {
    const timedOut = requestError instanceof Error &&
      (requestError.name === "AbortError" || requestError.name === "TimeoutError");
    throw new ApiError(
      timedOut ? "The request timed out. You can retry it." : "Could not reach the analytics service.",
      timedOut ? "REQUEST_TIMEOUT" : "NETWORK_ERROR",
      null,
      true,
    );
  } finally {
    clearTimeout(timeout);
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new ApiError("The analytics service returned an unreadable response.", "INVALID_RESPONSE");
  }

  if (!response.ok) {
    const errorBody = isRecord(body) && isRecord(body.error) ? body.error : {};
    const retryable = response.status === 408 || response.status === 429 || response.status >= 500;
    throw new ApiError(
      typeof errorBody.message === "string" ? errorBody.message : "The analytics request failed.",
      typeof errorBody.code === "string" ? errorBody.code : `HTTP_${response.status}`,
      typeof errorBody.request_id === "string" ? errorBody.request_id : null,
      retryable,
      parseDebug(errorBody.debug),
      parseRetryAfter(response),
    );
  }

  return body as T;
}

function parseDebug(value: unknown): ErrorDebug | null {
  if (!isRecord(value)) return null;
  return {
    sql: typeof value.sql === "string" ? value.sql : undefined,
    last_error: typeof value.last_error === "string" ? value.last_error : undefined,
  };
}

function parseRetryAfter(response: Response): number | null {
  const header = response.headers?.get?.("Retry-After");
  const seconds = header ? Number(header) : Number.NaN;
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isVisualizationAxis(value: unknown): boolean {
  return value === null || (isRecord(value) && typeof value.field === "string");
}

function isValidVisualization(value: unknown): boolean {
  return isRecord(value) &&
    ["table", "kpi", "bar", "line", "area", "pie"].includes(String(value.type)) &&
    typeof value.title === "string" &&
    isVisualizationAxis(value.x_axis) &&
    isVisualizationAxis(value.y_axis) &&
    (value.series === undefined || (Array.isArray(value.series) && value.series.every(isVisualizationAxis)));
}

function isValidKpi(value: unknown): value is NonNullable<AskResponse["kpi"]> {
  return isRecord(value) &&
    typeof value.label === "string" &&
    (typeof value.value === "number" || typeof value.value === "string" || value.value === null) &&
    ["currency", "integer", "decimal", "percentage", "text"].includes(String(value.format));
}

function normalizeAskResponse(value: unknown): AskResponse {
  if (!isRecord(value) ||
    typeof value.question !== "string" ||
    typeof value.sql !== "string" ||
    typeof value.explanation !== "string" ||
    !isStringArray(value.tables_used) ||
    !isStringArray(value.schema_context) ||
    typeof value.provider !== "string" ||
    !isStringArray(value.columns) ||
    !Array.isArray(value.rows) ||
    !value.rows.every(isRecord) ||
    typeof value.row_count !== "number" || value.row_count < 0 ||
    typeof value.execution_time_ms !== "number" || value.execution_time_ms < 0 ||
    !Array.isArray(value.warnings) || !value.warnings.every((warning) => typeof warning === "string")) {
    throw new ApiError("The analytics service returned an invalid result.", "INVALID_RESPONSE");
  }

  return {
    ...value,
    truncated: value.truncated === true,
    kpi: isValidKpi(value.kpi) ? value.kpi : null,
    visualization: isValidVisualization(value.visualization)
      ? value.visualization as AskResponse["visualization"]
      : null,
  } as AskResponse;
}

function isConversationTurn(value: unknown): value is ConversationResponse["turns"][number] {
  return isRecord(value) &&
    typeof value.conversation_id === "string" &&
    ["user", "assistant", "system"].includes(String(value.role)) &&
    typeof value.content === "string";
}

function normalizeConversation(value: unknown): ConversationResponse {
  if (!isRecord(value) ||
    typeof value.conversation_id !== "string" ||
    !Array.isArray(value.turns) ||
    !value.turns.every(isConversationTurn)) {
    throw new ApiError("The analytics service returned an invalid conversation.", "INVALID_RESPONSE");
  }
  return {
    conversation_id: value.conversation_id,
    turns: value.turns,
    context: typeof value.context === "string" ? value.context : null,
  };
}

export async function createConversation(): Promise<ConversationResponse> {
  const response = await apiFetch<unknown>("/api/v1/analytics/conversations", {
    method: "POST",
  });
  return normalizeConversation(response);
}

export async function getConversation(id: string): Promise<ConversationResponse> {
  return normalizeConversation(await apiFetch<unknown>(`/api/v1/analytics/conversations/${id}`));
}

export async function askQuestion(payload: QuestionRequest): Promise<AskResponse> {
  return normalizeAskResponse(await apiFetch<unknown>("/api/v1/analytics/ask", {
    method: "POST",
    body: JSON.stringify(payload),
  }));
}

export async function deleteConversation(id: string): Promise<void> {
  if (!id) {
    return;
  }

  try {
    await fetch(`${apiBaseUrl}/api/v1/analytics/conversations/${id}`, {
      method: "DELETE",
    });
  } catch {
    // Best-effort only for the in-memory UI client; the backend does not yet expose a delete route.
  }
}

export async function getSchema(): Promise<Record<string, unknown>> {
  return apiFetch<Record<string, unknown>>("/api/v1/schema/tables");
}
