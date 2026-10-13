-- Create the monitoring database role for the Prometheus DB exporters.
-- Review finding: database monitoring role is required but not provisioned
-- in the repository.
CREATE ROLE IF NOT EXISTS el72_monitor WITH LOGIN;
