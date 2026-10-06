"use client";

import { useEffect, useState } from "react";
import { BarChart3, Lightbulb } from "lucide-react";

import { getBusinessDefinitions } from "@/lib/api";
import { formatLabel } from "@/lib/utils";
import type { BusinessDefinitionsResponse } from "@/types/api";

/** Shown until (or instead of) the examples the backend provides. */
export const FALLBACK_EXAMPLES = [
  "How many active vehicles do we have?",
  "What were the top 10 customers by revenue?",
  "Show monthly revenue for the last 12 months.",
  "Which vehicles had the highest idle time?",
  "Show fuel consumption by vehicle.",
];

interface ExamplesPanelProps {
  onPick: (question: string) => void;
  disabled?: boolean;
}

/**
 * The empty state: example questions and the definitions behind the metrics, so a new user knows
 * what can be asked and what "revenue" or "active vehicle" means before asking.
 */
export function ExamplesPanel({ onPick, disabled = false }: ExamplesPanelProps) {
  const [details, setDetails] = useState<BusinessDefinitionsResponse | null>(null);

  useEffect(() => {
    let active = true;
    getBusinessDefinitions()
      .then((response) => {
        if (active) setDetails(response);
      })
      .catch(() => {
        // The built-in examples are enough when the backend cannot provide richer ones.
      });
    return () => {
      active = false;
    };
  }, []);

  const examples = details?.examples.length ? details.examples : FALLBACK_EXAMPLES;

  return (
    <section aria-label="What can I ask" className="space-y-5 rounded-lg border border-slate-200 bg-white p-6">
      <div className="flex items-center gap-3">
        <BarChart3 className="size-5 text-cyan-700" />
        <div>
          <h2 className="text-base font-semibold text-slate-900">What can I ask?</h2>
          <p className="text-sm text-slate-500">
            Ask in plain English about your fleet, trips, fuel, maintenance, billing, or subscriptions.
          </p>
        </div>
      </div>

      <div>
        <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
          <Lightbulb className="size-3.5 text-amber-500" /> Try one of these
        </p>
        <ul className="flex flex-wrap gap-2">
          {examples.map((example) => (
            <li key={example}>
              <button
                type="button"
                disabled={disabled}
                onClick={() => onPick(example)}
                className="rounded-full border border-slate-200 px-3 py-1.5 text-xs text-slate-700 transition hover:border-cyan-300 hover:bg-cyan-50 hover:text-cyan-800 disabled:opacity-50"
              >
                {example}
              </button>
            </li>
          ))}
        </ul>
      </div>

      {details && details.definitions.length > 0 && (
        <details className="text-sm text-slate-600">
          <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-slate-500">
            How metrics are defined
          </summary>
          <dl className="mt-3 space-y-2">
            {details.definitions.map((definition) => (
              <div key={definition.name}>
                <dt className="font-medium text-slate-800">{formatLabel(definition.name)}</dt>
                <dd className="text-slate-600">{definition.definition}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}
    </section>
  );
}
