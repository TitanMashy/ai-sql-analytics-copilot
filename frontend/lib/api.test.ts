import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, askQuestion } from "@/lib/api";
import { clearAuthToken, setAuthToken } from "@/lib/auth";
import { buildMockAskResponse } from "@/lib/mock-data";

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 503 ? "Service Unavailable" : "OK",
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response;
}

describe("analytics API client", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    clearAuthToken();
  });

  it("sends the stored access token as a bearer credential", async () => {
    setAuthToken("  token-abc  ");
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(buildMockAskResponse("Revenue")));

    await askQuestion({ question: "Revenue" });

    const init = vi.mocked(fetch).mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer token-abc");
  });

  it("sends no Authorization header when there is no token", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(buildMockAskResponse("Revenue")));

    await askQuestion({ question: "Revenue" });

    const init = vi.mocked(fetch).mock.calls[0][1] as RequestInit;
    expect(init.headers as Record<string, string>).not.toHaveProperty("Authorization");
  });

  it("reports a 401 as a non-retryable authentication error", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({
      error: { code: "UNAUTHENTICATED", message: "Authentication is required.", request_id: "r-1" },
    }, 401));

    await expect(askQuestion({ question: "Revenue" })).rejects.toMatchObject({
      code: "UNAUTHENTICATED",
      retryable: false,
      requestId: "r-1",
    });
  });

  it("exposes debug details and Retry-After when the backend provides them", async () => {
    const response = jsonResponse({
      error: {
        code: "QUERY_GENERATION_FAILED",
        message: "I couldn't produce a valid query for that question.",
        request_id: "r-2",
        debug: { sql: "SELECT missing FROM vehicles", last_error: "Unknown column reference" },
      },
    }, 422);
    vi.mocked(fetch).mockResolvedValueOnce(response);
    await expect(askQuestion({ question: "Impossible" })).rejects.toMatchObject({
      code: "QUERY_GENERATION_FAILED",
      retryable: false,
      debug: { sql: "SELECT missing FROM vehicles", last_error: "Unknown column reference" },
    });

    const limited = {
      ...jsonResponse({ error: { code: "RATE_LIMIT_EXCEEDED", message: "Slow down." } }, 429),
      headers: new Headers({ "Retry-After": "17" }),
    } as unknown as Response;
    vi.mocked(fetch).mockResolvedValueOnce(limited);
    await expect(askQuestion({ question: "Revenue" })).rejects.toMatchObject({
      code: "RATE_LIMIT_EXCEEDED",
      retryable: true,
      retryAfterSeconds: 17,
    });
  });

  it("defaults the truncated flag and accepts multi-series visualizations", async () => {
    const response = buildMockAskResponse("Show results") as unknown as Record<string, unknown>;
    delete response.truncated;
    response.visualization = {
      type: "line",
      title: "Revenue and cost by month",
      x_axis: { field: "month", format: "text" },
      y_axis: { field: "revenue", format: "currency" },
      series: [
        { field: "revenue", format: "currency" },
        { field: "cost", format: "currency" },
      ],
    };
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(response));

    const result = await askQuestion({ question: "Show results" });

    expect(result.truncated).toBe(false);
    expect(result.visualization?.series).toHaveLength(2);
  });

  it("drops visualizations whose series are malformed", async () => {
    const response = buildMockAskResponse("Show results") as unknown as Record<string, unknown>;
    response.visualization = {
      type: "line",
      title: "Broken",
      x_axis: { field: "month" },
      y_axis: { field: "revenue" },
      series: [{ nope: true }],
    };
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(response));

    const result = await askQuestion({ question: "Show results" });

    expect(result.visualization).toBeNull();
  });

  it("preserves structured backend error codes and request IDs", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({
      error: {
        code: "QUERY_SECURITY_ERROR",
        message: "The query is not permitted.",
        request_id: "request-123",
      },
    }, 400));

    await expect(askQuestion({ question: "List secrets" })).rejects.toMatchObject({
      code: "QUERY_SECURITY_ERROR",
      requestId: "request-123",
      retryable: false,
    });
  });

  it("maps network and timeout failures to retryable API errors", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new TypeError("offline"));
    await expect(askQuestion({ question: "Revenue" })).rejects.toMatchObject({
      code: "NETWORK_ERROR",
      retryable: true,
    });

    vi.mocked(fetch).mockRejectedValueOnce(Object.assign(new Error("timed out"), { name: "TimeoutError" }));
    await expect(askQuestion({ question: "Revenue" })).rejects.toMatchObject({
      code: "REQUEST_TIMEOUT",
      retryable: true,
    });
  });

  it("rejects malformed response bodies", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ question: "Revenue" }));

    await expect(askQuestion({ question: "Revenue" })).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
    });
  });

  it("accepts empty results and safely drops invalid visualization metadata", async () => {
    const response = buildMockAskResponse("Show results");
    response.rows = [];
    response.columns = [];
    response.row_count = 0;
    response.visualization = {
      ...response.visualization!,
      type: "heatmap" as never,
    };
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(response));

    const result = await askQuestion({ question: "Show results" });

    expect(result.rows).toEqual([]);
    expect(result.visualization).toBeNull();
  });

  it("marks unreadable JSON as an invalid response", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: vi.fn().mockRejectedValue(new SyntaxError("bad JSON")),
    } as unknown as Response);

    const request = askQuestion({ question: "Revenue" });
    await expect(request).rejects.toBeInstanceOf(ApiError);
    await expect(request).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });
});
