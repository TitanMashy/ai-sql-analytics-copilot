"use client";

import { useState } from "react";
import { BarChart3, TriangleAlert } from "lucide-react";

import { AnalyticsResults } from "@/components/analytics/analytics-results";
import { QuestionComposer } from "@/components/analytics/question-composer";
import { AppSidebar, type ConversationListItem } from "@/components/layout/app-sidebar";
import { askQuestion, createConversation } from "@/lib/api";
import type { AskResponse } from "@/types/api";

type StatusKey = "idle" | "loading" | "error";
type ChatMessage = { type: "user" | "assistant"; content: string };
type ConversationThread = ConversationListItem & {
  messages: ChatMessage[];
  result: AskResponse | null;
};

function createTitleFromQuestion(question: string) {
  const title = question.trim().replace(/\s+/g, " ");
  return title.length > 42 ? `${title.slice(0, 39)}...` : title || "New conversation";
}

export function AnalyticsDashboard() {
  const [draft, setDraft] = useState("");
  const [status, setStatus] = useState<StatusKey>("idle");
  const [error, setError] = useState<string | null>(null);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [threads, setThreads] = useState<ConversationThread[]>([]);

  async function startConversation() {
    if (status === "loading") return;
    setError(null);
    try {
      const newConversation = await createConversation();
      const thread: ConversationThread = {
        id: newConversation.conversation_id,
        title: "New conversation",
        messages: [],
        result: null,
      };
      setThreads((previous) => [thread, ...previous]);
      setActiveConversationId(thread.id);
      setStatus("idle");
    } catch (requestError) {
      setStatus("error");
      setError(requestError instanceof Error ? requestError.message : "Could not start a conversation.");
    }
  }

  async function submitQuestion() {
    if (!draft.trim()) {
      return;
    }

    const question = draft.trim();
    setStatus("loading");
    setError(null);

    try {
      let thread = threads.find((item) => item.id === activeConversationId);
      if (!thread) {
        const newConversation = await createConversation();
        thread = {
          id: newConversation.conversation_id,
          title: createTitleFromQuestion(question),
          messages: [],
          result: null,
        };
        setActiveConversationId(thread.id);
      }

      const threadId = thread.id;
      const updatedThread = { ...thread, title: thread.messages.length ? thread.title : createTitleFromQuestion(question) };
      setThreads((previous) => {
        const exists = previous.some((item) => item.id === threadId);
        return exists
          ? previous.map((item) => item.id === threadId
            ? { ...updatedThread, messages: [...item.messages, { type: "user", content: question }], result: null }
            : item)
          : [{ ...updatedThread, messages: [{ type: "user", content: question }] }, ...previous];
      });
      setDraft("");
      const result = await askQuestion({ question, conversation_id: threadId });
      setThreads((previous) => previous.map((item) => item.id === threadId
        ? { ...item, messages: [...item.messages, { type: "assistant", content: result.summary ?? result.explanation }], result }
        : item));
      setStatus("idle");
    } catch (requestError) {
      setStatus("error");
      setError(requestError instanceof Error ? requestError.message : "Request failed.");
    }
  }

  const activeThread = threads.find((thread) => thread.id === activeConversationId) ?? null;

  return (
    <div className="min-h-screen bg-[#f2f6f6] text-slate-900 md:flex">
      <AppSidebar
        conversations={threads}
        activeConversationId={activeConversationId}
        onCreateConversation={startConversation}
        onSelectConversation={(id) => {
          setActiveConversationId(id);
          setError(null);
          setStatus("idle");
        }}
        busy={status === "loading"}
      />

      <main className="min-w-0 flex-1">
        <header className="flex items-center justify-between border-b border-slate-200 bg-white px-5 py-3.5 md:px-8">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">Fleet operations / Analytics</p>
            <h2 className="mt-1 text-sm font-semibold text-slate-800">Conversational analytics</h2>
          </div>
          <span className="rounded-md border border-slate-200 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">Read-only data</span>
        </header>

        <QuestionComposer value={draft} onChange={setDraft} onSubmit={submitQuestion} busy={status === "loading"} />

        <div className="mx-auto max-w-[1240px] space-y-5 px-5 py-6 md:px-8 md:py-8">
          {status === "loading" && (
            <div role="status" className="flex items-center gap-2 text-xs font-medium text-cyan-800">
              <span className="size-2 animate-pulse rounded-full bg-cyan-600" /> Generating and validating your query...
            </div>
          )}

          {error && (
            <div role="alert" className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
              <TriangleAlert className="mt-0.5 size-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {activeThread?.messages.length ? (
            <section aria-label="Conversation" className="space-y-3">
              {activeThread.messages.map((message, index) => (
                <div key={`${activeThread.id}-${index}`} className={`flex ${message.type === "user" ? "justify-end" : "justify-start"}`}>
                  <p className={`max-w-[min(90%,760px)] rounded-lg px-4 py-3 text-sm leading-6 ${
                    message.type === "user" ? "bg-[#173344] text-white" : "border border-slate-200 bg-white text-slate-700"
                  }`}>
                    {message.content}
                  </p>
                </div>
              ))}
            </section>
          ) : (
            <section aria-label="No analytics results" className="flex min-h-56 items-center gap-4 border-y border-slate-200 py-8 text-slate-500">
              <BarChart3 className="size-5 text-cyan-700" />
              <p className="text-sm">No results selected</p>
            </section>
          )}

          {activeThread?.result && <AnalyticsResults result={activeThread.result} />}
        </div>
      </main>
    </div>
  );
}
