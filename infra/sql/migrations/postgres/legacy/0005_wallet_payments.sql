-- Feature 2: wallet payments tracking table (Paymob wallet flow).
-- Idempotent: safe to run multiple times.
--
-- The wallet NUMBER is deliberately NOT stored — only the wallet TYPE is
-- kept for audit/ledger purposes (plan 2.8).

CREATE TABLE IF NOT EXISTS wallet_payments (
    id SERIAL PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    -- Set at /payment/confirm; unique — one Paymob payment per record.
    paymob_payment_id VARCHAR(255) UNIQUE,
    wallet_type VARCHAR(30) NOT NULL,
    package VARCHAR(20) NOT NULL
        CHECK (package IN ('standard', 'premium')),
    amount_egp NUMERIC(10, 2) NOT NULL CHECK (amount_egp > 0),
    status VARCHAR(20) NOT NULL DEFAULT 'pending_otp'
        CHECK (status IN ('pending_otp', 'processing', 'succeeded',
            'failed', 'canceled')),
    -- OTP brute-force guard (plan 2.1): max 3 attempts, then canceled.
    otp_attempts INTEGER NOT NULL DEFAULT 0 CHECK (otp_attempts >= 0),
    -- OTP challenge expiry (60 s from payment creation, plan 2.1).
    otp_expires_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wallet_payments_user_created
    ON wallet_payments(user_id, created_at);
