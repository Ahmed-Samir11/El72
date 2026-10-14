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
-- Best-effort de-escalation: if el72_monitor pre-exists with more
-- privileges than monitoring needs (e.g. from an earlier manual setup),
-- drop the database-level CREATE/TEMP privileges. REVOKE is a silent no-op
-- when the role does not hold the privilege.
DO $$
BEGIN
    EXECUTE format(
        'REVOKE CREATE, TEMPORARY ON DATABASE %I FROM el72_monitor',
        current_database()
    );
END
$$;
