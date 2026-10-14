-- Feature 6: admin & dispute management (refunds, credit adjustments,
-- audit log).
-- Idempotent: safe to run multiple times.
--
-- 1. New `refunds` table (append-only; the UNIQUE order_key is the
--    idempotency guard against double-deducting a user's credits).
-- 2. Widen the status CHECK constraints on all four payment tables to
--    include 'refunded' (a refunded payment is marked in its own table).
-- 3. Widen the payment_audit_log action CHECK to include the new
--    'refund' and 'adjust_credits' event types.

CREATE TABLE IF NOT EXISTS refunds (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_key VARCHAR(255) NOT NULL UNIQUE,
    method VARCHAR(20) NOT NULL
        CHECK (method IN ('manual', 'card', 'wallet', 'cash')),
    order_id VARCHAR(255) NOT NULL,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    package VARCHAR(20) NOT NULL
        CHECK (package IN ('standard', 'premium')),
    amount_egp NUMERIC(10, 2) NOT NULL CHECK (amount_egp > 0),
    credits_deducted INTEGER NOT NULL,
    reason TEXT NOT NULL,
    admin_id VARCHAR(36) REFERENCES admins(id) ON DELETE SET NULL,
    admin_username VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Append-only: a refund is irreversible (plan 6.4). No UPDATE or DELETE.
CREATE OR REPLACE FUNCTION prevent_refund_modification() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'refunds is append-only';
END;
$$;

DROP TRIGGER IF EXISTS refunds_append_only ON refunds;
CREATE TRIGGER refunds_append_only
    BEFORE UPDATE OR DELETE ON refunds
    FOR EACH ROW EXECUTE FUNCTION prevent_refund_modification();

-- Widen the status CHECK on each payment table to include 'refunded'.
ALTER TABLE manual_payments DROP CONSTRAINT IF EXISTS manual_payments_status_check;
ALTER TABLE manual_payments
    ADD CONSTRAINT manual_payments_status_check
    CHECK (status IN ('pending', 'approved', 'rejected', 'refunded'));

ALTER TABLE card_payments DROP CONSTRAINT IF EXISTS card_payments_status_check;
ALTER TABLE card_payments
    ADD CONSTRAINT card_payments_status_check
    CHECK (status IN ('pending', 'succeeded', 'failed', 'canceled', 'refunded'));

ALTER TABLE wallet_payments DROP CONSTRAINT IF EXISTS wallet_payments_status_check;
ALTER TABLE wallet_payments
    ADD CONSTRAINT wallet_payments_status_check
    CHECK (status IN ('pending_otp', 'processing', 'succeeded',
        'failed', 'canceled', 'refunded'));

ALTER TABLE cash_payments DROP CONSTRAINT IF EXISTS cash_payments_status_check;
ALTER TABLE cash_payments
    ADD CONSTRAINT cash_payments_status_check
    CHECK (status IN ('pending', 'succeeded', 'failed', 'canceled', 'refunded'));

-- Widen the audit-log action CHECK to include the new admin event types.
ALTER TABLE payment_audit_log DROP CONSTRAINT IF EXISTS payment_audit_log_action_check;
ALTER TABLE payment_audit_log
    ADD CONSTRAINT payment_audit_log_action_check
    CHECK (action IN ('approve', 'reject', 'reveal_contact',
        'refund', 'adjust_credits',
        'webhook_received', 'webhook_signature_failed',
        'webhook_duplicate', 'validation_rejected', 'otp_failed',
        'token_expired', 'amount_mismatch', 'card_payment_created',
        'staging_rejected', 'wallet_payment_created',
        'cash_payment_created', 'cash_expired'));
