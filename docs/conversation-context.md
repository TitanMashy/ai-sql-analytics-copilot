# Conversation Context and Bounded Memory

The implemented conversational analytics layer preserves bounded follow-up context without allowing unlimited prompt history to reach the selected provider or SQL generation layer.

## Goals

- preserve the previous analytical thread across follow-up questions
- keep recent business context and result summaries available to the model
- avoid sending the full chat transcript to the LLM
- keep the existing SQL validation and read-only execution security boundary unchanged

## Architecture

The conversation layer sits between the API layer and the provider call:

1. A `conversation_id` is supplied on a request or created through the conversation endpoints.
2. A conversation store (selected by `CONVERSATION_STORE`) keeps the recent ordered user/assistant turns: PostgreSQL tables (durable, the Compose default) or an in-process `ConversationMemory` (the default when running the backend directly, and the test double). Both implement the same `ConversationStore` interface and the same ownership rule.
3. A bounded context builder retains at most the latest 8 turns and 2,000 characters by default; both caller context and turn content are independently request-limited.
4. The generated prompt receives this distilled context, not the raw full transcript.
5. Each successful question/answer can then become the next follow-up anchor for the same conversation.

This keeps the memory feature backend-owned and testable while preserving the existing security architecture.

## Context Strategy

The implementation does not keep the complete conversation forever. Instead, it preserves:

- the most recent user/assistant exchanges
- a deterministic trimming window
- a strict maximum character budget for prompt injection safety

The result is a compact context string such as:

```
user: Show monthly revenue for the last 12 months.
assistant: The total was $120k.
user: Compare that against the previous quarter.
```

This keeps only the relevant recent thread rather than the entire session transcript.

## API Shape

The generation and ask endpoints accept:

- `conversation_id` for continuing the same thread
- `conversation_context` for explicit context overrides when an application already has a compact summary

Conversation-aware SQL execution uses `POST /api/v1/analytics/ask` with the same `conversation_id`. The UI thread list is client-side for the current page session, while the conversation itself is kept by the backend: with `CONVERSATION_STORE=postgres` it survives restarts, and with `memory` it is lost on process restart.

The conversation routes expose simple lifecycle support:

- `POST /api/v1/analytics/conversations` to create a thread
- `GET /api/v1/analytics/conversations/{conversation_id}` to inspect it
- `POST /api/v1/analytics/conversations/{conversation_id}/turns` to append a turn

## Security Notes

Conversation memory is intentionally not a SQL generation or validation control. User questions and supplied context remain untrusted prompt data, whichever model provider is selected. The actual trust boundary remains SQLGlot validation, the table allowlist, the read-only PostgreSQL role, request limits, and the execution guardrails.

Conversations are owned by the authenticated principal that created them: another principal gets a 404, indistinguishable from "not found". Clients can add only `user` turns; assistant turns (which feed later prompts) are written by the server and only for exchanges that succeeded. Only text is stored (the question, the answer summary, the SQL and the tables used), never result rows. Idle conversations expire (`CONVERSATION_TTL_DAYS`, default 30, removed by `python -m app.jobs.purge`; 24 hours for the in-memory store), and the number per owner and turns per conversation are capped (`CONVERSATION_MAX_PER_OWNER`, `CONVERSATION_MAX_TURNS`). The tables are described in [database-schema.md](database-schema.md); Caller-supplied context in a request is still untrusted and is not persisted.
