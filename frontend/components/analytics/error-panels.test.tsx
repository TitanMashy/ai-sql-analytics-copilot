import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ErrorNotice, GenerationFailed, SignInRequired } from "./error-panels";

describe("ErrorNotice", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("counts down a rate-limit wait and enables Retry only when it reaches zero", () => {
    const onRetry = vi.fn();
    render(
      <ErrorNotice
        error={{
          code: "RATE_LIMIT_EXCEEDED",
          message: "Too many requests. Please retry later.",
          retryable: true,
          retryAfterSeconds: 3,
        }}
        onRetry={onRetry}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Try again in 3s.");
    expect(screen.getByRole("button", { name: "Retry" })).toBeDisabled();

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Try again in 2s.");

    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(screen.getByRole("alert")).not.toHaveTextContent("Try again in");
    const retry = screen.getByRole("button", { name: "Retry" });
    expect(retry).toBeEnabled();

    fireEvent.click(retry);
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("does not count down for other errors", () => {
    render(
      <ErrorNotice
        error={{ code: "NETWORK_ERROR", message: "Could not reach the analytics service.", retryable: true, retryAfterSeconds: 30 }}
        onRetry={() => undefined}
      />,
    );

    expect(screen.getByRole("alert")).not.toHaveTextContent("Try again in");
    expect(screen.getByRole("button", { name: "Retry" })).toBeEnabled();
  });

  it.each(["REQUEST_DEADLINE_EXCEEDED", "REQUEST_TIMEOUT", "LLM_TIMEOUT"])(
    "gives %s timeouts their own guidance",
    (code) => {
      render(<ErrorNotice error={{ code, message: "That took too long.", retryable: true }} onRetry={() => undefined} />);

      expect(screen.getByRole("alert")).toHaveTextContent("Try a narrower question");
    },
  );

  it("hides Retry for errors that retrying cannot fix", () => {
    render(<ErrorNotice error={{ code: "QUERY_SECURITY_ERROR", message: "Not permitted.", retryable: false }} onRetry={() => undefined} />);

    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  });

  it("shows the request id so a user can quote it to support", () => {
    render(<ErrorNotice error={{ code: "INTERNAL_ERROR", message: "Failed.", retryable: true, requestId: "req-123" }} />);

    expect(screen.getByRole("alert")).toHaveTextContent("Reference: req-123");
  });
});

describe("SignInRequired", () => {
  it("submits the trimmed token and clears the field", () => {
    const onSubmit = vi.fn();
    render(<SignInRequired onSubmit={onSubmit} />);
    const field = screen.getByLabelText("Access token");

    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    fireEvent.change(field, { target: { value: "  secret-token  " } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect(onSubmit).toHaveBeenCalledWith("secret-token");
    expect(field).toHaveValue("");
  });
});

describe("GenerationFailed", () => {
  it("shows guidance and only reveals SQL when it is provided", () => {
    const { rerender } = render(<GenerationFailed message="I could not produce a valid query." />);

    expect(screen.getByRole("alert", { name: /could not answer this question/i })).toBeInTheDocument();
    expect(screen.queryByText(/last attempted sql/i)).not.toBeInTheDocument();

    rerender(<GenerationFailed message="x" debugSql="SELECT 1" />);
    expect(screen.getByText(/last attempted sql/i)).toBeInTheDocument();
  });
});
