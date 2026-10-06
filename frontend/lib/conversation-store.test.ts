import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  forgetConversation,
  loadStoredConversations,
  saveStoredConversations,
} from "@/lib/conversation-store";

describe("conversation store", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("round-trips ids and titles only", () => {
    saveStoredConversations([
      { id: "a", title: "First" },
      { id: "b", title: "Second", extra: "dropped" } as never,
    ]);

    expect(loadStoredConversations()).toEqual([
      { id: "a", title: "First" },
      { id: "b", title: "Second" },
    ]);
    expect(window.localStorage.getItem("analytics.conversations")).not.toContain("dropped");
  });

  it("remembers at most twenty conversations", () => {
    saveStoredConversations(Array.from({ length: 30 }, (_, index) => ({ id: `c${index}`, title: "t" })));

    expect(loadStoredConversations()).toHaveLength(20);
  });

  it("forgets one conversation without touching the others", () => {
    saveStoredConversations([{ id: "a", title: "A" }, { id: "b", title: "B" }]);

    forgetConversation("a");

    expect(loadStoredConversations()).toEqual([{ id: "b", title: "B" }]);
  });

  it.each(["not json", "{}", "[1, 2]", '[{"id": 5, "title": "x"}]', '[{"id": "ok"}]'])(
    "ignores malformed stored data %s",
    (raw) => {
      window.localStorage.setItem("analytics.conversations", raw);

      expect(loadStoredConversations()).toEqual([]);
    },
  );

  it("keeps the valid entries when only some are malformed", () => {
    window.localStorage.setItem(
      "analytics.conversations",
      JSON.stringify([{ id: "ok", title: "Fine" }, { id: 7 }, null]),
    );

    expect(loadStoredConversations()).toEqual([{ id: "ok", title: "Fine" }]);
  });

  it("degrades to nothing remembered when storage throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });

    expect(loadStoredConversations()).toEqual([]);
    expect(() => saveStoredConversations([{ id: "a", title: "A" }])).not.toThrow();
  });
});
