"""selftest.py — aggressive end-to-end certification for the bot.

Checks environment, database, pipeline freshness, indexes, every core
module import, the main engines, command registration, the start menu,
services, backups, workflows, and a live Roblox cross-reference.

Returns a list of result dicts: {group, name, ok, warning, detail}.
This module can be deleted later without touching the bot's features.
"""
import glob
import importlib
import os
import subprocess
import time
from datetime import datetime


CORE_MODULES = [
    "database", "bot_core", "scanner", "enricher", "suggest",
    "sales_listener", "snapshot", "scheduler", "title_scorer",
    "title_predictor", "chain", "convergence_engine", "gap_engine",
    "oracle", "momentum", "early_winners", "rising_gaps",
    "opportunity_feed", "market_velocity", "competition_check",
    "winner_analysis", "predictor", "pattern_forge", "title_miner",
    "title_pipeline", "smart_pipeline", "intel_common",
    "category_configs", "launch_ledger", "ugc_playbook",
    "post_monitor", "commands_supercomputer", "commands_market",
    "commands_intel", "commands_advanced", "commands_xray",
    "commands_sales", "commands_guide", "commands_ai", "menu",
    "bot_ui", "tag_generator", "desc_forge", "recovery_brain",
    "creative_pivot", "creative_expand", "peer_autopsy", "algo_brain",
    "gemini_brain", "pivot_history", "live_enrich",
    "discover_keywords", "backfill_dates",
]

EXPECTED_COMMANDS = [
    "vacuum", "meta_sniper", "sales_keywords", "launch",
    "launch_sync", "ledger_sync", "hitrate", "playbook", "path",
    "scan_run", "enrich_run", "suggest_run", "suggest_probe",
    "cookie_check", "sales_report", "sales_post_now", "converge",
    "chain", "verdict", "autopsy", "whales", "golden_hour",
    "bot_update", "logs",
]

REQUIRED_TABLES = [
    "items", "discovered_items", "item_history", "search_suggestions",
    "my_sales", "launch_ledger", "failed_items", "learned_keywords",
]

REQUIRED_INDEXES = [
    "idx_items_name_trgm",
    "idx_search_suggestions_unique",
    "idx_my_sales_dedup",
    "idx_launch_ledger_launched",
]

REQUIRED_WORKFLOWS = [
    "scanner.yml", "enricher.yml", "suggest.yml", "discover.yml",
    "backfill_dates.yml", "deploy.yml",
]


