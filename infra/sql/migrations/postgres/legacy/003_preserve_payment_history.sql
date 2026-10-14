
BEGIN;

-- Preserve payment records if a user row is hard-deleted.
-- Assumes the existing PostgreSQL-generated FK constraint names.

ALTER TABLE payment_logs
    DROP CONSTRAINT IF EXISTS payment_logs_user_id_fkey;

ALTER TABLE payment_logs
    ALTER COLUMN user_id DROP NOT NULL;

ALTER TABLE payment_logs
    ADD CONSTRAINT payment_logs_user_id_fkey
    FOREIGN KEY (user_id)
    REFERENCES users(id)
    ON DELETE SET NULL;

ALTER TABLE payment_audit_log
    ADD CONSTRAINT payment_audit_log_target_user_id_fkey
    FOREIGN KEY (target_user_id)
    REFERENCES users(id)
    ON DELETE SET NULL;

ALTER TABLE card_payments
    DROP CONSTRAINT IF EXISTS card_payments_user_id_fkey;

ALTER TABLE card_payments
    ADD CONSTRAINT card_payments_user_id_fkey
    FOREIGN KEY (user_id)
    REFERENCES users(id)
    ON DELETE SET NULL;

ALTER TABLE wallet_payments
    DROP CONSTRAINT IF EXISTS wallet_payments_user_id_fkey;

ALTER TABLE wallet_payments
    ADD CONSTRAINT wallet_payments_user_id_fkey
    FOREIGN KEY (user_id)
    REFERENCES users(id)
    ON DELETE SET NULL;

COMMIT;