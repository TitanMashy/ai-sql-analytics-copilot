"""The data surface exposed to analytics queries.

Analytics queries never read the application tables directly. On PostgreSQL the
``analytics_readonly`` role can only ``SELECT`` from views in the ``analytics`` schema. Those
views (created by the ``b7c2d41f8a10`` migration) do three things:

* omit personal identifiers (``PII_COLUMNS``),
* filter rows to the caller's tenant using the transaction-local ``app.scope`` and
  ``app.customer_id`` settings that the query executor sets for every request, and
* fail closed: if the settings are missing or unrecognised, no rows are visible.

The role's ``search_path`` is ``analytics``, so generated SQL keeps using plain table names.
Prompts, the SQL validator, and the schema API all use :func:`get_schema_metadata`, which
applies the same column exclusions, so the model is never shown columns it cannot read.
"""

from __future__ import annotations

ANALYTICS_SCHEMA = "analytics"

# Direct personal identifiers that must never be readable through analytics queries.
PII_COLUMNS: dict[str, frozenset[str]] = {
    "customers": frozenset({"name", "email"}),
    "users": frozenset({"name", "email"}),
    "drivers": frozenset({"name", "phone", "license_number"}),
}

# Tenant scoping: how each analytics view finds the owning customer.
# ``customers`` is filtered on its own id; tables with a customer_id column filter on it;
# ``vehicle_locations`` has no customer column and is scoped through its vehicle.
TENANT_ROOT_TABLE = "customers"
TENANT_VIA_VEHICLE_TABLES = frozenset({"vehicle_locations"})

# Values of the transaction-local ``app.scope`` setting.
SCOPE_TENANT = "tenant"
SCOPE_GLOBAL = "global"
SCOPE_DENY = "deny"
