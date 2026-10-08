-- Feature 1: card payments tracking table (Paymob card flow).
-- Idempotent: safe to run multiple times.

CREATE TABLE IF NOT EXISTS card_payments (
    id SERIAL PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    -- Set at /payment/confirm; unique — one Paymob payment per record.
    paymob_payment_id VARCHAR(255) UNIQUE,
    package VARCHAR(20) NOT NULL
        CHECK (package IN ('standard', 'premium')),
    amount_egp NUMERIC(10, 2) NOT NULL CHECK (amount_egp > 0),
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'succeeded', 'failed', 'canceled')),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_card_payments_user_created
    ON card_payments(user_id, created_at);
