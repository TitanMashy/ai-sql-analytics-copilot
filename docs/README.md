# Documentation index

Where to look, and which document is the authority for what. Start with the top-level
[README](../README.md) to run the project and [progress.md](../progress.md) for the current
state and handoff.

## Understand the system

| Document | Answers |
|---|---|
| [architecture.md](architecture.md) | Components, the `/ask` request flow, where state lives |
| [database-schema.md](database-schema.md) | The fleet tables and the tenant-scoped `analytics` views |
| [business-definitions.md](business-definitions.md) | What "revenue", "active vehicle", "idle time" mean |
| [conversation-context.md](conversation-context.md) | How follow-up questions keep bounded context |
| [visualization.md](visualization.md) | How KPI and chart types are chosen |

## Security (read in this order)

| Document | Role |
|---|---|
| [threat-model.md](threat-model.md) | What is protected, from whom, and the residual risks |
| [security.md](security.md) | The SQL security controls in detail (validator, read-only execution, tenancy) |
| [production-security-review.md](production-security-review.md) | What is and is not implemented, as a checklist |

## Run and operate

| Document | Answers |
|---|---|
| [deployment.md](deployment.md) | Every setting, with defaults and production notes |
| [operations.md](operations.md) | Start, migrate, release, roll back, back up, respond to incidents |
| [capacity.md](capacity.md) | Sizing and how to run the k6 load test |
| [slos.md](slos.md) | Service objectives and the alerts behind them |
| [llm-providers.md](llm-providers.md) | Choosing mock, Gemini or Ollama; the settings, error codes and the one retry policy |
| [evaluation.md](evaluation.md) | The text-to-SQL evaluation suite and its thresholds |
| [runbooks/](runbooks/) | One page per alert or incident type |
| [drills/](drills/) | Restore and rollback rehearsals |

## History

| Document | Role |
|---|---|
| [Sequence.md](Sequence.md) | How the project evolved, the complexity analysis, and the log of what was simplified and why |
| [../final_sprints.md](../final_sprints.md) | The plan for Sprints 13-15 (LangChain, Ollama, tracing, closeout). Completed; results in progress.md sections 23-25 |
| [../sprints.md](../sprints.md) | The original Sprint 11 and 12 plan. Historical: some items it describes were later removed (see Sequence.md section 18) |
| [../progress.md](../progress.md) | The current handoff: status, verification results, known limitations |

When two documents disagree, trust the code first, then `progress.md`, then the rest.
