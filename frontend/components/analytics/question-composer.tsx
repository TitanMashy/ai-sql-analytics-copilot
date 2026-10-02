"use client";

import { FormEvent } from "react";
import { ArrowUp, Lightbulb, LoaderCircle } from "lucide-react";

interface QuestionComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  busy: boolean;
}

const suggestions = [
  "Top customers by revenue",
  "Monthly revenue trend",
  "Vehicles with highest idle time",
  "Active vehicle count",
];

export function QuestionComposer({ value, onChange, onSubmit, busy }: QuestionComposerProps) {
  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit();
  }

  return (
    <section className="border-b border-slate-200 bg-white px-5 py-5 md:px-8 md:py-6">
      <div className="mx-auto max-w-[1240px]">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-cyan-700">Ask your data</p>
            <h2 className="mt-1 text-lg font-semibold text-slate-900">What would you like to know?</h2>
          </div>
          <span className="hidden items-center gap-1.5 text-xs text-slate-400 sm:flex">
            <span className="size-1.5 rounded-full bg-emerald-500" /> Connected to fleet analytics
          </span>
        </div>

        <form onSubmit={handleSubmit} className="relative">
          <label htmlFor="question" className="sr-only">Ask a question about your fleet data</label>
          <textarea
            id="question"
            value={value}
            onChange={(event) => onChange(event.target.value)}
            placeholder="Ask a question about your fleet data..."
            rows={2}
            disabled={busy}
            className="block min-h-20 w-full resize-y rounded-lg border border-slate-300 bg-slate-50 px-4 py-3 pr-16 text-sm leading-6 text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-cyan-600 focus:bg-white focus:ring-2 focus:ring-cyan-100 disabled:opacity-60"
          />
          <button
            type="submit"
            disabled={busy || !value.trim()}
            aria-label="Run analytics query"
            title="Run analytics query"
            className="absolute bottom-2.5 right-2.5 flex size-10 items-center justify-center rounded-md bg-[#127d8c] text-white transition hover:bg-[#0e6875] disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            {busy ? <LoaderCircle className="size-4 animate-spin" /> : <ArrowUp className="size-5" />}
          </button>
        </form>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="mr-1 flex items-center gap-1 text-[11px] font-medium text-slate-500">
            <Lightbulb className="size-3.5 text-amber-500" /> Try
          </span>
          {suggestions.map((suggestion) => (
            <button
              key={suggestion}
              type="button"
              disabled={busy}
              onClick={() => onChange(suggestion)}
              className="rounded-full border border-slate-200 px-3 py-1.5 text-[11px] text-slate-600 transition hover:border-cyan-300 hover:bg-cyan-50 hover:text-cyan-800 disabled:opacity-50"
            >
              {suggestion}
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}
