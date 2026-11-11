#!/usr/bin/env bash
# Manually executed, fail-closed Oracle production migration.
# NO service restarts, git resets, webhook sends, bot launches, or flag changes.
# Migration files pinned to the exact SHA rehearsed with the production backup.
set -Eeuo pipefail
umask 077

export PGOPTIONS='-c TimeZone=UTC -c lock_timeout=30000'
PROJECT="$HOME/robux-ugc-advanced"
BACKUP="$HOME/vanta73_backups/ugc_db_final_20261111_214600.dump"
BACKUP_SHA='5ab11cc80cb7c2d0f9aad8277d1f6d8edb2cba48ee40ef8fc0de9f30aca5998f'
REHEARSED_SHA='792c0c9cc80abb7c7ce4d58619f1417682ead785'
REPO='fiverrdev44-collab/robux-ugc-advanced'
RUN_DIR="$HOME/vanta73_production_migration_$(date -u +%Y%m%d_%H%M%S)"
FAILED=0
trap 'code=$?; echo "STOP: migration script failed (exit $code). Leave BOTH services stopped. Do NOT rerun or deploy. Logs: $RUN_DIR"; exit "$code"' ERR

require_stopped() {
  local svc
  for svc in ugc-bot ugc-enrich; do
    if [[ "$(systemctl is-active "$svc" 2>/dev/null || true)" != "inactive" ]]; then
      echo "BLOCKED: $svc is not inactive"; exit 3
    fi
  done
  if pgrep -f '[p]ython.*(discord_ugc_bot|enricher\.py)' >/dev/null; then
    echo 'BLOCKED: bot/enricher Python process remains'; exit 4
  fi
}

require_stopped
cd "$PROJECT"
if [[ ! -f "$BACKUP" ]]; then echo "BLOCKED: backup missing"; exit 5; fi
printf '%s  %s\n' "$BACKUP_SHA" "$BACKUP" | sha256sum -c --status || { echo 'BLOCKED: verified backup checksum changed'; exit 6; }
pg_restore -l "$BACKUP" >/dev/null || { echo 'BLOCKED: verified backup archive unreadable'; exit 7; }

DBURL=$(sed -n 's/^DATABASE_URL=//p' .env | head -n 1 | tr -d '\r')
DBURL="${DBURL#\"}"; DBURL="${DBURL%\"}"
DBURL="${DBURL#\'}"; DBURL="${DBURL%\'}"
[[ -n "$DBURL" ]] || { echo 'BLOCKED: missing DATABASE_URL'; exit 8; }

