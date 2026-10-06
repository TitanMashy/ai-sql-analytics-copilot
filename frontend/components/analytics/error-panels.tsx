"use client";

import { FormEvent, useEffect, useState } from "react";
import { Clock, KeyRound, MessageCircleQuestion, TriangleAlert } from "lucide-react";

export interface UiError {
  code: string;
  message: string;
  retryable: boolean;
  requestId?: string | null;
  debugSql?: string;
  retryAfterSeconds?: number | null;
}

/** Counts down from `seconds` to zero, one tick per second. */
export function useCountdown(seconds: number | null | undefined): number {
  const [remaining, setRemaining] = useState(Math.max(0, Math.ceil(seconds ?? 0)));

  useEffect(() => {
    if (remaining <= 0) return;
    const timer = window.setInterval(() => {
      setRemaining((current) => Math.max(0, current - 1));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [remaining]);

  return remaining;
}

interface SignInRequiredProps {
  onSubmit: (token: string) => void;
}

/** Shown when the API answers 401: the user supplies the access token issued for them. */
export function SignInRequired({ onSubmit }: SignInRequiredProps) {
  const [token, setToken] = useState("");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (token.trim()) {
      onSubmit(token.trim());
      setToken("");
    }
  }

  return (
    <section role="alert" aria-label="Sign in required" className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-4 text-sm text-amber-900">
      <div className="flex items-start gap-2">
        <KeyRound className="mt-0.5 size-4 shrink-0" />
        <div className="flex-1 space-y-3">
          <p>
            <strong className="mr-2 font-semibold">Sign-in required</strong>
            Your session has no valid access token. Paste an access token issued by your administrator to continue.
          </p>
          <form onSubmit={handleSubmit} className="flex flex-wrap items-center gap-2">
            <label htmlFor="access-token" className="sr-only">Access token</label>
            <input
              id="access-token"
              type="password"
              autoComplete="off"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              placeholder="Access token"
              className="min-w-64 flex-1 rounded-md border border-amber-300 bg-white px-3 py-2 text-sm text-slate-800 outline-none focus:border-cyan-600 focus:ring-2 focus:ring-cyan-100"
            />
            <button
              type="submit"
              disabled={!token.trim()}
              className="rounded-md bg-[#127d8c] px-3 py-2 text-xs font-semibold text-white hover:bg-[#0e6875] disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              Continue
            </button>
          </form>
        </div>
      </div>
    </section>
  );
}

interface GenerationFailedProps {
  message: string;
  debugSql?: string;
}

/** The model could not produce a valid query: guide the user instead of showing a raw error. */
export function GenerationFailed({ message, debugSql }: GenerationFailedProps) {
  return (
    <section role="alert" aria-label="Could not answer this question" className="rounded-lg border border-slate-200 bg-white px-4 py-4 text-sm text-slate-700">
      <div className="flex items-start gap-2">
        <MessageCircleQuestion className="mt-0.5 size-4 shrink-0 text-cyan-700" />
        <div className="flex-1 space-y-2">
          <p>
            <strong className="mr-2 font-semibold text-slate-900">I couldn&apos;t answer that</strong>
            {message}
          </p>
          <ul className="list-inside list-disc text-xs text-slate-500">
            <li>Name the metric and the grouping, for example &quot;revenue by customer&quot;.</li>
            <li>Mention a time range, for example &quot;in the last 12 months&quot;.</li>
            <li>Ask about fleet, trips, fuel, maintenance, invoices, payments or subscriptions.</li>
          </ul>
          {debugSql && (
            <details className="text-xs text-slate-500">
              <summary className="cursor-pointer font-medium">Show the last attempted SQL (development only)</summary>
              <pre className="mt-2 max-h-48 overflow-auto rounded bg-slate-900 p-3 text-cyan-100"><code>{debugSql}</code></pre>
            </details>
          )}
        </div>
      </div>
    </section>
  );
}

interface ErrorNoticeProps {
  error: UiError;
  onRetry?: () => void;
  retryDisabled?: boolean;
}

const TIMEOUT_CODES = new Set(["REQUEST_DEADLINE_EXCEEDED", "REQUEST_TIMEOUT", "LLM_TIMEOUT"]);

/**
 * The generic failure banner, with distinct treatment for the two cases a user can act on:
 * a rate limit (wait for the countdown, then retry) and a timeout (ask something narrower).
 */
export function ErrorNotice({ error, onRetry, retryDisabled = false }: ErrorNoticeProps) {
  const rateLimited = error.code === "RATE_LIMIT_EXCEEDED";
  const timedOut = TIMEOUT_CODES.has(error.code);
  const remaining = useCountdown(rateLimited ? error.retryAfterSeconds : 0);
  const waiting = rateLimited && remaining > 0;
  const Icon = rateLimited || timedOut ? Clock : TriangleAlert;

  return (
    <div role="alert" className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
      <Icon className="mt-0.5 size-4 shrink-0" />
      <div className="flex flex-1 flex-wrap items-center justify-between gap-3">
        <span>
          <strong className="mr-2 font-semibold">{error.code}</strong>
          {error.message}
          {waiting ? ` Try again in ${remaining}s.` : ""}
          {timedOut ? " Try a narrower question, such as a shorter date range or a top-N." : ""}
          {error.requestId ? <span className="ml-2 text-xs text-red-600">Reference: {error.requestId}</span> : null}
        </span>
        {error.retryable && onRetry && (
          <button
            type="button"
            onClick={onRetry}
            disabled={retryDisabled || waiting}
            className="rounded-md border border-red-300 px-3 py-1.5 text-xs font-semibold text-red-800 hover:bg-red-100 disabled:opacity-50"
          >
            Retry
          </button>
        )}
      </div>
    </div>
  );
}
