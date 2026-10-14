-- Set the password for the restricted el72_monitor role.
--
-- Run once PER DATABASE (the operational Postgres database AND the
-- TimescaleDB database each have their own role). Pass the secret through
-- the environment, NOT through psql arguments or -v variables: command-line
-- arguments are visible to other users via the process list, whereas an
-- environment variable is not.
--
--   PGPASSWORD='<app password>' MONITOR_PASSWORD='<generated>' \
--       psql "$DATABASE_URL" -f infra/sql/provision_monitor_password.sql
--   PGPASSWORD='<app password>' MONITOR_PASSWORD='<generated>' \
--       psql "$TIMESCALE_URL" -f infra/sql/provision_monitor_password.sql
--
-- The same password may be used for both databases (it is the value of
-- DB_MONITOR_PASSWORD in .env).
--
-- Safety: if MONITOR_PASSWORD is unset, env() makes psql abort before any
-- statement runs; the DO block below additionally rejects short passwords.
-- The secret is read from the environment into a psql client variable, then
-- interpolated with :'monitor_password' — it never appears in psql argv.
\set monitor_password `env('MONITOR_PASSWORD')`

DO $$
BEGIN
    IF length(:'monitor_password') < 8 THEN
        RAISE EXCEPTION
            'monitor_password must be at least 8 characters long'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
END
$$;

SELECT format(
    'ALTER ROLE el72_monitor PASSWORD %L',
    :'monitor_password'
)
\gexec
