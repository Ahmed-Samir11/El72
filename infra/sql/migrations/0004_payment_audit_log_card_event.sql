-- Feature 1: widen the payment_audit_log action CHECK to include the new
-- card-flow event types `card_payment_created` and `staging_rejected`.
-- Idempotent: drops and recreates the constraint with the widened set.

ALTER TABLE payment_audit_log DROP CONSTRAINT IF EXISTS payment_audit_log_action_check;
ALTER TABLE payment_audit_log
    ADD CONSTRAINT payment_audit_log_action_check
    CHECK (action IN ('approve', 'reject', 'reveal_contact',
        'webhook_received', 'webhook_signature_failed',
        'webhook_duplicate', 'validation_rejected', 'otp_failed',
        'token_expired', 'amount_mismatch', 'card_payment_created',
        'staging_rejected'));
