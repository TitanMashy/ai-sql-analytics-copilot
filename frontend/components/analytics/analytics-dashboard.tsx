"use client";

import { useEffect, useRef, useState } from "react";

import { AnalyticsResults } from "@/components/analytics/analytics-results";
import {
  ErrorNotice,
  GenerationFailed,
  SignInRequired,
  type UiError,
} from "@/components/analytics/error-panels";
import { ExamplesPanel } from "@/components/analytics/examples-panel";
import { QuestionComposer } from "@/components/analytics/question-composer";
import { AppSidebar, type ConversationListItem } from "@/components/layout/app-sidebar";
import {
  ApiError,
  askQuestion,
  createConversation,
  deleteConversation,
  getConversation,
  submitFeedback,
} from "@/lib/api";
import { setAuthToken } from "@/lib/auth";
import {
  forgetConversation,
  loadStoredConversations,
  saveStoredConversations,
} from "@/lib/conversation-store";
import type { AskResponse } from "@/types/api";

type StatusKey = "idle" | "loading" | "error";
type ChatMessage = {
  type: "user" | "assistant";
  content: string;
  /** The full answer. Only present for answers received in this session: results are not stored. */
  result?: AskResponse;
  /** True for text restored from the server after a reload. */
  restored?: boolean;
};
type ConversationThread = ConversationListItem & {
  messages: ChatMessage[];
};
type KeyedError = UiError & { key: number };

function createTitleFromQuestion(question: string) {
  const title = question.trim().replace(/\s+/g, " ");
  return title.length > 42 ? `${title.slice(0, 39)}...` : title || "New conversation";
}

