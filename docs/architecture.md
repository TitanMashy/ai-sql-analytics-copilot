# Architecture

```mermaid
flowchart TD
    Client[API Client] --> API[FastAPI]
    API --> Retrieval[SchemaRetriever]
    Retrieval --> Provider[LLMProvider]
    Provider --> Generation[Structured SQL]
    Generation --> Validation[SQLGlot ASTValidator]
    Validation --> Service[AnalyticsQueryService]
    Service --> Analytics[(PostgreSQL analytics_readonly)]
    Service --> Serialization[Result serialization]
    Serialization --> Analyzer[AnalyticsResultAnalyzer]
    Analyzer --> Visualization[VisualizationSelector]
    Analyzer --> Summary[Grounded Summary]
    Visualization --> Response[Analytics Response]
    Summary --> Response
    Response --> API
```

The backend remains a modular monolith. `/generate` retrieves relevant schema and business definitions before calling either the deterministic mock provider or the optional Gemini provider. `/ask` passes generated SQL into the existing validator and analytics service, then analyzes returned rows locally, selects visualization metadata, and creates a grounded summary. Generation never executes SQL directly.
