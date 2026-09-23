DO $$
DECLARE
    table_name text;
BEGIN
    FOR table_name IN
        SELECT tablename
        FROM pg_catalog.pg_tables
        WHERE schemaname = 'public'
    LOOP
        IF NOT has_table_privilege('analytics_readonly', format('public.%I', table_name), 'SELECT') THEN
            RAISE EXCEPTION 'analytics_readonly cannot SELECT from %', table_name;
        END IF;
        IF has_table_privilege('analytics_readonly', format('public.%I', table_name), 'INSERT')
            OR has_table_privilege('analytics_readonly', format('public.%I', table_name), 'UPDATE')
            OR has_table_privilege('analytics_readonly', format('public.%I', table_name), 'DELETE')
        THEN
            RAISE EXCEPTION 'analytics_readonly has write access to %', table_name;
        END IF;
    END LOOP;

    IF has_schema_privilege('analytics_readonly', 'public', 'CREATE') THEN
        RAISE EXCEPTION 'analytics_readonly can CREATE in public schema';
    END IF;
END
$$;

SELECT 'analytics_readonly permissions verified' AS result;