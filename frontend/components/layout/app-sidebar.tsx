"use client";

import { Activity, BarChart3, LockKeyhole, MessageSquareText, Plus, Trash2 } from "lucide-react";

export interface ConversationListItem {
  id: string;
  title: string;
}

interface AppSidebarProps {
  conversations: ConversationListItem[];
  activeConversationId: string | null;
  onCreateConversation: () => void;
  onSelectConversation: (id: string) => void;
  /** Deletes a conversation and its server-side history; omit to hide the delete buttons. */
  onDeleteConversation?: (id: string) => void;
  busy: boolean;
}

const workspaceLinks = [
  { icon: BarChart3, label: "Analytics", active: true },
];

export function AppSidebar({
  conversations,
  activeConversationId,
  onCreateConversation,
  onSelectConversation,
  onDeleteConversation,
  busy,
}: AppSidebarProps) {
  return (
    <aside className="flex w-full shrink-0 flex-col border-b border-slate-800 bg-[#101b2a] text-slate-100 md:min-h-screen md:w-[264px] md:border-b-0 md:border-r">
      <div className="flex items-center justify-between px-5 py-5">
        <div className="flex items-center gap-3">
          <div className="flex size-9 items-center justify-center rounded-lg bg-cyan-400 text-slate-950">
            <Activity className="size-5" strokeWidth={2.5} />
          </div>
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-cyan-300">Fleet intelligence</p>
            <h1 className="mt-0.5 text-sm font-semibold text-white">Analytics Copilot</h1>
          </div>
        </div>
        <button
          type="button"
          onClick={onCreateConversation}
          disabled={busy}
          aria-label="New conversation"
          title="New conversation"
          className="rounded-md p-2 text-slate-400 transition hover:bg-slate-800 hover:text-white disabled:opacity-50"
        >
          <Plus className="size-4" />
        </button>
      </div>

      <div className="border-y border-slate-800 px-3 py-4">
        <p className="px-2 pb-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">Workspace</p>
        <nav aria-label="Workspace navigation" className="space-y-1">
          {workspaceLinks.map(({ icon: Icon, label, active }) => (
            <div
              key={label}
              className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm ${
                active ? "bg-slate-800 font-medium text-white" : "text-slate-400"
              }`}
            >
              <Icon className={`size-4 ${active ? "text-cyan-300" : "text-slate-500"}`} />
              {label}
            </div>
          ))}
        </nav>
      </div>

      <section className="flex min-h-0 flex-1 flex-col px-3 py-4">
        <div className="flex items-center justify-between px-2 pb-2">
          <h2 className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">Recent conversations</h2>
          <MessageSquareText className="size-3.5 text-slate-500" />
        </div>
        {conversations.length ? (
          <nav aria-label="Recent conversations" className="space-y-1 overflow-y-auto">
            {conversations.map((item) => (
              <div
                key={item.id}
                className={`group flex items-center rounded-md transition ${
                  activeConversationId === item.id
                    ? "bg-cyan-400/10 text-cyan-100 ring-1 ring-inset ring-cyan-300/20"
                    : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"
                }`}
              >
                <button
                  type="button"
                  onClick={() => onSelectConversation(item.id)}
                  aria-current={activeConversationId === item.id ? "true" : undefined}
                  className="min-w-0 flex-1 truncate px-3 py-2 text-left text-xs"
                >
                  {item.title}
                </button>
                {onDeleteConversation && (
                  <button
                    type="button"
                    onClick={() => onDeleteConversation(item.id)}
                    disabled={busy}
                    aria-label={`Delete conversation: ${item.title}`}
                    title="Delete conversation"
                    className="mr-1 rounded p-1.5 text-slate-500 opacity-0 transition hover:bg-slate-700 hover:text-white focus:opacity-100 group-hover:opacity-100 disabled:opacity-30"
                  >
                    <Trash2 className="size-3.5" />
                  </button>
                )}
              </div>
            ))}
          </nav>
        ) : (
          <p className="px-3 py-2 text-xs text-slate-500">Your questions will appear here.</p>
        )}
      </section>

      <div className="flex items-center justify-between border-t border-slate-800 px-5 py-4">
        <div className="flex items-center gap-2 text-xs text-slate-400">
          <LockKeyhole className="size-3.5 text-cyan-300" />
          Read-only session
        </div>
      </div>
    </aside>
  );
}
