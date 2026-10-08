-- Migration 0001: extend payment_audit_log for Feature 5 (security & audit).
--
-- New installs get this schema directly from infra/sql/schema/postgres.sql; this
-- file only upgrades EXISTING deployments that already have the Feature 0
-- payment_audit_log table. Safe to run multiple times (idempotent).
--
-- Apply with:  psql "$DATABASE_URL" -f infra/sql/migrations/postgres/legacy/0001_payment_audit_log_detail.sql

BEGIN;

-- New column: free-form, sanitized event detail (e.g. webhook payload notes).
ALTER TABLE payment_audit_log ADD COLUMN IF NOT EXISTS detail TEXT;

-- Widen the action CHECK from the Feature 0 admin-action set to the full
-- Feature 5 payment-event set (webhook_received, otp_failed, ...).
ALTER TABLE payment_audit_log DROP CONSTRAINT IF EXISTS payment_audit_log_action_check;
ALTER TABLE payment_audit_log
    ADD CONSTRAINT payment_audit_log_action_check
    CHECK (action IN ('approve', 'reject', 'reveal_contact',
        'webhook_received', 'webhook_signature_failed', 'otp_failed',
        'token_expired', 'amount_mismatch'));

COMMIT;
