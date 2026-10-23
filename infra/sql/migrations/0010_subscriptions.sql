-- Feature 7: recurring subscriptions (Paymob subscriptions).
-- Idempotent: safe to run multiple times.
--
-- 1. New `subscriptions` table (one active subscription per user; the
--    recurring mandate is charged by Paymob each month).
-- 2. New `subscription_renewals` table (append-only; the UNIQUE
--    paymob_renewal_id is the idempotency guard against double-charging,
--    plan 7.6).
-- 3. Widen the payment_audit_log action CHECK to include the new
--    subscription event types.

CREATE TABLE IF NOT EXISTS subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    paymob_subscription_id VARCHAR(255) NOT NULL UNIQUE,
    card_payment_method_id VARCHAR(255) NOT NULL,
    package VARCHAR(20) NOT NULL
        CHECK (package IN ('standard', 'premium')),
    amount_egp NUMERIC(10, 2) NOT NULL CHECK (amount_egp > 0),
    billing_interval VARCHAR(10) NOT NULL DEFAULT 'month'
        CHECK (billing_interval IN ('month')),
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'canceled', 'failed')),
    failed_renewals INTEGER NOT NULL DEFAULT 0,
    next_charge TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    canceled_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS ix_subscriptions_user_status
    ON subscriptions (user_id, status);

-- One active subscription per user, enforced at the database level
-- (plan 7.1). Partial unique index: only 'active' rows are constrained,
-- so a user can keep multiple historical (canceled/failed) subscriptions.
DROP INDEX IF EXISTS uq_subscriptions_one_active_per_user;
CREATE UNIQUE INDEX uq_subscriptions_one_active_per_user
    ON subscriptions (user_id) WHERE status = 'active';

-- Append-only: a renewal is a historical record of a charge. No UPDATE
-- or DELETE (plan 7.6).
CREATE TABLE IF NOT EXISTS subscription_renewals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subscription_id UUID NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
    paymob_renewal_id VARCHAR(255) NOT NULL UNIQUE,
    amount_egp NUMERIC(10, 2) NOT NULL CHECK (amount_egp > 0),
    status VARCHAR(20) NOT NULL
        CHECK (status IN ('succeeded', 'failed')),
    charged_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_subscription_renewals_subscription
    ON subscription_renewals (subscription_id, created_at);

CREATE OR REPLACE FUNCTION prevent_renewal_modification() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'subscription_renewals is append-only';
END;
$$;

DROP TRIGGER IF EXISTS subscription_renewals_append_only ON subscription_renewals;
CREATE TRIGGER subscription_renewals_append_only
    BEFORE UPDATE OR DELETE ON subscription_renewals
    FOR EACH ROW EXECUTE FUNCTION prevent_renewal_modification();

-- Widen the audit-log action CHECK to include the new subscription
-- event types.
ALTER TABLE payment_audit_log DROP CONSTRAINT IF EXISTS payment_audit_log_action_check;
ALTER TABLE payment_audit_log
    ADD CONSTRAINT payment_audit_log_action_check
    CHECK (action IN ('approve', 'reject', 'reveal_contact',
        'refund', 'adjust_credits',
        'webhook_received', 'webhook_signature_failed',
        'webhook_duplicate', 'validation_rejected', 'otp_failed',
        'token_expired', 'amount_mismatch', 'card_payment_created',
        'staging_rejected', 'wallet_payment_created',
        'cash_payment_created', 'cash_expired',
        'subscription_created', 'subscription_canceled',
        'subscription_renewal_succeeded', 'subscription_renewal_failed',
        'subscription_auto_canceled'));
