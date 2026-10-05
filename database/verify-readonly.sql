-- Verifies the analytics_readonly privilege model. Run after migrations:
--   make verify-permissions
DO $$
DECLARE
    object_name text;
    column_name text;
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_namespace WHERE nspname = 'analytics') THEN
        RAISE EXCEPTION 'analytics schema is missing; run migrations';
    END IF;

    -- 1. No access of any kind to base tables in public (including alembic_version/seed_runs).
    FOR object_name IN
        SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public'
    LOOP
        IF has_table_privilege('analytics_readonly', format('public.%I', object_name), 'SELECT')
            OR has_table_privilege('analytics_readonly', format('public.%I', object_name), 'INSERT')
            OR has_table_privilege('analytics_readonly', format('public.%I', object_name), 'UPDATE')
            OR has_table_privilege('analytics_readonly', format('public.%I', object_name), 'DELETE')
        THEN
            RAISE EXCEPTION 'analytics_readonly must not have privileges on public.%', object_name;
        END IF;
    END LOOP;

    -- 2. Views are SELECT-only.
    FOR object_name IN
        SELECT viewname FROM pg_catalog.pg_views WHERE schemaname = 'analytics'
    LOOP
        IF NOT has_table_privilege('analytics_readonly', format('analytics.%I', object_name), 'SELECT') THEN
            RAISE EXCEPTION 'analytics_readonly cannot SELECT from analytics.%', object_name;
        END IF;
        IF has_table_privilege('analytics_readonly', format('analytics.%I', object_name), 'INSERT')
            OR has_table_privilege('analytics_readonly', format('analytics.%I', object_name), 'UPDATE')
            OR has_table_privilege('analytics_readonly', format('analytics.%I', object_name), 'DELETE')
        THEN
            RAISE EXCEPTION 'analytics_readonly has write access to analytics.%', object_name;
        END IF;
    END LOOP;

    -- 3. No personal-data columns are exposed.
    FOR column_name IN
        SELECT c.table_name || '.' || c.column_name
        FROM information_schema.columns c
        WHERE c.table_schema = 'analytics'
          AND ((c.table_name IN ('customers', 'users') AND c.column_name IN ('name', 'email'))
            OR (c.table_name = 'drivers' AND c.column_name IN ('name', 'phone', 'license_number')))
    LOOP
        RAISE EXCEPTION 'analytics view exposes personal data column %', column_name;
    END LOOP;

    -- 4. The role cannot create objects anywhere it can see.
    IF has_schema_privilege('analytics_readonly', 'public', 'CREATE')
        OR has_schema_privilege('analytics_readonly', 'analytics', 'CREATE')
    THEN
        RAISE EXCEPTION 'analytics_readonly can CREATE in a schema';
    END IF;
END
$$;

SELECT 'analytics_readonly permissions verified' AS result;
