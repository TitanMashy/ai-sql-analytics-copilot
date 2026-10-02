import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { askQuestion, createConversation } from "@/lib/api";
import type { AskResponse } from "@/types/api";
import { buildMockAskResponse } from "@/lib/mock-data";

import { AnalyticsDashboard } from "./analytics-dashboard";

vi.mock("@/lib/api", () => {
  class TestApiError extends Error {
    code = "TEST_ERROR";
    retryable = true;
  }
  return {
    ApiError: TestApiError,
    askQuestion: vi.fn(),
    createConversation: vi.fn(),
  };
});

describe("AnalyticsDashboard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
});
