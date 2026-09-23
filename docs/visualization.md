# Result Intelligence and Visualization

Sprint 6 analyzes query results after secure SQL execution. The frontend receives machine-readable rows plus backend-validated display metadata; it does not decide whether a chart is safe or compatible.

## Selection Rules

- One numeric aggregate row with a KPI-like question: `kpi` visualization.
- Datetime plus numeric data: `line` visualization.
- Categorical plus numeric data: `bar` visualization.
- A small categorical distribution with at most six categories: `pie` visualization.
- Complex multi-dimensional data, empty data, or incompatible fields: `table` fallback.

The selector validates every referenced axis field against returned columns, checks that rows are non-empty, and falls back to `table` on failure. Visualization type, title, axes, and formatting are represented in the typed response contract.

## KPI Detection

KPI detection is deterministic. It requires one result row, a numeric non-identifier column, and KPI-like question language such as total, count, number, average, revenue, or cost. Formats include `currency`, `integer`, `decimal`, and `percentage`.

## Formatting and Warnings

Result values remain machine-readable. Decimal values become JSON numbers, temporal values become ISO strings, UUIDs become strings, and NULL remains NULL. Column profiles identify numeric, categorical, datetime, identifier, and unknown values. Empty results and columns with a high NULL fraction produce warnings.

## Summaries

The default summary is deterministic and uses only returned rows. It reports the KPI or the highest categorical value for a numeric measure. Summaries can be disabled with `ENABLE_RESULT_SUMMARY=false`. A future Gemini summary provider may receive only the question, SQL, columns, and returned rows; summary output never affects SQL generation or execution, and a summary failure must not fail the analytics response.