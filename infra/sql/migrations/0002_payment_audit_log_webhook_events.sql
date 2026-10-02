-- Migration 0002: extend payment_audit_log for Feature 4 (webhook & credit
-- granting).
--
-- New installs get this schema directly from infra/sql/schema.sql; this file
-- only upgrades EXISTING deployments that already have the payment_audit_log
-- table. Safe to run multiple times (idempotent).
--
-- Apply with:  psql "$DATABASE_URL" -f infra/sql/migrations/0002_payment_audit_log_webhook_events.sql

BEGIN;

-- Widen the action CHECK with the Feature 4 webhook outcomes:
--   webhook_duplicate    duplicate delivery short-circuited (idempotency)
--   validation_rejected  webhook rejected by reference_id/user/package/payload
--                        validation (400)
ALTER TABLE payment_audit_log DROP CONSTRAINT IF EXISTS payment_audit_log_action_check;
ALTER TABLE payment_audit_log
    ADD CONSTRAINT payment_audit_log_action_check
    CHECK (action IN ('approve', 'reject', 'reveal_contact',
        'webhook_received', 'webhook_signature_failed',
        'webhook_duplicate', 'validation_rejected', 'otp_failed',
        'token_expired', 'amount_mismatch'));

COMMIT;
