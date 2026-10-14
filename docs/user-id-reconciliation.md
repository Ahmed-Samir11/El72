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

## Procedure (sketch — adapt to your schema before running)

> The SQL below is a **pseudocode sketch, not an executable script**: the
> `users` column list and reference tables must be adapted to your actual
> definition, and it runs only on a frozen database under your supervision.
> The two ordering requirements that will otherwise make it fail are:
> 1. **Drop every foreign key that references `users.id` before altering
>    the column** (Postgres rejects dropping/re-typing a referenced PK
>    while FKs exist); recreate them after the remap.
> 2. **Handle the SERIAL sequence**: after rebuilding `users.id` as
>    SERIAL, reset it past the max id
>    (`SELECT setval('users_id_seq', (SELECT max(id) FROM users));`).

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
4. **Remap the ids** (one transaction, on the fresh database):
   ```sql
   -- 0) detach all FKs that reference users.id
   --    (alerts, tracked_items, payment_logs, user_credits,
   --     credit_transactions, manual_payments, card_payments,
   --     wallet_payments, cash_payments, payment_audit_log.target_user_id,
   --     refunds.user_id, subscriptions.user_id, ...)
   ALTER TABLE <each_referring_table>
       DROP CONSTRAINT <fk_name>;

   -- 1) temporary mapping table
   CREATE TEMP TABLE user_id_map (old_uuid UUID PRIMARY KEY, new_id INTEGER);

   -- 2) assign fresh sequential ids (deterministic order keeps it stable)
   INSERT INTO user_id_map
   SELECT id, row_number() OVER (ORDER BY id)
   FROM users;

   -- 3) rebuild users with the INTEGER pk
   ALTER TABLE users RENAME TO users_old;   -- keeps UUID ids + old data
   CREATE TABLE users (<same column list, but: id SERIAL PRIMARY KEY>);
   INSERT INTO users (<columns>)
   SELECT <columns with m.new_id as id>
   FROM users_old u
   JOIN user_id_map m ON m.old_uuid = u.id;

   -- 4) rewrite every user_id reference via the same map
   UPDATE payment_logs p
      SET user_id = m.new_id FROM user_id_map m WHERE m.old_uuid = p.user_id;
   -- ...repeat for each table (VARCHAR(36) refs map via m.old_uuid::text)

   -- 5) recreate FKs from the canonical schema and reset the sequence
   ALTER TABLE <each_referring_table>
       ADD CONSTRAINT <fk_name> FOREIGN KEY (user_id)
       REFERENCES users(id) ON DELETE SET NULL;
   SELECT setval('users_id_seq', (SELECT max(id) FROM users));
   ```
   (Adapt the column lists and constraint names to your `users`
   definition and the canonical schema.)
5. **Recreate constraints/indexes** from the canonical schema and
   migrations (`scripts/db-bootstrap.sh` is idempotent).
6. **Verify.** Run `scripts/audit-db-and-bootstrap.sh` (read-only) and
   confirm zero drift, then restore service writes.

Keep the original dump until the rebuilt database has served a full
billing cycle.
