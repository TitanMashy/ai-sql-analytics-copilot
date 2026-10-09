import { getAuthToken } from "@/lib/auth";
import {
  anyOf,
  arrayOf,
  isFiniteNumber,
  isNonNegativeNumber,
  isNull,
  isRecord,
  isString,
  oneOf,
  optional,
  shape,
  stringArray,
  type Check,
} from "@/lib/schema";
import type {
  AskResponse,
  BusinessDefinitionsResponse,
  ConversationResponse,
  ErrorDebug,
  FeedbackRequest,
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

function authHeaders(): Record<string, string> {
  const token = getAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
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

/** Builds the structured error for a non-2xx response, whatever its body looks like. */
function errorFromResponse(response: Response, body: unknown): ApiError {
  const errorBody = isRecord(body) && isRecord(body.error) ? body.error : {};
  const retryable = response.status === 408 || response.status === 429 || response.status >= 500;
  return new ApiError(
    typeof errorBody.message === "string" ? errorBody.message : "The analytics request failed.",
    typeof errorBody.code === "string" ? errorBody.code : `HTTP_${response.status}`,
    typeof errorBody.request_id === "string" ? errorBody.request_id : null,
    retryable,
    parseDebug(errorBody.debug),
    parseRetryAfter(response),
  );
}

async function send(path: string, init?: RequestInit): Promise<Response> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), requestTimeoutMs);
  try {
    return await fetch(`${apiBaseUrl}${path}`, {
      ...init,
      signal: init?.signal ?? controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...authHeaders(),
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
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await send(path, init);

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new ApiError("The analytics service returned an unreadable response.", "INVALID_RESPONSE");
  }

  if (!response.ok) {
    throw errorFromResponse(response, body);
  }
  return body as T;
}

// -- response schemas (field lists mirror contracts/api-contract.json) ------------------------

const valueFormats = ["currency", "integer", "decimal", "percentage", "text"] as const;
const visualizationTypes = ["table", "kpi", "bar", "line", "area", "pie"] as const;

const axisSchema: Check = shape({
  field: isString,
  format: optional(oneOf(...valueFormats)),
});

const visualizationSchema: Check = shape({
  type: oneOf(...visualizationTypes),
  title: isString,
  x_axis: optional(axisSchema),
  y_axis: optional(axisSchema),
  series: optional(arrayOf(axisSchema)),
});

const kpiSchema: Check = shape({
  label: isString,
  value: anyOf(isString, isFiniteNumber, isNull),
  format: oneOf(...valueFormats),
});

const askResponseSchema: Check = shape({
  question: isString,
  sql: isString,
  explanation: isString,
  tables_used: stringArray,
  schema_context: stringArray,
  provider: isString,
  columns: stringArray,
  rows: arrayOf(isRecord),
  row_count: isNonNegativeNumber,
  execution_time_ms: isNonNegativeNumber,
  warnings: stringArray,
});

const conversationSchema: Check = shape({
  conversation_id: isString,
  turns: arrayOf(
    shape({
      conversation_id: isString,
      role: oneOf("user", "assistant", "system"),
      content: isString,
    }),
  ),
});

const businessDefinitionsSchema: Check = shape({
  definitions: arrayOf(shape({ name: isString, definition: isString })),
  examples: stringArray,
});

function normalizeAskResponse(value: unknown): AskResponse {
  if (!askResponseSchema(value)) {
    throw new ApiError("The analytics service returned an invalid result.", "INVALID_RESPONSE");
  }
  const body = value as Record<string, unknown>;
  // Chart and KPI metadata are optional extras: a malformed one is dropped, and the result table
  // is still shown.
  return {
    ...body,
    truncated: body.truncated === true,
    kpi: kpiSchema(body.kpi) ? body.kpi : null,
    visualization: visualizationSchema(body.visualization) ? body.visualization : null,
  } as AskResponse;
}

function normalizeConversation(value: unknown): ConversationResponse {
  if (!conversationSchema(value)) {
    throw new ApiError("The analytics service returned an invalid conversation.", "INVALID_RESPONSE");
  }
  const body = value as Record<string, unknown>;
  return {
    conversation_id: body.conversation_id as string,
    turns: body.turns as ConversationResponse["turns"],
    context: typeof body.context === "string" ? body.context : null,
  };
}

// -- endpoints ------------------------------------------------------------------------------

export async function createConversation(): Promise<ConversationResponse> {
  const response = await apiFetch<unknown>("/api/v1/analytics/conversations", {
    method: "POST",
  });
  return normalizeConversation(response);
}

export async function getConversation(id: string): Promise<ConversationResponse> {
  return normalizeConversation(
    await apiFetch<unknown>(`/api/v1/analytics/conversations/${encodeURIComponent(id)}`),
  );
}

export async function askQuestion(payload: QuestionRequest): Promise<AskResponse> {
  return normalizeAskResponse(await apiFetch<unknown>("/api/v1/analytics/ask", {
    method: "POST",
    body: JSON.stringify(payload),
  }));
}

/** Deletes a conversation and its server-side history. One that is already gone counts as deleted. */
export async function deleteConversation(id: string): Promise<void> {
  if (!id) return;
  const response = await send(`/api/v1/analytics/conversations/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  if (!response.ok && response.status !== 404) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      // The status alone is enough to report.
    }
    throw errorFromResponse(response, body);
  }
}

export async function submitFeedback(payload: FeedbackRequest): Promise<void> {
  const body = await apiFetch<unknown>("/api/v1/analytics/feedback", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!isRecord(body) || !isString(body.status)) {
    throw new ApiError("The analytics service returned an invalid response.", "INVALID_RESPONSE");
  }
}

export async function getBusinessDefinitions(): Promise<BusinessDefinitionsResponse> {
  const body = await apiFetch<unknown>("/api/v1/schema/business-definitions");
  if (!businessDefinitionsSchema(body)) {
    throw new ApiError("The analytics service returned invalid definitions.", "INVALID_RESPONSE");
  }
  return body as BusinessDefinitionsResponse;
}
