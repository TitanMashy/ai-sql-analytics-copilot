# Conversation Context and Bounded Memory

Sprint 7 adds lightweight conversational analytics support without allowing unlimited prompt history to reach Gemini or the rest of the SQL generation layer.

## Goals

- preserve the previous analytical thread across follow-up questions
- keep recent business context and result summaries available to the model
- avoid sending the full chat transcript to the LLM
- keep the existing SQL validation and read-only execution security boundary unchanged

## Architecture

The conversation layer sits between the API layer and the provider call:

1. A `conversation_id` is supplied on a request or created through the conversation endpoints.
2. A shared in-memory `ConversationMemory` stores the recent ordered user/assistant turns.
3. A bounded context builder trims the history to the last `N` turns and a byte cap.
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

The conversation routes expose simple lifecycle support:

- `POST /api/v1/analytics/conversations` to create a thread
- `GET /api/v1/analytics/conversations/{conversation_id}` to inspect it
- `POST /api/v1/analytics/conversations/{conversation_id}/turns` to append a turn

## Security Notes

Conversation memory is intentionally not a SQL generation or validation control. It is only a bounded prompt context aid. The actual trust boundary remains the AST validator, table allowlist, read-only PostgreSQL role, and the execution guardrails already in place for Sprints 3–6.
