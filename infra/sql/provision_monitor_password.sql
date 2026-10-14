-- Run using psql with the monitor_password variable supplied securely.
-- The psql variable is quoted as a SQL literal by psql.
SELECT format(
    'ALTER ROLE el72_monitor PASSWORD %L',
    :'monitor_password'
)
\gexec