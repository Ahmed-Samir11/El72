-- Create the monitoring role if it does not exist.
-- Apply to the PostgreSQL database and the TimescaleDB database.
-- Password provisioning is handled separately through a secret.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_roles
        WHERE rolname = 'el72_monitor'
    ) THEN
        CREATE ROLE el72_monitor WITH LOGIN;
    END IF;
END
$$;

-- PostgreSQL's built-in monitoring role grants the privileges needed
-- by standard PostgreSQL monitoring queries without granting superuser.
GRANT pg_monitor TO el72_monitor;