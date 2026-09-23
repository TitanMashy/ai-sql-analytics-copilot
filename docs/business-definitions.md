# Business Definitions

The generation layer includes these definitions in the LLM prompt when relevant:

- **Revenue:** `SUM(invoices.total_amount)` for non-cancelled invoices. Payments represent cash collection, not billed revenue.
- **Active vehicle:** `vehicles.status = 'active'`.
- **Completed trip:** `trips.trip_status = 'completed'`.
- **Fuel cost:** `SUM(fuel_records.total_cost)`.
- **Idle time:** `SUM(trips.idle_time_minutes)`, or `AVG` for average-idle questions.
- **Payments:** linked to invoices with `payments.invoice_id`; collection state comes from `payments.status`.

These definitions are deterministic prompt context, not a security control. Generated SQL is still untrusted and must pass the existing validator before `/ask` can execute it.