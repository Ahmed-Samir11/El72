
BEGIN;

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
        CHECK (status IN (
            'pending_otp', 'processing', 'succeeded', 'failed', 'canceled'
        )),
    otp_attempts INTEGER NOT NULL DEFAULT 0 CHECK (otp_attempts >= 0),
    otp_expires_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Ensure the user references are nullable.
ALTER TABLE payment_logs
    ALTER COLUMN user_id DROP NOT NULL;

ALTER TABLE card_payments
    ALTER COLUMN user_id DROP NOT NULL;

ALTER TABLE wallet_payments
    ALTER COLUMN user_id DROP NOT NULL;

ALTER TABLE manual_payments
    ALTER COLUMN user_id DROP NOT NULL;

ALTER TABLE payment_audit_log
    ALTER COLUMN target_user_id DROP NOT NULL;

-- Recreate user foreign keys with the intended deletion behavior.
ALTER TABLE payment_logs
    DROP CONSTRAINT IF EXISTS payment_logs_user_id_fkey;
ALTER TABLE payment_logs
    ADD CONSTRAINT payment_logs_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL;

ALTER TABLE card_payments
    DROP CONSTRAINT IF EXISTS card_payments_user_id_fkey;
ALTER TABLE card_payments
    ADD CONSTRAINT card_payments_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL;

ALTER TABLE wallet_payments
    DROP CONSTRAINT IF EXISTS wallet_payments_user_id_fkey;
ALTER TABLE wallet_payments
    ADD CONSTRAINT wallet_payments_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL;

ALTER TABLE manual_payments
    DROP CONSTRAINT IF EXISTS manual_payments_user_id_fkey;
ALTER TABLE manual_payments
    ADD CONSTRAINT manual_payments_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL;

ALTER TABLE payment_audit_log
    DROP CONSTRAINT IF EXISTS payment_audit_log_target_user_id_fkey;
ALTER TABLE payment_audit_log
    ADD CONSTRAINT payment_audit_log_target_user_id_fkey
    FOREIGN KEY (target_user_id) REFERENCES users(id) ON DELETE SET NULL;

-- Indexes used by payment lookup paths.
CREATE INDEX IF NOT EXISTS idx_payment_logs_user_id
    ON payment_logs(user_id);

CREATE INDEX IF NOT EXISTS idx_card_payments_user_created
    ON card_payments(user_id, created_at);

CREATE INDEX IF NOT EXISTS idx_wallet_payments_user_created
    ON wallet_payments(user_id, created_at);

CREATE INDEX IF NOT EXISTS idx_manual_payments_user_id
    ON manual_payments(user_id);

COMMIT;