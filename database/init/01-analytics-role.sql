DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'analytics_readonly') THEN
        CREATE ROLE analytics_readonly LOGIN;
    END IF;
END
$$;

\getenv analytics_password ANALYTICS_DATABASE_PASSWORD
SELECT format('ALTER ROLE analytics_readonly PASSWORD %L', :'analytics_password') \gexec

GRANT CONNECT ON DATABASE app TO analytics_readonly;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- The role never receives privileges on the application tables in "public" and no default
-- privileges are granted, so tables added later are NOT readable automatically.
-- Analytics queries read tenant-scoped, PII-free views in the "analytics" schema, which the
-- Alembic migration b7c2d41f8a10 creates and grants. Until that migration runs the role can
-- read nothing, which is the intended fail-closed state.
ALTER ROLE analytics_readonly SET search_path = analytics;
