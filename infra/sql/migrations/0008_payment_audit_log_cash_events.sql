-- Feature 3: widen the payment_audit_log action CHECK to include the new
-- cash-flow event types `cash_payment_created` and `cash_expired`.
-- Idempotent: drops and recreates the constraint with the widened set.

ALTER TABLE payment_audit_log DROP CONSTRAINT IF EXISTS payment_audit_log_action_check;
ALTER TABLE payment_audit_log
    ADD CONSTRAINT payment_audit_log_action_check
    CHECK (action IN ('approve', 'reject', 'reveal_contact',
        'webhook_received', 'webhook_signature_failed',
        'webhook_duplicate', 'validation_rejected', 'otp_failed',
        'token_expired', 'amount_mismatch', 'card_payment_created',
        'staging_rejected', 'wallet_payment_created',
        'cash_payment_created', 'cash_expired'));
