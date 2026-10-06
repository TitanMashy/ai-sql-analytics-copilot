import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  askQuestion,
  createConversation,
  deleteConversation,
  getBusinessDefinitions,
  getConversation,
  submitFeedback,
} from "@/lib/api";
import type { AskResponse } from "@/types/api";
import { buildMockAskResponse } from "@/lib/mock-data";

import { AnalyticsDashboard } from "./analytics-dashboard";

vi.mock("@/lib/api", () => {
  class TestApiError extends Error {
    code = "TEST_ERROR";
    retryable = true;
    requestId: string | null = null;
    debug: { sql?: string } | null = null;
    retryAfterSeconds: number | null = null;
  }
  return {
    ApiError: TestApiError,
    askQuestion: vi.fn(),
    createConversation: vi.fn(),
    deleteConversation: vi.fn(),
    getBusinessDefinitions: vi.fn(),
    getConversation: vi.fn(),
    submitFeedback: vi.fn(),
  };
});

describe("AnalyticsDashboard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.sessionStorage.clear();
    window.localStorage.clear();
    vi.mocked(getBusinessDefinitions).mockResolvedValue({ definitions: [], examples: [] });
    vi.mocked(getConversation).mockRejectedValue(new Error("not found"));
    vi.mocked(deleteConversation).mockResolvedValue(undefined);
    vi.mocked(submitFeedback).mockResolvedValue(undefined);
    vi.mocked(createConversation).mockResolvedValue({
      conversation_id: "test-conversation",
      turns: [],
      context: "No prior conversation context.",
    });
    vi.mocked(askQuestion).mockImplementation(async ({ question }) => buildMockAskResponse(question));
  });

  it("submits a question and renders the analytics summary", async () => {
    render(<AnalyticsDashboard />);

    fireEvent.change(screen.getByLabelText(/ask a question about your fleet data/i), {
      target: { value: "What are the top 10 customers by revenue?" },
    });

    fireEvent.click(screen.getByRole("button", { name: /run analytics query/i }));

    await waitFor(() => {
      expect(screen.getByText(/total revenue/i)).toBeInTheDocument();
      expect(screen.getByRole("cell", { name: /northstar logistics/i })).toBeInTheDocument();
    });
  });

  it("shows backend errors instead of presenting mock analytics", async () => {
    vi.mocked(askQuestion).mockRejectedValueOnce(new Error("Analytics service unavailable."));
    render(<AnalyticsDashboard />);

    fireEvent.change(screen.getByLabelText(/ask a question about your fleet data/i), {
      target: { value: "What are the top 10 customers by revenue?" },
    });
    fireEvent.click(screen.getByRole("button", { name: /run analytics query/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Analytics service unavailable.");
    expect(screen.queryByRole("region", { name: "Analytics results" })).not.toBeInTheDocument();
  });

  it("retries a failed question without creating a duplicate user turn", async () => {
    vi.mocked(askQuestion)
      .mockRejectedValueOnce(new Error("Temporary network failure."))
      .mockImplementationOnce(async ({ question }) => buildMockAskResponse(question));
    render(<AnalyticsDashboard />);
    fireEvent.change(screen.getByLabelText(/ask a question about your fleet data/i), {
      target: { value: "What are the top 10 customers by revenue?" },
    });
    fireEvent.click(screen.getByRole("button", { name: /run analytics query/i }));

    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));

    await waitFor(() => expect(screen.getByRole("region", { name: "Analytics results" })).toBeInTheDocument());
    expect(askQuestion).toHaveBeenCalledTimes(2);
    expect(createConversation).toHaveBeenCalledTimes(1);
    expect(screen.getAllByText("What are the top 10 customers by revenue?")).toHaveLength(2);
  });

  it("shows conversation creation failures without asking analytics", async () => {
    vi.mocked(createConversation).mockRejectedValueOnce(new Error("Conversation service unavailable."));
    render(<AnalyticsDashboard />);
    fireEvent.change(screen.getByLabelText(/ask a question about your fleet data/i), {
      target: { value: "How many active vehicles do we have?" },
    });
    fireEvent.click(screen.getByRole("button", { name: /run analytics query/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Conversation service unavailable.");
    expect(askQuestion).not.toHaveBeenCalled();
  });

  it("renders empty results and falls back safely for invalid chart metadata", async () => {
    vi.mocked(askQuestion).mockImplementationOnce(async ({ question }) => ({
      ...buildMockAskResponse(question),
      rows: [],
      columns: [],
      row_count: 0,
      visualization: {
        type: "heatmap",
        title: "Unexpected chart",
        x_axis: null,
        y_axis: null,
      } as unknown as AskResponse["visualization"],
    }));
    render(<AnalyticsDashboard />);
    fireEvent.change(screen.getByLabelText(/ask a question about your fleet data/i), {
      target: { value: "Show an empty result" },
    });
    fireEvent.click(screen.getByRole("button", { name: /run analytics query/i }));

    expect(await screen.findByRole("region", { name: "Analytics results" })).toBeInTheDocument();
    expect(screen.getByText("0 rows")).toBeInTheDocument();
    expect(screen.queryByRole("application")).not.toBeInTheDocument();
  });

  it("ignores duplicate submit clicks while a request is pending", async () => {
    let resolveQuestion: ((result: AskResponse) => void) | undefined;
    vi.mocked(askQuestion).mockImplementationOnce(() => new Promise((resolve) => {
      resolveQuestion = resolve;
    }));
    render(<AnalyticsDashboard />);
    fireEvent.change(screen.getByLabelText(/ask a question about your fleet data/i), {
      target: { value: "What are the top 10 customers by revenue?" },
    });
    const submit = screen.getByRole("button", { name: /run analytics query/i });
    fireEvent.click(submit);
    fireEvent.click(submit);

    await waitFor(() => expect(askQuestion).toHaveBeenCalledTimes(1));
    resolveQuestion?.(buildMockAskResponse("What are the top 10 customers by revenue?"));
    await waitFor(() => expect(screen.getByRole("region", { name: "Analytics results" })).toBeInTheDocument());
    expect(askQuestion).toHaveBeenCalledTimes(1);
  });
  it("asks the user to sign in after a 401 and retries the question with the new token", async () => {
    const unauthenticated = Object.assign(new ApiError("Authentication is required.", "UNAUTHENTICATED", null, false), {
      code: "UNAUTHENTICATED",
      retryable: false,
    });
    vi.mocked(askQuestion)
      .mockRejectedValueOnce(unauthenticated)
      .mockImplementationOnce(async ({ question }) => buildMockAskResponse(question));
    render(<AnalyticsDashboard />);
    fireEvent.change(screen.getByLabelText(/ask a question about your fleet data/i), {
      target: { value: "What are the top 10 customers by revenue?" },
    });
    fireEvent.click(screen.getByRole("button", { name: /run analytics query/i }));

    expect(await screen.findByRole("alert", { name: /sign in required/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Access token"), { target: { value: "token-123" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    await waitFor(() => expect(screen.getByRole("region", { name: "Analytics results" })).toBeInTheDocument());
    expect(window.sessionStorage.getItem("analytics.accessToken")).toBe("token-123");
    expect(askQuestion).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("alert", { name: /sign in required/i })).not.toBeInTheDocument();
  });

  it("keeps the question in the thread when sign-in is needed before the conversation exists", async () => {
    const unauthenticated = Object.assign(new ApiError("Authentication is required.", "UNAUTHENTICATED", null, false), {
      code: "UNAUTHENTICATED",
      retryable: false,
    });
    vi.mocked(createConversation).mockRejectedValueOnce(unauthenticated);
    render(<AnalyticsDashboard />);
    fireEvent.change(screen.getByLabelText(/ask a question about your fleet data/i), {
      target: { value: "How many active vehicles do we have?" },
    });
    fireEvent.click(screen.getByRole("button", { name: /run analytics query/i }));

    await screen.findByRole("alert", { name: /sign in required/i });
    fireEvent.change(screen.getByLabelText("Access token"), { target: { value: "token-123" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    await waitFor(() => expect(screen.getByRole("region", { name: "Analytics results" })).toBeInTheDocument());
    expect(screen.getAllByText("How many active vehicles do we have?").length).toBeGreaterThan(0);
  });

  it("explains a failed query generation with guidance instead of a raw error code", async () => {
    const failed = Object.assign(new ApiError("I couldn't produce a valid query for that question.", "QUERY_GENERATION_FAILED", null, false), {
      code: "QUERY_GENERATION_FAILED",
      retryable: false,
      debug: { sql: "SELECT missing FROM vehicles" },
    });
    vi.mocked(askQuestion).mockRejectedValueOnce(failed);
    render(<AnalyticsDashboard />);
    fireEvent.change(screen.getByLabelText(/ask a question about your fleet data/i), {
      target: { value: "Do something impossible" },
    });
    fireEvent.click(screen.getByRole("button", { name: /run analytics query/i }));

    const panel = await screen.findByRole("alert", { name: /could not answer this question/i });
    expect(panel).toHaveTextContent("I couldn't produce a valid query for that question.");
    expect(panel).toHaveTextContent("Name the metric");
    expect(panel).not.toHaveTextContent("QUERY_GENERATION_FAILED");
    expect(screen.getByText("SELECT missing FROM vehicles")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  });

  it("tells the user when to try again after a rate limit", async () => {
    const limited = Object.assign(new ApiError("Too many requests. Please retry later.", "RATE_LIMIT_EXCEEDED", null, true), {
      code: "RATE_LIMIT_EXCEEDED",
      retryable: true,
      retryAfterSeconds: 12,
    });
    vi.mocked(askQuestion).mockRejectedValueOnce(limited);
    render(<AnalyticsDashboard />);
    fireEvent.change(screen.getByLabelText(/ask a question about your fleet data/i), {
      target: { value: "What are the top 10 customers by revenue?" },
    });
    fireEvent.click(screen.getByRole("button", { name: /run analytics query/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Try again in 12s.");
  });

  it("marks truncated results", async () => {
    vi.mocked(askQuestion).mockImplementationOnce(async ({ question }) => ({
      ...buildMockAskResponse(question),
      truncated: true,
    }));
    render(<AnalyticsDashboard />);
    fireEvent.change(screen.getByLabelText(/ask a question about your fleet data/i), {
      target: { value: "What are the top 10 customers by revenue?" },
    });
    fireEvent.click(screen.getByRole("button", { name: /run analytics query/i }));

    expect(await screen.findByText(/rows \(truncated\)/)).toBeInTheDocument();
  });
  it("keeps every answer in the thread, each with its own chart and table", async () => {
    render(<AnalyticsDashboard />);
    const composer = screen.getByLabelText(/ask a question about your fleet data/i);

    fireEvent.change(composer, { target: { value: "What are the top 10 customers by revenue?" } });
    fireEvent.click(screen.getByRole("button", { name: /run analytics query/i }));
    await waitFor(() => expect(screen.getAllByRole("region", { name: "Analytics results" })).toHaveLength(1));

    fireEvent.change(composer, { target: { value: "How many active vehicles do we have?" } });
    fireEvent.click(screen.getByRole("button", { name: /run analytics query/i }));
    await waitFor(() => expect(screen.getAllByRole("region", { name: "Analytics results" })).toHaveLength(2));

    const [first, second] = screen.getAllByRole("region", { name: "Analytics results" });
    expect(within(first).getByRole("cell", { name: /northstar logistics/i })).toBeInTheDocument();
    expect(within(second).getByText("Active Vehicles")).toBeInTheDocument();
    // Both questions are still on screen, in order.
    expect(screen.getAllByText("How many active vehicles do we have?").length).toBeGreaterThan(0);
  });

  it("restores the conversation text after a reload and says the data is not stored", async () => {
    window.localStorage.setItem(
      "analytics.conversations",
      JSON.stringify([{ id: "saved-1", title: "Revenue by customer" }]),
    );
    vi.mocked(getConversation).mockResolvedValueOnce({
      conversation_id: "saved-1",
      turns: [
        { conversation_id: "saved-1", role: "user", content: "Show revenue by customer" },
        { conversation_id: "saved-1", role: "assistant", content: "Northstar led revenue." },
      ],
      context: null,
    });

    render(<AnalyticsDashboard />);

    expect(await screen.findByText("Northstar led revenue.")).toBeInTheDocument();
    expect(screen.getByText("Show revenue by customer")).toBeInTheDocument();
    expect(screen.getByText(/data for this answer is not stored/i)).toBeInTheDocument();
    expect(getConversation).toHaveBeenCalledWith("saved-1");
  });

  it("forgets stored conversations the server no longer has", async () => {
    window.localStorage.setItem(
      "analytics.conversations",
      JSON.stringify([{ id: "gone", title: "Old question" }, { id: "kept", title: "Kept question" }]),
    );
    const notFound = Object.assign(new ApiError("Conversation not found.", "CONVERSATION_NOT_FOUND", null, false), {
      code: "CONVERSATION_NOT_FOUND",
    });
    vi.mocked(getConversation).mockImplementation(async (id: string) => {
      if (id === "gone") throw notFound;
      return {
        conversation_id: id,
        turns: [{ conversation_id: id, role: "user", content: "Kept question" }],
        context: null,
      };
    });

    render(<AnalyticsDashboard />);

    await screen.findAllByText("Kept question");
    expect(JSON.parse(window.localStorage.getItem("analytics.conversations") ?? "[]")).toEqual([
      { id: "kept", title: "Kept question" },
    ]);
  });

  it("deletes a conversation on the server and removes it from the list", async () => {
    render(<AnalyticsDashboard />);
    fireEvent.change(screen.getByLabelText(/ask a question about your fleet data/i), {
      target: { value: "What are the top 10 customers by revenue?" },
    });
    fireEvent.click(screen.getByRole("button", { name: /run analytics query/i }));
    await screen.findByRole("region", { name: "Analytics results" });

    fireEvent.click(screen.getByRole("button", { name: /delete conversation: what are the top 10/i }));

    await waitFor(() => expect(deleteConversation).toHaveBeenCalledWith("test-conversation"));
    await waitFor(() => expect(screen.queryByRole("region", { name: "Analytics results" })).not.toBeInTheDocument());
    expect(window.localStorage.getItem("analytics.conversations")).not.toContain("test-conversation");
  });

  it("records helpful and not-helpful feedback against the answer's request id", async () => {
    render(<AnalyticsDashboard />);
    fireEvent.change(screen.getByLabelText(/ask a question about your fleet data/i), {
      target: { value: "What are the top 10 customers by revenue?" },
    });
    fireEvent.click(screen.getByRole("button", { name: /run analytics query/i }));
    await screen.findByRole("region", { name: "Analytics results" });

    fireEvent.click(screen.getByRole("button", { name: "Not helpful" }));

    await waitFor(() => expect(submitFeedback).toHaveBeenCalledWith({
      request_id: "req-mock-2",
      helpful: false,
      conversation_id: "test-conversation",
    }));
    expect(await screen.findByText("Thanks for the feedback.")).toBeInTheDocument();
  });

  it("reports a feedback failure without losing the answer", async () => {
    vi.mocked(submitFeedback).mockRejectedValueOnce(new Error("offline"));
    render(<AnalyticsDashboard />);
    fireEvent.change(screen.getByLabelText(/ask a question about your fleet data/i), {
      target: { value: "What are the top 10 customers by revenue?" },
    });
    fireEvent.click(screen.getByRole("button", { name: /run analytics query/i }));
    await screen.findByRole("region", { name: "Analytics results" });

    fireEvent.click(screen.getByRole("button", { name: "Helpful" }));

    expect(await screen.findByText(/could not send feedback/i)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Analytics results" })).toBeInTheDocument();
  });

  it("offers example questions before the first question and fills the composer from them", async () => {
    vi.mocked(getBusinessDefinitions).mockResolvedValue({
      definitions: [{ name: "revenue", definition: "Sum of non-cancelled invoice totals." }],
      examples: ["How many invoices are overdue?"],
    });
    render(<AnalyticsDashboard />);

    const example = await screen.findByRole("button", { name: "How many invoices are overdue?" });
    fireEvent.click(example);

    expect(screen.getByLabelText(/ask a question about your fleet data/i)).toHaveValue(
      "How many invoices are overdue?",
    );
    expect(screen.getByText("Revenue")).toBeInTheDocument();
    expect(screen.getByText("Sum of non-cancelled invoice totals.")).toBeInTheDocument();
  });

  it("falls back to built-in examples when the definitions endpoint fails", async () => {
    vi.mocked(getBusinessDefinitions).mockRejectedValue(new Error("offline"));
    render(<AnalyticsDashboard />);

    expect(await screen.findByRole("button", { name: "How many active vehicles do we have?" })).toBeInTheDocument();
  });

  it("explains a timeout and offers a retry", async () => {
    const timedOut = Object.assign(
      new ApiError("The request took too long to complete.", "REQUEST_DEADLINE_EXCEEDED", "req-9", true),
      { code: "REQUEST_DEADLINE_EXCEEDED", retryable: true, requestId: "req-9" },
    );
    vi.mocked(askQuestion).mockRejectedValueOnce(timedOut);
    render(<AnalyticsDashboard />);
    fireEvent.change(screen.getByLabelText(/ask a question about your fleet data/i), {
      target: { value: "What are the top 10 customers by revenue?" },
    });
    fireEvent.click(screen.getByRole("button", { name: /run analytics query/i }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The request took too long to complete.");
    expect(alert).toHaveTextContent("Try a narrower question");
    expect(alert).toHaveTextContent("Reference: req-9");
    expect(screen.getByRole("button", { name: "Retry" })).toBeEnabled();
  });
});