def run_selftest(bot=None):
    results = []

    def add(group, name, ok, detail="", warning=False):
        results.append({
            "group": group,
            "name": name,
            "ok": bool(ok),
            "warning": bool(warning),
            "detail": str(detail)[:180],
        })

    # ── Environment ──────────────────────────────────────────────
    add("env", "DATABASE_URL", bool(os.getenv("DATABASE_URL")))
    cookie_count = sum(
        1 for i in range(1, 6) if os.getenv(f"ROBLOSECURITY_COOKIE_{i}")
    )
    add("env", "cookies", cookie_count > 0, f"{cookie_count} loaded")
    add("env", "MY_GROUP_NAMES", bool(os.getenv("MY_GROUP_NAMES")))

    # ── Database + pipeline ─────────────────────────────────────
    cur = conn = None
    sample_id = sample_name = sample_favs = sample_price = None
    ledger_id = None
    try:
        from bot_core import get_db
        conn = get_db()
        cur = conn.cursor()

        for table in REQUIRED_TABLES:
            try:
                cur.execute(f"SELECT count(*) FROM {table}")
                add("db", f"table:{table}", True, f"{cur.fetchone()[0]:,} rows")
            except Exception as e:
                add("db", f"table:{table}", False, str(e)[:100])
                try:
                    conn.rollback()
                except Exception:
                    pass

        cur.execute("""
            SELECT count(*) FROM discovered_items d
            WHERE NOT EXISTS (SELECT 1 FROM items i WHERE i.id = d.id)
        """)
        backlog = cur.fetchone()[0] or 0
        add("pipeline", "backlog", True, f"{backlog:,} pending")

        cur.execute("""
            SELECT count(*) FILTER (WHERE favorite_count IS NULL), count(*)
            FROM items
        """)
        null_favs, total_items = cur.fetchone()
        null_favs = int(null_favs or 0)
        total_items = int(total_items or 0)
        pct_null = (null_favs / total_items * 100) if total_items else 100
        add(
            "pipeline", "favorites coverage",
            pct_null < 20,
            f"{100 - pct_null:.1f}% with favorites",
            warning=True,
        )

        for label, sql in [
            ("dup items",
             "SELECT count(*) FROM (SELECT id FROM items GROUP BY id "
             "HAVING count(*) > 1) t"),
            ("dup history days",
             "SELECT count(*) FROM (SELECT item_id, date(snapshot_at) "
             "FROM item_history GROUP BY 1,2 HAVING count(*) > 1) t"),
            ("dup suggestions",
             "SELECT count(*) FROM (SELECT seed_keyword, lower(suggestion) "
             "FROM search_suggestions GROUP BY 1,2 HAVING count(*) > 1) t"),
        ]:
            cur.execute(sql)
            add("db", label, cur.fetchone()[0] == 0)

        cur.execute("SELECT max(fetched_at) FROM items")
        last_enrich = cur.fetchone()[0]
        add(
            "pipeline", "recent enrichment",
            last_enrich is not None
            and (datetime.utcnow() - last_enrich.replace(tzinfo=None)).total_seconds() < 86400,
            last_enrich,
        )

        cur.execute("SELECT max(snapshot_at) FROM item_history")
        last_snap = cur.fetchone()[0]
        add(
            "pipeline", "recent snapshot",
            last_snap is not None
            and (datetime.utcnow() - last_snap.replace(tzinfo=None)).total_seconds() < 172800,
            last_snap,
        )

        cur.execute("SELECT max(fetched_at) FROM search_suggestions")
        last_sugg = cur.fetchone()[0]
        add(
            "pipeline", "recent suggestions",
            last_sugg is not None
            and (datetime.utcnow() - last_sugg.replace(tzinfo=None)).total_seconds() < 7 * 86400,
            last_sugg,
            warning=True,
        )

        cur.execute("SELECT count(*), max(sale_date) FROM my_sales")
        sales_n, last_sale = cur.fetchone()
        add("db", "sales rows", (sales_n or 0) > 0, f"{sales_n:,}, last {last_sale}")

        cur.execute("SELECT count(*) FROM launch_ledger")
        ledger_n = cur.fetchone()[0] or 0
        add("db", "ledger rows", ledger_n > 0, f"{ledger_n:,} rows")

        cur.execute("SELECT count(*) FROM failed_items")
        add("db", "failed items", True, f"{cur.fetchone()[0]:,} skipped")

        for idx in REQUIRED_INDEXES:
            cur.execute("SELECT 1 FROM pg_indexes WHERE indexname = %s", (idx,))
            add("indexes", idx, cur.fetchone() is not None)

        # Sample rows for engine + live tests
        cur.execute("""
            SELECT id, name, favorite_count, price
            FROM items WHERE favorite_count > 0
            ORDER BY random() LIMIT 1
        """)
        row = cur.fetchone()
        if row:
            sample_id, sample_name, sample_favs, sample_price = row

        cur.execute("SELECT item_id FROM launch_ledger LIMIT 1")
        row = cur.fetchone()
        if row:
            ledger_id = row[0]
    except Exception as e:
        add("db", "connect", False, f"{type(e).__name__}: {e}")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

    # ── Every core module imports ───────────────────────────────
    for mod in CORE_MODULES:
        try:
            importlib.import_module(mod)
            add("modules", mod, True)
        except Exception as e:
            add("modules", mod, False, f"{type(e).__name__}: {e}")

    # ── Engines ─────────────────────────────────────────────────
    try:
        from title_scorer import score_titles_batch
        scored = score_titles_batch(
            ["kawaii aura emote", "cute kitty beanie", "y2k cyber sword"],
            family="emotes",
        )
        add("engines", "title_scorer", bool(scored), f"{len(scored)} scored")
    except Exception as e:
        add("engines", "title_scorer", False, f"{type(e).__name__}: {e}")

    cur = conn = None
    try:
        from bot_core import get_db
        conn = get_db()
        cur = conn.cursor()

        try:
            from convergence_engine import _score_keyword
            r = _score_keyword(cur, "anime", "emotes", min_median=0, min_demand=0)
            add("engines", "convergence", r is not None, "scored" if r else "no result")
        except Exception as e:
            add("engines", "convergence", False, f"{type(e).__name__}: {e}")

        try:
            from gap_engine import run_gap_engine
            g = run_gap_engine(cur, ["kawaii", "aura"], max_scan=300)
            add("engines", "gap_engine", isinstance(g, dict), f"{len(g)} keys")
        except Exception as e:
            add("engines", "gap_engine", False, f"{type(e).__name__}: {e}")

        try:
            from oracle import forecast_trend
            f = forecast_trend(cur, "anime", days=14)
            add("engines", "oracle", isinstance(f, dict), f"{len(f)} keys")
        except Exception as e:
            add("engines", "oracle", False, f"{type(e).__name__}: {e}")

        try:
            from momentum import find_momentum_keywords
            m = find_momentum_keywords(cur, days=7, min_items=3, top_n=5)
            add("engines", "momentum", isinstance(m, list), f"{len(m)} keywords")
        except Exception as e:
            add("engines", "momentum", False, f"{type(e).__name__}: {e}")

        try:
            from early_winners import find_early_winners
            e = find_early_winners(cur, days=7)
            add("engines", "early_winners", isinstance(e, list), f"{len(e)} winners")
        except Exception as e:
            add("engines", "early_winners", False, f"{type(e).__name__}: {e}")

        try:
            from intel_common import item_percentile, portfolio_context
            if sample_id:
                p = item_percentile(cur, sample_id)
                add("engines", "percentile", isinstance(p, dict), f"{len(p)} keys")
            else:
                add("engines", "percentile", False, "no sample item", warning=True)
            portfolio_context(cur, top_n=2)
            add("engines", "portfolio_context", True)
        except Exception as e:
            add("engines", "intel_common", False, f"{type(e).__name__}: {e}")

        try:
            from title_predictor import predict_title
            p = predict_title(cur, "kawaii aura emote", auto_train=False)
            add(
                "engines", "title_predictor",
                isinstance(p, dict) and "score" in p,
                p.get("error", "model ok"),
                warning=(p.get("error") == "no_model"),
            )
        except Exception as e:
            add("engines", "title_predictor", False, f"{type(e).__name__}: {e}")

        try:
            from launch_ledger import fill_ledger
            if ledger_id:
                add("engines", "ledger fill", fill_ledger(cur, ledger_id))
            else:
                add("engines", "ledger fill", False, "no ledger rows", warning=True)
        except Exception as e:
            add("engines", "ledger fill", False, f"{type(e).__name__}: {e}")

        try:
            from ugc_playbook import audit_title, audit_price
            audit_title("kawaii aura emote")
            audit_price(20)
            add("engines", "playbook rules", True)
        except Exception as e:
            add("engines", "playbook rules", False, f"{type(e).__name__}: {e}")
    except Exception as e:
        add("engines", "db", False, f"{type(e).__name__}: {e}")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

    try:
        from post_monitor import analyze_sales, format_report
        data = analyze_sales(7)
        report = format_report(data)
        add("engines", "sales report", isinstance(report, str) and len(report) > 20)
    except Exception as e:
        add("engines", "sales report", False, f"{type(e).__name__}: {e}")

    # ── Live Roblox cross-reference ─────────────────────────────
    try:
        from recovery_brain import fetch_item_from_roblox
        if sample_id:
            live = fetch_item_from_roblox(
                sample_id, os.getenv("ROBLOSECURITY_COOKIE_1")
            )
            if live:
                name_ok = (
                    (live.get("name") or "").strip().lower()
                    == (sample_name or "").strip().lower()
                )
                add(
                    "live", "name match", name_ok,
                    f"db={(sample_name or '')[:40]} live={(live.get('name') or '')[:40]}",
                )
                add(
                    "live", "favorites",
                    True,
                    f"db={sample_favs} live={live.get('favorite_count')}",
                    warning=True,
                )
            else:
                add("live", "item fetch", False, "returned None", warning=True)
        else:
            add("live", "item fetch", False, "no sample item", warning=True)
    except Exception as e:
        add("live", "item fetch", False, f"{type(e).__name__}: {e}", warning=True)

    # ── Commands ────────────────────────────────────────────────
    if bot is not None:
        names = {c.name for c in bot.commands}
        missing = [c for c in EXPECTED_COMMANDS if c not in names]
        add(
            "commands", "registered",
            not missing,
            f"{len(names)} total" + (f", missing {missing}" if missing else ""),
        )
        no_help = []
        for c in bot.commands:
            if not callable(getattr(c, "callback", None)):
                no_help.append(f"{c.name}:no-callback")
            elif not (c.help or (c.callback.__doc__ or "").strip()):
                no_help.append(c.name)
        add(
            "commands", "help text",
            not no_help,
            ", ".join(no_help[:10]) if no_help else "all documented",
            warning=True,
        )

    # ── Start menu ──────────────────────────────────────────────
    try:
        from menu import MenuView
        if bot is not None:
            from bot_core import get_db as _get_db
            view = MenuView(bot, _get_db)
            n = len(view.children)
            add("menu", "buttons", n >= 5, f"{n} buttons")
            labels = [getattr(c, "label", "") for c in view.children]
            add("menu", "labels", all(labels), ", ".join(labels)[:150])
        else:
            add("menu", "load", True, "class imported", warning=True)
    except Exception as e:
        add("menu", "load", False, f"{type(e).__name__}: {e}")

    # ── Services ────────────────────────────────────────────────
    for svc in ["ugc-bot", "ugc-enrich"]:
        try:
            out = subprocess.check_output(
                ["systemctl", "is-active", svc], text=True, timeout=5
            ).strip()
            add("services", svc, out == "active", out, warning=(svc == "ugc-enrich"))
        except Exception:
            add("services", svc, False, "cannot query", warning=True)

    # ── Backups ─────────────────────────────────────────────────
    try:
        files = glob.glob("/home/ubuntu/backups/ugc_db_*.sql.gz")
        if files:
            latest = max(files, key=os.path.getmtime)
            age_h = (time.time() - os.path.getmtime(latest)) / 3600
            add(
                "backups", "latest",
                age_h < 48,
                f"{os.path.basename(latest)} ({age_h:.1f}h old)",
            )
        else:
            add("backups", "latest", False, "no backup found")
    except Exception as e:
        add("backups", "latest", False, f"{type(e).__name__}: {e}")

    # ── Workflows present ───────────────────────────────────────
    base = "/home/ubuntu/robux-ugc-advanced/.github/workflows"
    for wf in REQUIRED_WORKFLOWS:
        add("workflows", wf, os.path.exists(os.path.join(base, wf)))

    return results
