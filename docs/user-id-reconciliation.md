# Merging a UUID-keyed database onto the reconciled INTEGER schema

The operational schema (see `infra/sql/schema/postgres.sql`) uses INTEGER
primary keys for `users` and the operational tables, matching the ORM
(`OperationalIdType`). A database created before this reconciliation has
`users.id UUID`. **No migration converts that column in place** — the path
is a rebuild from a dump with a scripted id remap.

## Why no in-place migration

- `ALTER TABLE users ALTER COLUMN id TYPE INTEGER` has no valid
  UUID → INTEGER cast and would destroy the key values.
- Payment/audit tables reference `users.id`; every reference must be
  remapped consistently in one operation, which only a controlled rebuild
  can guarantee.

## Procedure (tested steps)

1. **Freeze writes.** Stop all application services and the scraper so no
   new rows are written during the dump.
2. **Dump the UUID-keyed database.**
   ```bash
   pg_dump "$DATABASE_URL" --format=custom --file=pre-uuid-repair.dump
   ```
3. **Restore into a fresh database** created from the reconciled schema:
   run `scripts/db-bootstrap.sh` against the fresh database first, then
   restore the data-only dump on top (or restore first and let the
   bootstrap's idempotent migrations converge the schema — pick one order
   and verify with the audit script afterwards).
4. **Remap the ids.** On the fresh database the `users` table is INTEGER
   (`SERIAL`). After loading the old rows (whose `id` values are UUID
   strings), build a deterministic mapping and rewrite references:
   ```sql
   -- 1) temporary mapping table
   CREATE TEMP TABLE user_id_map (old_uuid UUID PRIMARY KEY, new_id INTEGER);

   -- 2) assign fresh sequential ids (deterministic order keeps it stable)
   WITH ranked AS (
       SELECT id AS old_uuid, row_number() OVER (ORDER BY id) AS new_id
       FROM users
   )
   INSERT INTO user_id_map SELECT old_uuid, new_id FROM ranked;

   -- 3) rewrite the PK
   ALTER TABLE users ADD COLUMN old_id UUID;
   UPDATE users u SET old_id = u.id FROM user_id_map m WHERE m.old_uuid = u.id;
   -- (load the UUID ids into old_id before the column type change)
   ALTER TABLE users DROP COLUMN id;
   ALTER TABLE users RENAME COLUMN old_id TO id;  -- now holds UUIDs
   ALTER TABLE users ALTER COLUMN id TYPE TEXT;   -- staging
   -- final: rebuild users(id INTEGER) from the map
   CREATE TABLE users_new (LIKE users INCLUDING ALL);
   INSERT INTO users_new
   SELECT ... FROM users u JOIN user_id_map m ON m.old_uuid = u.id;
   DROP TABLE users; ALTER TABLE users_new RENAME TO users;
   ```
   (The exact column list depends on your `users` definition; adapt the
   `SELECT` list accordingly.)
5. **Rewrite every `user_id` reference** the same way, in one transaction:
   `payment_logs`, `user_credits`, `credit_transactions`, `manual_payments`,
   `card_payments`, `wallet_payments`, `cash_payments`,
   `payment_audit_log.target_user_id`, `alerts`, `tracked_items`, and the
   preserved feature tables (`refunds.user_id`, `subscriptions.user_id`,
   which are VARCHAR(36) dashed-UUID strings — map via
   `m.old_uuid::text`).
6. **Recreate constraints/indexes** from the canonical schema and
   migrations (`scripts/db-bootstrap.sh` is idempotent).
7. **Verify.** Run `scripts/audit-db-and-bootstrap.sh` (read-only) and
   confirm zero drift, then restore service writes.

Keep the original dump until the rebuilt database has served a full
billing cycle.
