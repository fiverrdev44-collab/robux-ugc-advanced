-- D-09: functional index for the exact-title lookup in item_resolver.resolve_name
-- Query: SELECT id FROM items WHERE lower(trim(name)) = lower(trim(%s))
-- Run OUTSIDE a transaction (CONCURRENTLY cannot run inside one):
--   psql "$DATABASE_URL" -f migrations/2026-11-01_items_name_lower_trim_index.sql
-- NOT APPLIED to production by this audit.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_items_name_lower_trim
    ON items (lower(trim(name)));
