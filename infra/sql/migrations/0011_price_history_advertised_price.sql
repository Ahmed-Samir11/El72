-- 0011: Store the advertised "was" (strikethrough) price on price_history.
--
-- The scraper extracts `original_price` from product pages (the price shown
-- before a discount). Persisting it per observation lets the fake-discount
-- detector compare the site's claimed discount against the product's real
-- historical price. Nullable: most observations have no advertised price.
ALTER TABLE price_history ADD COLUMN IF NOT EXISTS advertised_price NUMERIC(10, 2);
