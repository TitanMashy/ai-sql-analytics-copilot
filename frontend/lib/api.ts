import type { AskResponse, ConversationResponse, QuestionRequest } from "@/types/api";

const apiBaseUrl = process.env.NEXT_PUBLIC_API_URL ?? "";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  if (!response.ok) {
    let message = "The analytics service is temporarily unavailable.";
    try {
      const body = (await response.json()) as { error?: { message?: string } };
      if (body?.error?.message) {
        message = body.error.message;
      }
    } catch {
      message = response.statusText || message;
    }
    throw new Error(message);
  }

  return (await response.json()) as T;
}

export async function createConversation(): Promise<ConversationResponse> {
  return apiFetch<ConversationResponse>("/api/v1/analytics/conversations", {
    method: "POST",
  });
}

export async function getConversation(id: string): Promise<ConversationResponse> {
  return apiFetch<ConversationResponse>(`/api/v1/analytics/conversations/${id}`);
}

export async function askQuestion(payload: QuestionRequest): Promise<AskResponse> {
  return apiFetch<AskResponse>("/api/v1/analytics/ask", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function deleteConversation(id: string): Promise<void> {
  if (!id) {
    return;
  }

  try {
    await fetch(`${apiBaseUrl}/api/v1/analytics/conversations/${id}`, {
      method: "DELETE",
    });
  } catch {
    // Best-effort only for the in-memory UI client; the backend does not yet expose a delete route.
  }
}

export async function getSchema(): Promise<Record<string, unknown>> {
  return apiFetch<Record<string, unknown>>("/api/v1/schema/tables");
}
