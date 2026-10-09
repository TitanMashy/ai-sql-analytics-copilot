# Threat model

A short, honest model of what the system protects, from whom, and how. It complements
[security.md](security.md) (the controls in detail) and
[production-security-review.md](production-security-review.md) (what is and is not implemented).

## Assets

| Asset | Why it matters |
|---|---|
| Customers' fleet and billing data | confidentiality between tenants is the product's core promise |
| Personal data (contact names, emails, phone numbers, licence numbers) | privacy obligations; never needed for analytics |
| Database integrity and availability | the service must not be a way to modify or exhaust the database |
| LLM provider key and spend | a stolen key or unbounded usage costs money |
| Credentials and signing keys | compromise defeats every other control |
| The audit trail | evidence for investigations |

## Actors

- **Legitimate user:** a customer's employee asking about their own fleet.
- **Curious or malicious tenant:** an authenticated user trying to see another tenant's data or
  personal data, or to abuse the service.
- **Prompt injector:** anyone whose text reaches the model: the user, or data the model quotes back.
- **External attacker:** unauthenticated, reaching the public surface.
- **Compromised dependency or model:** the model's output is treated as untrusted by design.

## Trust boundaries and controls

```
browser -> frontend proxy -> backend -> validator -> read-only transaction -> analytics views -> tables
                                 \-> LLM provider (external, untrusted output)
```

| # | Threat | Control (defense in depth) | Residual risk |
|---|---|---|---|
| 1 | Unauthenticated access | JWT on every analytics and schema route; development modes rejected in production at startup and again at runtime | token theft (see 9) |
| 2 | Reaching internal routes through the proxy | proxy forwards an explicit route list; direct-SQL routes unmounted in production; metrics and diagnostics need an operator token; backend port unpublished | misconfigured ingress that exposes the backend directly |
| 3 | **Cross-tenant read** | tenant scope is set per transaction from the token and applied by the `analytics` views; unset scope returns no rows; the role has no base-table privileges; integration tests prove isolation through joins, CTEs, subqueries, unions | the scope is an ordinary session setting; the validator blocks `set_config`/`current_setting`/`SET` so generated SQL cannot change it |
| 4 | **Personal-data exposure** | personal columns are absent from the views, hidden from prompts and the schema API, and rejected by the validator as security errors | a new personal column added later must be added to `PII_COLUMNS` |
| 5 | SQL injection via the model (write, DDL, system functions, catalog, multiple statements) | AST validator (SELECT-only, table/function allowlists, no schema qualifiers other than `analytics`), read-only transaction, role with SELECT on views only, statement/lock/idle timeouts, row cap, cost pre-flight | validator and parser disagreement (mitigated by the database controls underneath) |
| 6 | Prompt injection (extract the system prompt, bypass rules) | rules are in a system instruction; user text is JSON-encoded as data; nothing the model says is trusted: its SQL is validated and its explanation is only displayed | the model may still follow injected instructions; the controls above bound what that can achieve; evaluation tracks leaks |
| 7 | Resource exhaustion (cost, connections, threads) | per-principal rate limits (stricter for LLM calls), per-request deadline, statement timeout, `QUERY_COST_LIMIT`, row cap, request-size limits, bounded pools | many distinct principals; capacity planning in `capacity.md` |
| 8 | Conversation hijack or injection | conversations are owner-scoped and 404 for others; clients can only add `user` turns; failed attempts are never stored; TTL and caps | a stolen token reads that user's own conversations |
| 9 | Credential theft | secrets via files, never in the environment or images; startup errors never print values; rotation runbook | a stolen JWT is valid until it expires (there is no revocation list) |
| 10 | Log and audit leakage | no questions, SQL, tokens, or URLs in logs; audit stores a SQL hash, not SQL; spans carry no content; metrics labels are bounded | operators with log access still see principal ids and request ids |
| 11 | Supply chain | dependency pinning by range with a generated lockfile, `pip-audit`, `npm audit`, image scanning, Dependabot | zero-days |
| 12 | Browser-side attacks | CSP, frame denial, `nosniff`, referrer policy; result and SQL text rendered as text; CSV export neutralizes spreadsheet formulas | the CSP allows inline scripts because Next.js emits them; tighten with nonces |
| 13 | Data loss | backups with a scripted restore drill; migrations are expand-only before contract | restore time depends on data size |

## Assumptions

- PostgreSQL is not reachable from outside the private network, and its superuser is not used by
  the application.
- TLS is terminated by a trusted ingress, and HSTS is enforced there.
- The identity provider issues tokens with `sub`, `iss`, `aud`, `exp`, `roles`, and a trustworthy
  `customer_id`, and short lifetimes. This service validates tokens; it does not issue them.
- Operators with database administrator access are trusted and audited by other means.

## Not covered

Denial of service at the network layer (use the ingress or a CDN), token revocation before expiry,
per-tenant quotas and billing, row-level security on the base tables for other applications that
share the database, and multi-region replication.

## Keeping this current

Review this document when a new data source, tool, endpoint, or personal field is added, after any
incident, and at least yearly. Every threat should map to a test or an alert; if a row has neither,
add one or write down why not.
