-- Run under a single transaction (scripts/db-bootstrap.sh applies this file
-- with psql --single-transaction). Do NOT add explicit BEGIN/COMMIT here:
-- an inner COMMIT would end the wrapper transaction early and break
-- file-level atomicity.

-- Precondition guard: fail with an actionable error instead of an opaque
-- column-type mismatch deeper in the migration.
DO $$
DECLARE
    id_type text;
BEGIN
    SELECT format_type(att.atttypid, att.atttypmod)
    INTO id_type
    FROM pg_attribute att
    JOIN pg_class c ON c.oid = att.attrelid
    WHERE c.relname = 'users'
      AND c.relnamespace = 'public'::regnamespace
      AND att.attname = 'id';

    IF id_type IS NULL THEN
        RAISE EXCEPTION
            'table public.users not found; apply the canonical schema '
            '(infra/sql/schema/postgres.sql) before this migration';
    ELSIF id_type = 'uuid' THEN
        RAISE EXCEPTION
            'users.id is UUID; this migration requires the reconciled '
            'INTEGER users.id (see the header of '
            'infra/sql/schema/postgres.sql). Rebuild the database from a '
            'dump with an id remap first.';
    END IF;
END
$$;

-- Fallback table definitions for databases where the canonical schema
-- (infra/sql/schema/postgres.sql) was never applied. On a canonical fresh
-- install these CREATE TABLE IF NOT EXISTS statements are no-ops; the
-- canonical schema remains the source of truth for the full column set.
-- manual_payments and payment_audit_log are deliberately NOT recreated here:
-- they belong to the canonical schema, and the alignment loop below skips
-- any table it does not find.
--
-- Precondition: users.id is INTEGER (the reconciled operational schema).
-- This migration does not convert a legacy UUID users.id — see the header
-- of infra/sql/schema/postgres.sql; rebuild such a database instead.

-- Payment logs: preserve records when a user account is deleted.
-- UUID remains the payment-log primary key.
CREATE TABLE IF NOT EXISTS payment_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER,
    paymob_order_id VARCHAR(255) UNIQUE NOT NULL,
    amount NUMERIC(10, 2) NOT NULL,
    currency VARCHAR(10) NOT NULL DEFAULT 'EGP',
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    tier VARCHAR(20) NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Card payment records.
CREATE TABLE IF NOT EXISTS card_payments (
    id SERIAL PRIMARY KEY,
    user_id INTEGER,
    paymob_payment_id VARCHAR(255) UNIQUE,
    package VARCHAR(20) NOT NULL
        CHECK (package IN ('standard', 'premium')),
    amount_egp NUMERIC(10, 2) NOT NULL CHECK (amount_egp > 0),
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'succeeded', 'failed', 'canceled')),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Wallet payment records.
CREATE TABLE IF NOT EXISTS wallet_payments (
    id SERIAL PRIMARY KEY,
    user_id INTEGER,
    paymob_payment_id VARCHAR(255) UNIQUE,
    wallet_type VARCHAR(30) NOT NULL,
    package VARCHAR(20) NOT NULL
        CHECK (package IN ('standard', 'premium')),
    amount_egp NUMERIC(10, 2) NOT NULL CHECK (amount_egp > 0),
    status VARCHAR(20) NOT NULL DEFAULT 'pending_otp'
        CHECK (status IN ('pending_otp', 'processing', 'succeeded',
            'failed', 'canceled')),
    otp_attempts INTEGER NOT NULL DEFAULT 0 CHECK (otp_attempts >= 0),
    otp_expires_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Align every user reference to the intended behavior: nullable column,
-- orphaned rows cleared, and the foreign key recreated as ON DELETE SET NULL
-- so payment/audit records survive user deletion.
--
-- Robustness notes:
-- * Tables are processed only when they exist (manual_payments,
--   payment_audit_log and cash_payments come from other schema sources).
-- * All foreign keys on the column are dropped by scanning pg_constraint,
--   not by assumed default name — a renamed legacy FK cannot survive with
--   its old (e.g. CASCADE) behavior.
DO $$
DECLARE
    v RECORD;
    fk_name text;
BEGIN
    FOR v IN
        SELECT * FROM (
            VALUES
                ('payment_logs', 'user_id'),
                ('card_payments', 'user_id'),
                ('wallet_payments', 'user_id'),
                ('manual_payments', 'user_id'),
                ('cash_payments', 'user_id'),
                ('payment_audit_log', 'target_user_id')
        ) AS refs(tablename, columnname)
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = 'public' AND tablename = v.tablename
        ) THEN
            CONTINUE;
        END IF;

        -- Nullable (no-op when already nullable).
        EXECUTE format(
            'ALTER TABLE public.%I ALTER COLUMN %I DROP NOT NULL',
            v.tablename, v.columnname
        );

        -- Drop every FK on this column (any name), so renamed legacy
        -- constraints cannot keep their old deletion behavior.
        FOR fk_name IN
            SELECT c.conname
            FROM pg_constraint c
            JOIN pg_class rel ON rel.oid = c.conrelid
            WHERE rel.relname = v.tablename
              AND rel.relnamespace = 'public'::regnamespace
              AND c.contype = 'f'
              AND EXISTS (
                  SELECT 1
                  FROM unnest(c.conkey) AS k(attnum)
                  JOIN pg_attribute a
                    ON a.attrelid = c.conrelid AND a.attnum = k.attnum
                  WHERE a.attname = v.columnname
              )
        LOOP
            EXECUTE format(
                'ALTER TABLE public.%I DROP CONSTRAINT %I',
                v.tablename, fk_name
            );
        END LOOP;

        -- Clear orphaned references; re-adding the FK would otherwise fail
        -- on rows whose user no longer exists.
        EXECUTE format(
            'UPDATE public.%I SET %I = NULL '
            'WHERE %I IS NOT NULL AND NOT EXISTS '
            '(SELECT 1 FROM users u WHERE u.id = %I.%I)',
            v.tablename, v.columnname,
            v.tablename, v.tablename, v.columnname
        );

        -- Recreate the FK with the intended deletion behavior.
        EXECUTE format(
            'ALTER TABLE public.%I ADD CONSTRAINT %I '
            'FOREIGN KEY (%I) REFERENCES users(id) ON DELETE SET NULL',
            v.tablename,
            v.tablename || '_' || v.columnname || '_fkey',
            v.columnname
        );
    END LOOP;
END
$$;

-- Indexes used by payment lookup paths. The first three tables are
-- guaranteed to exist by the fallback CREATEs above; the rest are guarded.
CREATE INDEX IF NOT EXISTS idx_payment_logs_user_id
    ON payment_logs(user_id);

CREATE INDEX IF NOT EXISTS idx_card_payments_user_created
    ON card_payments(user_id, created_at);

CREATE INDEX IF NOT EXISTS idx_wallet_payments_user_created
    ON wallet_payments(user_id, created_at);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'manual_payments'
    ) THEN
        CREATE INDEX IF NOT EXISTS idx_manual_payments_user_id
            ON public.manual_payments(user_id);
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'cash_payments'
    ) THEN
        CREATE INDEX IF NOT EXISTS idx_cash_payments_user_id
            ON public.cash_payments(user_id);
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'payment_audit_log'
    ) THEN
        CREATE INDEX IF NOT EXISTS idx_payment_audit_log_target_user_id
            ON public.payment_audit_log(target_user_id);
    END IF;
END
$$;
