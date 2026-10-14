-- Align payment audit actions with events emitted by the current application.
-- Keep this migration compatible with the bootstrap's --single-transaction wrapper.

ALTER TABLE public.payment_audit_log
    DROP CONSTRAINT IF EXISTS payment_audit_log_action_check;

ALTER TABLE public.payment_audit_log
    ADD CONSTRAINT payment_audit_log_action_check
    CHECK (action IN (
        'approve',
        'reject',
        'reveal_contact',
        'webhook_received',
        'webhook_signature_failed',
        'webhook_duplicate',
        'validation_rejected',
        'otp_failed',
        'token_expired',
        'amount_mismatch',
        'card_payment_created',
        'staging_rejected',
        'wallet_payment_created'
    ));
