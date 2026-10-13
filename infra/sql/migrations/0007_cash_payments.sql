-- Feature 3: cash payments tracking table (Paymob cash flow).
-- Idempotent: safe to run multiple times.
--
-- The payment code is not PII (it identifies the payment, not the user),
-- is random/non-sequential, and expires after 24 h (plan 3.1/3.2/3.3).

CREATE TABLE IF NOT EXISTS cash_payments (
    id SERIAL PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    -- Set at /payment/confirm; unique — one Paymob payment per record.
    paymob_payment_id VARCHAR(255) UNIQUE,
    -- Random single-use code shown to the user (8 unambiguous chars,
    -- non-sequential; never contains user data — plan 3.1/3.2).
    payment_code VARCHAR(32) UNIQUE NOT NULL,
    cash_type VARCHAR(20) NOT NULL CHECK (cash_type IN ('fawry', 'bank')),
    package VARCHAR(20) NOT NULL
        CHECK (package IN ('standard', 'premium')),
    amount_egp NUMERIC(10, 2) NOT NULL CHECK (amount_egp > 0),
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'succeeded', 'failed', 'canceled')),
    -- Code/order expiry: 24 h from creation (plan 3.3).
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cash_payments_user_created
    ON cash_payments(user_id, created_at);
