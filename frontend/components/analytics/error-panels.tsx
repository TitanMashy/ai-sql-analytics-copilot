"use client";

import { FormEvent, useState } from "react";
import { KeyRound, MessageCircleQuestion } from "lucide-react";

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
