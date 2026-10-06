const STORAGE_KEY = "analytics.conversations";
const MAX_REMEMBERED = 20;

export interface StoredConversation {
  id: string;
  title: string;
}

/**
 * The conversations this browser has started, kept so a reload can ask the backend for their
 * history. Only ids and titles are stored here; the turns live on the server (durable when
 * CONVERSATION_STORE=postgres) and are owned by the signed-in user, so a stale id for someone
 * else's conversation simply 404s. localStorage can throw or be unavailable, so every call
 * degrades to "nothing remembered".
 */
export function loadStoredConversations(): StoredConversation[] {
  if (typeof window === "undefined") return [];
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(
        (item): item is StoredConversation =>
          typeof item === "object" && item !== null &&
          typeof (item as StoredConversation).id === "string" &&
          typeof (item as StoredConversation).title === "string",
      )
      .slice(0, MAX_REMEMBERED);
  } catch {
    return [];
  }
}

export function saveStoredConversations(conversations: StoredConversation[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify(conversations.slice(0, MAX_REMEMBERED).map(({ id, title }) => ({ id, title }))),
    );
  } catch {
    // Without storage the thread is simply not restored after a reload.
  }
}

export function forgetConversation(id: string): void {
  saveStoredConversations(loadStoredConversations().filter((item) => item.id !== id));
}