export function AnalyticsDashboard() {
  const submissionInProgress = useRef(false);
  const errorCounter = useRef(0);
  const [draft, setDraft] = useState("");
  const [status, setStatus] = useState<StatusKey>("idle");
  const [error, setError] = useState<KeyedError | null>(null);
  const [lastFailedQuestion, setLastFailedQuestion] = useState<string | null>(null);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [threads, setThreads] = useState<ConversationThread[]>([]);

  function showError(uiError: UiError | null) {
    errorCounter.current += 1;
    setError(uiError ? { ...uiError, key: errorCounter.current } : null);
  }

  // Restore the conversations this browser started, so a reload does not lose the thread. Only
  // the text comes back: result rows are never stored server-side, so re-ask to refresh the data.
  useEffect(() => {
    let cancelled = false;

    async function restore() {
      const restored: ConversationThread[] = [];
      for (const item of loadStoredConversations()) {
        try {
          const conversation = await getConversation(item.id);
          const messages: ChatMessage[] = [];
          for (const turn of conversation.turns) {
            if (turn.role === "user" || turn.role === "assistant") {
              messages.push({ type: turn.role, content: turn.content, restored: true });
            }
          }
          restored.push({ id: item.id, title: item.title, messages });
        } catch (restoreError) {
          if (restoreError instanceof ApiError && restoreError.code === "UNAUTHENTICATED") {
            if (!cancelled) {
              errorCounter.current += 1;
              setError({
                code: restoreError.code,
                message: restoreError.message,
                retryable: false,
                key: errorCounter.current,
              });
            }
            return;
          }
          if (restoreError instanceof ApiError && restoreError.code === "CONVERSATION_NOT_FOUND") {
            forgetConversation(item.id); // expired, deleted, or not ours
          }
          // Any other failure leaves the id remembered for the next load.
        }
      }
      if (cancelled || !restored.length) return;
      setThreads((previous) => {
        const known = new Set(previous.map((thread) => thread.id));
        return [...previous, ...restored.filter((thread) => !known.has(thread.id))];
      });
      setActiveConversationId((current) => current ?? restored[0].id);
    }

    void restore();
    return () => {
      cancelled = true;
    };
  }, []);

  // Remember the conversation list so the next load can restore it.
  useEffect(() => {
    if (threads.length) {
      saveStoredConversations(threads.map(({ id, title }) => ({ id, title })));
    }
  }, [threads]);

  async function startConversation() {
    if (status === "loading") return;
    showError(null);
    try {
      const newConversation = await createConversation();
      const thread: ConversationThread = {
        id: newConversation.conversation_id,
        title: "New conversation",
        messages: [],
      };
      setThreads((previous) => [thread, ...previous]);
      setActiveConversationId(thread.id);
      setStatus("idle");
      setLastFailedQuestion(null);
    } catch (requestError) {
      setStatus("error");
      showError(toUiError(requestError, "Could not start a conversation."));
    }
  }

  async function removeConversation(id: string) {
    if (status === "loading") return;
    try {
      await deleteConversation(id);
    } catch (requestError) {
      showError(toUiError(requestError, "Could not delete the conversation."));
      return;
    }
    forgetConversation(id);
    setThreads((previous) => previous.filter((thread) => thread.id !== id));
    setActiveConversationId((current) => (current === id ? null : current));
    showError(null);
  }

  async function submitQuestion(questionOverride?: string, isRetry = false) {
    if (submissionInProgress.current) return;
    const question = (questionOverride ?? draft).trim();
    if (!question) {
      return;
    }

    submissionInProgress.current = true;
    setStatus("loading");
    showError(null);

    try {
      let thread = threads.find((item) => item.id === activeConversationId);
      if (!thread) {
        const newConversation = await createConversation();
        thread = {
          id: newConversation.conversation_id,
          title: createTitleFromQuestion(question),
          messages: [],
        };
        setActiveConversationId(thread.id);
      }

      const threadId = thread.id;
      const title = thread.messages.length ? thread.title : createTitleFromQuestion(question);
      // A retry normally finds its question already recorded; if the first attempt failed before
      // the thread existed (for example a 401 while creating it), the question still has to be added.
      const lastMessage = thread.messages[thread.messages.length - 1];
      const alreadyRecorded = isRetry && lastMessage?.type === "user" && lastMessage.content === question;
      if (!alreadyRecorded) {
        const userMessage: ChatMessage = { type: "user", content: question };
        setThreads((previous) => {
          const exists = previous.some((item) => item.id === threadId);
          return exists
            ? previous.map((item) => item.id === threadId
              ? { ...item, title, messages: [...item.messages, userMessage] }
              : item)
            : [{ id: threadId, title, messages: [userMessage] }, ...previous];
        });
        setDraft("");
      }
      const result = await askQuestion({ question, conversation_id: threadId });
      const assistantMessage: ChatMessage = {
        type: "assistant",
        content: result.summary ?? result.explanation,
        result,
      };
      setThreads((previous) => previous.map((item) => item.id === threadId
        ? { ...item, messages: [...item.messages, assistantMessage] }
        : item));
      setStatus("idle");
      setLastFailedQuestion(null);
    } catch (requestError) {
      setStatus("error");
      showError(toUiError(requestError, "Request failed."));
      setLastFailedQuestion(question);
    } finally {
      submissionInProgress.current = false;
    }
  }

  async function sendFeedback(result: AskResponse, helpful: boolean) {
    if (!result.request_id) return;
    await submitFeedback({
      request_id: result.request_id,
      helpful,
      conversation_id: activeConversationId,
    });
  }

  const activeThread = threads.find((thread) => thread.id === activeConversationId) ?? null;
  const special = error?.code === "UNAUTHENTICATED" || error?.code === "QUERY_GENERATION_FAILED";

  return (
    <div className="min-h-screen bg-[#f2f6f6] text-slate-900 md:flex">
      <AppSidebar
        conversations={threads}
        activeConversationId={activeConversationId}
        onCreateConversation={startConversation}
        onSelectConversation={(id) => {
          setActiveConversationId(id);
          showError(null);
          setStatus("idle");
        }}
        onDeleteConversation={removeConversation}
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

          {error?.code === "UNAUTHENTICATED" && (
            <SignInRequired
              onSubmit={(token) => {
                setAuthToken(token);
                showError(null);
                if (lastFailedQuestion) {
                  void submitQuestion(lastFailedQuestion, true);
                } else {
                  setStatus("idle");
                }
              }}
            />
          )}

          {error?.code === "QUERY_GENERATION_FAILED" && (
            <GenerationFailed message={error.message} debugSql={error.debugSql} />
          )}

          {error && !special && (
            <ErrorNotice
              key={error.key}
              error={error}
              onRetry={lastFailedQuestion ? () => submitQuestion(lastFailedQuestion, true) : undefined}
              retryDisabled={status === "loading"}
            />
          )}

          {activeThread?.messages.length ? (
            <section aria-label="Conversation" className="space-y-5">
              {activeThread.messages.map((message, index) => (
                <div key={`${activeThread.id}-${index}`} className="space-y-4">
                  <div className={`flex ${message.type === "user" ? "justify-end" : "justify-start"}`}>
                    <p className={`max-w-[min(90%,760px)] rounded-lg px-4 py-3 text-sm leading-6 ${
                      message.type === "user" ? "bg-[#173344] text-white" : "border border-slate-200 bg-white text-slate-700"
                    }`}>
                      {message.content}
                    </p>
                  </div>
                  {message.result && (
                    <AnalyticsResults
                      result={message.result}
                      onFeedback={message.result.request_id
                        ? (helpful) => sendFeedback(message.result as AskResponse, helpful)
                        : undefined}
                    />
                  )}
                  {message.restored && message.type === "assistant" && (
                    <p className="text-xs text-slate-400">
                      The data for this answer is not stored. Ask the question again to refresh it.
                    </p>
                  )}
                </div>
              ))}
            </section>
          ) : (
            <ExamplesPanel onPick={setDraft} disabled={status === "loading"} />
          )}
        </div>
      </main>
    </div>
  );
}

function toUiError(error: unknown, fallback: string): UiError {
  if (error instanceof ApiError) {
    return {
      code: error.code,
      message: error.message,
      retryable: error.retryable,
      requestId: error.requestId,
      debugSql: error.debug?.sql,
      retryAfterSeconds: error.retryAfterSeconds,
    };
  }
  return {
    code: "REQUEST_FAILED",
    message: error instanceof Error ? error.message : fallback,
    retryable: true,
  };
}
