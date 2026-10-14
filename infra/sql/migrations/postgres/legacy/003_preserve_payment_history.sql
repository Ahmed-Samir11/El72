-- SUPERSEDED by 0002_payment_history_fk_alignment.sql.
--
-- This migration originally re-created the payment user foreign keys as
-- ON DELETE SET NULL, but it (a) duplicated work that 0002 now performs
-- more completely, and (b) lacked the orphan-row cleanup that 0002 does —
-- on a database with orphaned payment rows the ADD CONSTRAINT here would
-- fail where 0002 succeeds.
--
-- It is kept as an intentional no-op so replaying the legacy migration
-- sequence stays safe. Do not re-enable the statements below; run 0002
-- (via scripts/db-bootstrap.sh) instead.

SELECT 1;