q() { psql -X -w -v ON_ERROR_STOP=1 -At "$DBURL" -c "$1"; }
snapshot_type=$(q "SELECT data_type FROM information_schema.columns WHERE table_schema='public' AND table_name='item_history' AND column_name='snapshot_at'")
[[ "$(q 'SELECT current_database()')" == 'ugc_db' ]] || { echo 'BLOCKED: wrong DB'; exit 9; }
[[ "$snapshot_type" == 'timestamp without time zone' ]] || { echo "BLOCKED: unexpected history type: $snapshot_type"; exit 10; }
[[ "$(q "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'")" == '31' ]] || { echo 'BLOCKED: unexpected pre-migration public table count'; exit 11; }
[[ "$(q "SELECT count(*) FROM (SELECT item_id, snapshot_at::date FROM public.item_history GROUP BY 1,2 HAVING count(*)>1) d")" == '0' ]] || { echo 'BLOCKED: duplicate snapshot days'; exit 12; }
[[ "$(q "SELECT count(*) FROM public.tracked_creators WHERE creator_type IS NULL OR creator_type NOT IN ('User','Group') OR creator_id IS NULL")" == '0' ]] || { echo 'BLOCKED: invalid creator type or id'; exit 13; }
[[ "$(q "SELECT count(*) FROM (SELECT creator_id FROM public.tracked_creators GROUP BY creator_id HAVING count(*)>1) d")" == '0' ]] || { echo 'BLOCKED: duplicate legacy creator id'; exit 14; }
[[ "$(q "SELECT count(*) FROM (SELECT source_event_id FROM public.my_sales WHERE source_event_id IS NOT NULL GROUP BY 1 HAVING count(*)>1) d")" == '0' ]] || { echo 'BLOCKED: duplicate sales source identity'; exit 15; }

counts_before=$(q 'SELECT (SELECT count(*) FROM public.items)::text || '\''|'\'' || (SELECT count(*) FROM public.item_history) || '\''|'\'' || (SELECT count(*) FROM public.my_sales) || '\''|'\'' || (SELECT count(*) FROM public.tracked_creators)')
if [[ "$counts_before" != '227394|74192|1357|46' ]]; then
  echo "BLOCKED: live row counts changed since reviewed preflight: $counts_before"
  exit 16
fi
echo "PASS: Oracle DB identity, two stopped services, immutable backup SHA, 31 legacy tables, duplicate/creator/sales guards."
echo "Baseline counts: $counts_before (items|history|sales|tracked_creators)"

mkdir -m 700 "$RUN_DIR"
curl --fail --location --silent --show-error --retry 2 \
  "https://github.com/$REPO/archive/$REHEARSED_SHA.tar.gz" \
  -o "$RUN_DIR/rehearsed-release.tar.gz"
tar -xzf "$RUN_DIR/rehearsed-release.tar.gz" -C "$RUN_DIR"
SOURCE="$RUN_DIR/robux-ugc-advanced-$REHEARSED_SHA"
[[ -f "$SOURCE/migrations/2026-11-08_f10_timestamp_integrity.sql" ]] || { echo 'BLOCKED: missing pinned migrations'; exit 17; }

migrations=(
  2026-11-01_items_name_lower_trim_index.sql
  2026-11-02_astra_tables.sql
  2026-11-02_astra_outcomes.sql
  2026-11-02_project_oracle_phase1.sql
  2026-11-02_project_oracle_phase2.sql
  2026-11-03_sales_integrity_columns.sql
  2026-11-05_creator_registry.sql
  2026-11-05_golden_hour_indexes.sql
  2026-11-08_f07_creator_identity_expand.sql
  2026-11-08_f07_oracle_identity_additive.sql
  2026-11-08_f07_creator_identity_contract.sql
  2026-11-08_f10_timestamp_integrity.sql
)
# No external transaction wrapper: migration 1 uses CONCURRENTLY,
# and the remaining files manage their own BEGIN/COMMIT.
i=0
for name in "${migrations[@]}"; do
  require_stopped
  i=$((i+1))
  echo "RUNNING $i/12: $name"
  psql -X -w -v ON_ERROR_STOP=1 -P pager=off "$DBURL" \
    -f "$SOURCE/migrations/$name" >"$RUN_DIR/migration_$i.log" 2>&1 || {
      echo "STOPPED on $i/12: $name"
      tail -n 35 "$RUN_DIR/migration_$i.log"
      exit 18
    }
  echo "PASS $i/12"
done

counts_after=$(q 'SELECT (SELECT count(*) FROM public.items)::text || '\''|'\'' || (SELECT count(*) FROM public.item_history) || '\''|'\'' || (SELECT count(*) FROM public.my_sales) || '\''|'\'' || (SELECT count(*) FROM public.tracked_creators)')
[[ "$counts_after" == "$counts_before" ]] || { echo "BLOCKED: core row counts changed: $counts_before => $counts_after"; exit 19; }
[[ "$(q "SELECT data_type FROM information_schema.columns WHERE table_schema='public' AND table_name='item_history' AND column_name='snapshot_at'")" == 'timestamp with time zone' ]] || { echo 'BLOCKED: F-10 timestamp type failed'; exit 20; }
[[ "$(q "SELECT count(*) FROM (SELECT item_id, (snapshot_at AT TIME ZONE 'UTC')::date FROM public.item_history GROUP BY 1,2 HAVING count(*)>1) d")" == '0' ]] || { echo 'BLOCKED: postmigration UTC duplicates'; exit 21; }
[[ "$(q "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'")" == '32' ]] || { echo 'BLOCKED: unexpected new table count'; exit 22; }
[[ "$(q "SELECT count(*) FROM pg_constraint WHERE conrelid='public.tracked_creators'::regclass AND contype='p' AND pg_get_constraintdef(oid)='PRIMARY KEY (creator_type, creator_id)'")" == '1' ]] || { echo 'BLOCKED: composite creator PK missing'; exit 23; }
[[ "$(q "SELECT to_regclass('public.creator_registry') IS NOT NULL AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='items' AND column_name='creator_type') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='my_sales' AND column_name='transaction_id')")" == 't' ]] || { echo 'BLOCKED: required schema markers missing'; exit 24; }

PGOPTIONS='-c default_transaction_read_only=on -c TimeZone=UTC -c statement_timeout=60000' \
  psql -X -w -v ON_ERROR_STOP=1 -P pager=off "$DBURL" -f "$SOURCE/release/preflight.sql" \
  > "$RUN_DIR/postflight.log" 2>&1

echo 'SUCCESS: Oracle production migrated 12/12, core counts unchanged, UTC/history, creator PK, 32 tables, full read-only postflight PASS.'
echo "Logs: $RUN_DIR"
echo 'BOTH SERVICES ARE STILL STOPPED. Next: manual controlled code deployment after checking the full output.'
unset DBURL
