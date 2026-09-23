# Architecture

```mermaid
flowchart TD
    Client[API Client] --> API[FastAPI]
    API --> Retrieval[SchemaRetriever]
    Retrieval --> Provider[LLMProvider]
    Provider --> Generation[Structured SQL]
    Generation --> Validation[SQLValidator placeholder]
    Validation --> Service[AnalyticsQueryService]
    Service --> Analytics[(PostgreSQL analytics_readonly)]
    Service --> Serialization[Result serialization]
    Serialization --> API
```

The backend remains a modular monolith. `/generate` retrieves relevant schema and business definitions before calling either the deterministic mock provider or the optional OpenAI provider. `/ask` passes generated SQL into the existing validator and analytics service; generation never executes SQL directly.
