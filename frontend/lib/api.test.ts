import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, askQuestion } from "@/lib/api";
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
