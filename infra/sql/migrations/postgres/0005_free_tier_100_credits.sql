-- Raise existing free accounts to the 100-tracker free allowance.
--
-- The free tier's starting balance went from 3 to 100 credits
-- (services/api/credits.py). Users with no user_credits row already get 100
-- lazily, but rows created under the old allowance still hold 0-3. Grant each
-- such free user the credits they missed, so their balance becomes 100 minus
-- the trackers they have already created.
--
-- A row's free allowance is its balance minus the sum of its credit
-- transactions other than this migration's 'free_tier_100' grants (i.e.
-- undoing deductions and paid top-ups): the starting balance plus any
-- free-tier grant already given. Only rows whose allowance is below 100 are
-- topped up, by the difference. Once granted, the allowance computes to
-- exactly 100, so re-running this migration (the bootstrap re-applies every
-- file) is a no-op and rows provisioned at 100 are never touched.

WITH allowance AS (
    SELECT c.user_id,
           c.balance - COALESCE(
               SUM(t.amount) FILTER (WHERE t.reason <> 'free_tier_100'), 0
           ) AS starting_credits
    FROM public.user_credits AS c
    JOIN public.users AS u ON u.id = c.user_id
    LEFT JOIN public.credit_transactions AS t ON t.user_id = c.user_id
    WHERE u.tier = 'free'
    GROUP BY c.user_id, c.balance
),
upgraded AS (
    UPDATE public.user_credits AS c
        SET balance = c.balance + (100 - a.starting_credits),
            updated_at = now()
        FROM allowance AS a
        WHERE a.user_id = c.user_id
          AND a.starting_credits < 100
        RETURNING c.user_id, 100 - a.starting_credits AS granted
)
INSERT INTO public.credit_transactions (id, user_id, amount, reason, created_at)
SELECT gen_random_uuid(), user_id, granted, 'free_tier_100', now()
FROM upgraded;
