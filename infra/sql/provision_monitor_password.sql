-- Set the password for the restricted el72_monitor role.
--
-- Run once PER DATABASE (the operational Postgres database AND the
-- TimescaleDB database each have their own role), e.g.:
--   PGPASSWORD='<app password>' psql "$DATABASE_URL" \
--       -v monitor_password='<generated>' -f infra/sql/provision_monitor_password.sql
--   PGPASSWORD='<app password>' psql "$TIMESCALE_URL" \
--       -v monitor_password='<generated>' -f infra/sql/provision_monitor_password.sql
--
-- The same password may be used for both databases (it is the value of
-- DB_MONITOR_PASSWORD in .env).
--
-- Input validation: psql refuses to run if the variable is unset or empty
-- (undefined/empty :variables error out under -v), and the DO block below
-- rejects short passwords. The variable is quoted as a SQL literal by psql.
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
