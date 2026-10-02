import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { askQuestion, createConversation } from "@/lib/api";
import { buildMockAskResponse } from "@/lib/mock-data";

import { AnalyticsDashboard } from "./analytics-dashboard";

vi.mock("@/lib/api", () => ({
  askQuestion: vi.fn(),
  createConversation: vi.fn(),
}));

describe("AnalyticsDashboard", () => {
  beforeEach(() => {
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
});
