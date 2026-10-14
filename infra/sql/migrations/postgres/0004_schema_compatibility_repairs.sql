-- Repair schema compatibility gaps without replaying obsolete legacy migrations.

-- Normalize unknown/NULL status values before adding the check: VALIDATE
-- CONSTRAINT would otherwise fail on rows with legacy values. Mapping them
-- to ACTIVE is the least destructive option (keeps the account usable).
UPDATE public.users
    SET status = 'ACTIVE'
    WHERE status IS NULL OR status NOT IN ('ACTIVE', 'DELETED');

-- Add the user status constraint only when it is absent.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.users'::regclass
          AND conname = 'users_status_check'
    ) THEN
        ALTER TABLE public.users
            ADD CONSTRAINT users_status_check
            CHECK (status IN ('ACTIVE', 'DELETED')) NOT VALID;
    END IF;
END
$$;

-- Validate existing data before relying on the constraint.
ALTER TABLE public.users
    VALIDATE CONSTRAINT users_status_check;

CREATE INDEX IF NOT EXISTS idx_users_status
    ON public.users(status);

-- Restore indexes expected by the legacy alert compatibility migration.
CREATE INDEX IF NOT EXISTS idx_alerts_sku
    ON public.alerts(sku);

CREATE INDEX IF NOT EXISTS idx_alerts_notify_channel
    ON public.alerts(notify_channel);
