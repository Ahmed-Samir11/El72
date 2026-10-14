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
--
-- When a replacement is needed, the new constraint is the UNION of the
-- target set and any actions already present in the old definition, so a
-- custom or extra action is never dropped.
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
    extracted text[];
    action_list text;
    a text;
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

        -- Preserve any extra actions already present. pg_get_constraintdef
        -- renders the IN list as: CHECK ((action = ANY (ARRAY[...]::text[]))).
        SELECT array_agg(regexp_replace(trim(e), '''', '', 'g') ORDER BY e)
        INTO extracted
        FROM unnest(string_to_array(
            substring(current_def FROM 'ARRAY\[([^\]]*)\]'), ','
        )) AS e;

        ALTER TABLE public.payment_audit_log
            DROP CONSTRAINT payment_audit_log_action_check;
    ELSE
        extracted := ARRAY[]::text[];
    END IF;

    -- Union: target actions first, then extras not already in the target set.
    SELECT string_agg(''' || a || '''', ', ' ORDER BY a)
    INTO action_list
    FROM (
        SELECT DISTINCT a FROM (
            SELECT unnest(target_actions) AS a
            UNION
            SELECT unnest(COALESCE(extracted, ARRAY[]::text[]))
        ) unioned
    ) all_actions;

    EXECUTE format(
        'ALTER TABLE public.payment_audit_log '
        'ADD CONSTRAINT payment_audit_log_action_check CHECK (action IN (%s))',
        action_list
    );
END
$$;
