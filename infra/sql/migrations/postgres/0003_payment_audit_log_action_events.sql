-- Align payment audit actions with events emitted by the current application.
-- Keep this migration compatible with the bootstrap's --single-transaction
-- wrapper.
--
-- Idempotency: the constraint is only widened when it is still the original
-- narrow baseline. The check matches the quoted action literal as it appears
-- in the constraint definition, so a later widening (0008 cash events, 0010
-- subscription events) is detected precisely. If the constraint already
-- includes 'card_payment_created' it was created by this migration or by a
-- later widening and is left untouched — replacing it unconditionally would
-- fail on databases whose audit rows already use the wider action set.
DO $$
DECLARE
    current_def text;
BEGIN
    SELECT pg_get_constraintdef(c.oid)
    INTO current_def
    FROM pg_constraint c
    JOIN pg_class t ON t.oid = c.conrelid
    WHERE t.relname = 'payment_audit_log'
      AND c.conname = 'payment_audit_log_action_check';

    IF current_def IS NULL THEN
        -- No constraint at all: establish the baseline.
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
    ELSIF position('''card_payment_created''' IN current_def) = 0 THEN
        -- Original narrow baseline (approve / reject / reveal_contact):
        -- widen it to the current event set.
        ALTER TABLE public.payment_audit_log
            DROP CONSTRAINT payment_audit_log_action_check;
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
    END IF;
END
$$;
