"use client";

export default function GlobalError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-[#f2f6f6] px-6 text-slate-900">
      <section role="alert" className="w-full max-w-md border-y border-slate-300 py-8">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-red-700">Application error</p>
        <h1 className="mt-2 text-xl font-semibold">The analytics workspace could not load.</h1>
        <button
          type="button"
          onClick={reset}
          className="mt-5 rounded-md bg-[#127d8c] px-4 py-2 text-sm font-semibold text-white hover:bg-[#0e6875]"
        >
          Try again
        </button>
      </section>
    </main>
  );
}
