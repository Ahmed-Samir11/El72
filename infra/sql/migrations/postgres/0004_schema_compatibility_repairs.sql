-- Repair schema compatibility gaps without replaying obsolete legacy migrations.

-- Normalize NULL statuses before adding the check: the app only ever writes
-- ACTIVE/DELETED and auth filters on status = 'ACTIVE', so a NULL row is
-- unreachable and restoring the column default is the safe move.
UPDATE public.users
    SET status = 'ACTIVE'
    WHERE status IS NULL;

-- Non-NULL unknown statuses are deliberately NOT normalized: the application
-- only writes ACTIVE/DELETED, so any other value implies a manual database
-- change (e.g. an operator-suspended account). Silently re-activating it
-- would be unsafe — fail with the offending values instead so an operator
-- can review and update those rows explicitly, then re-run this migration.
DO $$
DECLARE
    bad_values text;
BEGIN
    SELECT string_agg(DISTINCT status, ', ')
    INTO bad_values
    FROM public.users
    WHERE status NOT IN ('ACTIVE', 'DELETED');
    IF bad_values IS NOT NULL THEN
        RAISE EXCEPTION
            'users.status contains values outside (ACTIVE, DELETED): %%. '
            'Update those rows explicitly, then re-run this migration.'
            USING ERRCODE = 'integrity_constraint_violation', DETAIL = bad_values;
    END IF;
END
$$;

-- Add the user status constraint only when it is absent; validate in the
-- same block so an already-present (already-valid) constraint is never
-- re-validated on every run.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.users'::regclass
          AND conname = 'users_status_check'
    ) THEN
        -- NOT VALID so the ADD does not take a heavyweight scan lock; the
        -- data is normalized above, so the subsequent VALIDATE succeeds.
        ALTER TABLE public.users
            ADD CONSTRAINT users_status_check
            CHECK (status IN ('ACTIVE', 'DELETED')) NOT VALID;
        ALTER TABLE public.users
            VALIDATE CONSTRAINT users_status_check;
    END IF;
END
$$;

-- The canonical schema declares alerts.active_status NOT NULL DEFAULT TRUE.
-- Repair any legacy NULLs, then enforce the constraint so existing
-- databases converge on the canonical definition.
UPDATE public.alerts
    SET active_status = TRUE
    WHERE active_status IS NULL;

ALTER TABLE public.alerts
    ALTER COLUMN active_status SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_users_status
    ON public.users(status);

-- Restore indexes expected by the legacy alert compatibility migration.
CREATE INDEX IF NOT EXISTS idx_alerts_sku
    ON public.alerts(sku);

CREATE INDEX IF NOT EXISTS idx_alerts_notify_channel
    ON public.alerts(notify_channel);
