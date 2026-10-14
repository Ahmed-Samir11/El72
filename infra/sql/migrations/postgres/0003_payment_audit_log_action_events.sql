-- Align payment audit actions with events emitted by the current application.
-- Keep this migration compatible with the bootstrap's --single-transaction
-- wrapper.
--
-- Idempotency: the constraint is replaced only when the current definition
-- is missing at least one of the target actions (matched as quoted literals
-- exactly as they appear in a CHECK definition). A constraint created by
-- this migration, or already widened by 0008 (cash events) / 0010
-- (subscription events), contains the full target set and is left
-- untouched — replacing it unconditionally would fail on databases whose
-- audit rows already use the wider action set.
DO $$
DECLARE
    current_def text;
    target_actions text[] := ARRAY[
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
    ];
    missing_count integer;
BEGIN
    SELECT pg_get_constraintdef(c.oid)
    INTO current_def
    FROM pg_constraint c
    JOIN pg_class t ON t.oid = c.conrelid
    WHERE t.relname = 'payment_audit_log'
      AND c.conname = 'payment_audit_log_action_check';

    IF current_def IS NOT NULL THEN
        -- Count target actions absent from the current definition.
        SELECT count(*)
        INTO missing_count
        FROM unnest(target_actions) AS act
        WHERE position(''' || act || ''' IN current_def) = 0;

        IF missing_count = 0 THEN
            -- Already covers the target set (this migration or a later
            -- widening): nothing to do.
            RETURN;
        END IF;

        ALTER TABLE public.payment_audit_log
            DROP CONSTRAINT payment_audit_log_action_check;
    END IF;

    -- Establish / restore the baseline set (0008 and 0010 widen it later).
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
END
$$;
