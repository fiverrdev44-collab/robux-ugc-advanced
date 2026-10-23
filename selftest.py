"""selftest.py — aggressive end-to-end certification for the bot.

Checks environment, database, pipeline freshness, indexes, every core
module import, the main engines, command registration, the start menu,
services, backups, workflows, and a live Roblox cross-reference.

Returns a list of result dicts: {group, name, ok, warning, detail}.
This module can be deleted later without touching the bot's features.
"""
import asyncio
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
    "discover_keywords", "backfill_dates", "confidence",
    "verification", "opportunity_score", "revsim", "live_market",
    "experiments", "commands_experiments", "data_audit",
    "search_visibility", "commands_visibility", "matched_experiments",
    "favorites_backfill",
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
    "idx_my_sales_event_id",
    "idx_my_sales_fingerprint_fallback",
    "idx_launch_ledger_launched",
    "idx_item_history_daily",
]

REQUIRED_WORKFLOWS = [
    "scanner.yml", "enricher.yml", "suggest.yml", "discover.yml",
    "backfill_dates.yml", "deploy.yml",
]


def run_selftest(bot=None, progress=None):
    results = []

    def stage(name):
        if progress:
            try:
                progress(name, results)
            except Exception:
                pass

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
    stage("ENVIRONMENT")

    # ── Database + pipeline ─────────────────────────────────────
    cur = conn = None
    samples = []
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
            SELECT count(*) FILTER (WHERE favorite_count > 0), count(*)
            FROM items
        """)
        positive_favs, total_items = cur.fetchone()
        positive_favs = int(positive_favs or 0)
        total_items = int(total_items or 0)
        pct_positive = (positive_favs / total_items * 100) if total_items else 0
        add(
            "pipeline", "favorites coverage",
            pct_positive >= 30,
            f"{pct_positive:.1f}% positive favorites",
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
            SELECT id, name, favorite_count, price, creator_name
            FROM items WHERE favorite_count > 0
            ORDER BY random() LIMIT 3
        """)
        samples = cur.fetchall()
        sample_id = samples[0][0] if samples else None

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
    stage("DATABASE")

    # ── Every core module imports ───────────────────────────────
    for mod in CORE_MODULES:
        try:
            importlib.import_module(mod)
            add("modules", mod, True)
        except Exception as e:
            add("modules", mod, False, f"{type(e).__name__}: {e}")
    stage("MODULES")

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
            r = _score_keyword(cur, "dance", "emotes", min_median=0, min_demand=0)
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

        # Determinism: same input must produce the same output twice.
        try:
            from convergence_engine import _score_keyword as _sc
            a = _sc(cur, "dance", "emotes", 0, 0)
            b = _sc(cur, "dance", "emotes", 0, 0)
            add("determinism", "convergence", a == b)
        except Exception as e:
            add("determinism", "convergence", False, f"{type(e).__name__}: {e}")

        try:
            from oracle import forecast_trend as _ft
            a = _ft(cur, "anime", days=14)
            b = _ft(cur, "anime", days=14)
            add("determinism", "oracle", a == b)
        except Exception as e:
            add("determinism", "oracle", False, f"{type(e).__name__}: {e}")

        # Cross-check the sales report against a direct SQL sum.
        try:
            from post_monitor import analyze_sales
            data = analyze_sales(7)
            cur.execute("""
                SELECT count(*), COALESCE(SUM(amount_robux), 0)
                FROM my_sales
                WHERE sale_date = (now() AT TIME ZONE 'UTC')::date
            """)
            u, r = cur.fetchone()
            ok = (
                int(data.get("today_units", 0)) == int(u or 0)
                and int(data.get("today_robux", 0)) == int(r or 0)
            )
            add(
                "crosscheck", "sales today", ok,
                f"report={data.get('today_units')}/{data.get('today_robux')} "
                f"sql={u}/{r}",
            )
        except Exception as e:
            add("crosscheck", "sales today", False, f"{type(e).__name__}: {e}")
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
    stage("ENGINES")

    # ── Live Roblox cross-reference (3 items) ───────────────────
    try:
        from recovery_brain import fetch_item_from_roblox
        cookie = os.getenv("ROBLOSECURITY_COOKIE_1")
        if samples:
            for idx, (sid, sname, sfavs, sprice, screator) in enumerate(samples, 1):
                live = fetch_item_from_roblox(sid, cookie)
                if not live:
                    add("live", f"item{idx}", False, "fetch returned None", warning=True)
                    continue
                name_ok = (
                    (live.get("name") or "").strip().lower()
                    == (sname or "").strip().lower()
                )
                add(
                    "live", f"item{idx} name", name_ok,
                    f"db={(sname or '')[:36]} live={(live.get('name') or '')[:36]}",
                )
                if (screator or "").strip():
                    creator_ok = (
                        (live.get("creator_name") or "").strip().lower()
                        == (screator or "").strip().lower()
                    )
                    add(
                        "live", f"item{idx} creator", creator_ok,
                        f"db={screator} live={live.get('creator_name')}",
                    )
                else:
                    add(
                        "live", f"item{idx} creator", True,
                        "db creator empty", warning=True,
                    )
                add(
                    "live", f"item{idx} favorites", True,
                    f"db={sfavs} live={live.get('favorite_count')}",
                    warning=True,
                )
                add(
                    "live", f"item{idx} price", True,
                    f"db={sprice} live={live.get('price')}",
                    warning=True,
                )
        else:
            add("live", "items", False, "no sample items", warning=True)
    except Exception as e:
        add("live", "items", False, f"{type(e).__name__}: {e}", warning=True)
    stage("LIVE MARKETPLACE")

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
    stage("COMMANDS")

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
    stage("START MENU")

    # ── Services ────────────────────────────────────────────────
    for svc in ["ugc-bot", "ugc-enrich"]:
        try:
            out = subprocess.check_output(
                ["systemctl", "is-active", svc], text=True, timeout=5
            ).strip()
            add("services", svc, out == "active", out, warning=(svc == "ugc-enrich"))
        except Exception:
            add("services", svc, False, "cannot query", warning=True)
    stage("SERVICES")

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
    stage("BACKUPS")

    # ── Workflows present ───────────────────────────────────────
    base = "/home/ubuntu/robux-ugc-advanced/.github/workflows"
    for wf in REQUIRED_WORKFLOWS:
        add("workflows", wf, os.path.exists(os.path.join(base, wf)))
    stage("WORKFLOWS")

    return results


# ─────────────────────────────────────────────────────────────────
# Live command harness — executes menu buttons and safe commands
# with mock Discord objects and captures their responses.
# ─────────────────────────────────────────────────────────────────

class _MockPermissions:
    administrator = True
    manage_guild = True
    manage_messages = True
    manage_channels = True


class _MockAuthor:
    id = 1210571583559835709
    display_name = "selftest"
    mention = "<@selftest>"
    bot = False
    guild_permissions = _MockPermissions()


class _MockMessage:
    def __init__(self, sink):
        self._sink = sink

    async def edit(self, content=None, *, embed=None, **kwargs):
        self._sink.append({"content": content, "embed": embed})
        return self

    async def delete(self):
        return None

    async def add_reaction(self, *a, **k):
        return None


class _MockGuild:
    id = 0
    name = "selftest"
    member_count = 1
    owner_id = 1210571583559835709
    me = _MockAuthor()

    def get_member(self, *a, **k):
        return None

    def get_channel(self, *a, **k):
        return None


class _MockChannel:
    id = 0
    name = "selftest"
    mention = "#selftest"

    async def send(self, *a, **k):
        return None


class _MockMessageObj:
    id = 0
    content = ""
    created_at = datetime.utcnow()
    attachments = []
    embeds = []


class _AsyncNull:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _MockCtx:
    def __init__(self):
        self.author = _MockAuthor()
        self.guild = _MockGuild()
        self.channel = _MockChannel()
        self.message = _MockMessageObj()
        self.sent = []

    async def send(self, content=None, *, embed=None, **kwargs):
        self.sent.append({"content": content, "embed": embed})
        return _MockMessage(self.sent)

    async def reply(self, content=None, *, embed=None, **kwargs):
        return await self.send(content, embed=embed, **kwargs)

    def typing(self):
        return _AsyncNull()


class _MockResponse:
    def __init__(self, parent):
        self.parent = parent

    async def send_message(self, content=None, *, embed=None, **kwargs):
        self.parent.sent.append({"content": content, "embed": embed})
        return _MockMessage(self.parent.sent)

    async def defer(self, **kwargs):
        return None

    async def edit_message(self, **kwargs):
        return None


class _MockFollowup:
    def __init__(self, sink):
        self._sink = sink

    async def send(self, content=None, *, embed=None, **kwargs):
        self._sink.append({"content": content, "embed": embed})
        return _MockMessage(self._sink)


class _MockInteraction:
    def __init__(self):
        self.sent = []
        self.response = _MockResponse(self)
        self.followup = _MockFollowup(self.sent)
        self.user = _MockAuthor()
        self.guild = _MockGuild()
        self.channel = _MockChannel()
        self.message = _MockMessageObj()


SAFE_COMMANDS = [
    ("dbtest", [], {}),
    ("scan_status", [], {}),
    ("playbook", [], {"topic": "naming"}),
    ("path", [], {}),
    ("vacuum", [5], {}),
    ("meta_sniper", [], {"niche": "aura emote"}),
    ("sales_keywords", ["emotes"], {}),
    ("early", [7], {}),
    ("experiments", [], {}),
    ("data_audit", [], {}),
    ("visibility", [], {}),
    ("momentum", [7], {}),
    ("oracle", [], {"keyword": "anime"}),
    ("predict", [], {"idea": "kawaii aura emote"}),
    ("gap", [], {"keyword": "anime"}),
    ("xray", [], {}),
    ("patterns", ["emotes"], {}),
    ("failures", ["emotes"], {}),
    ("trends", [], {}),
    ("golden_hour", [5], {}),
    ("whales", [], {}),
    ("sales_report", [7], {}),
    ("sales_debug", [], {}),
    ("sales_scan", [5], {}),
    ("sales_for", [], {"item_name": "Smooth 360 flip Rizz"}),
    ("hitrate", [365], {}),
    ("ledger_sync", [], {}),
    ("launch_sync", [], {"groups": "Ami Berloga,Motion Works Inc.,eroseris"}),
    ("suggest_probe", [], {"query": "aura"}),
    ("cookie_check", [], {}),
    ("history", [], {}),
    ("watchlist", [], {}),
    ("tags", [], {"args": "kawaii aura emote"}),
    ("logs", [20], {}),
]


async def run_command_harness(bot, progress=None):
    """Execute menu buttons + safe commands with mocks. Async on main loop."""
    results = []

    def add(group, name, ok, detail="", warning=False):
        results.append({
            "group": group,
            "name": name,
            "ok": bool(ok),
            "warning": bool(warning),
            "detail": str(detail)[:180],
        })

    # Menu buttons
    try:
        from menu import MenuView
        from bot_core import get_db

        view = MenuView(bot, get_db)
        for child in view.children:
            label = getattr(child, "label", "button")
            inter = _MockInteraction()
            print(f"[selftest] menu {label} start", flush=True)
            try:
                try:
                    await asyncio.wait_for(child.callback(inter), timeout=20)
                except TypeError:
                    await asyncio.wait_for(
                        child.callback(inter, child), timeout=20
                    )
                add(
                    "menu_live", label,
                    bool(inter.sent),
                    f"{len(inter.sent)} responses",
                )
                print(f"[selftest] menu {label} ok", flush=True)
            except asyncio.TimeoutError:
                add("menu_live", label, False, "timeout after 20s")
                print(f"[selftest] menu {label} TIMEOUT", flush=True)
            except Exception as e:
                add("menu_live", label, False, f"{type(e).__name__}: {e}")
                print(
                    f"[selftest] menu {label} error {type(e).__name__}",
                    flush=True,
                )
    except Exception as e:
        add("menu_live", "menu", False, f"{type(e).__name__}: {e}")

    # Interactive commands cannot be automated without a user reply.
    add(
        "commands_live", "guide",
        True,
        "skipped: interactive consultation (waits for user input)",
        warning=True,
    )

    # Commands
    total_cmds = len(SAFE_COMMANDS)
    for idx, (name, args, kwargs) in enumerate(SAFE_COMMANDS, 1):
        cmd = bot.get_command(name)
        if not cmd:
            add("commands_live", name, False, "not registered")
            continue
        ctx = _MockCtx()
        print(f"[selftest] {name} start", flush=True)
        try:
            await asyncio.wait_for(
                cmd.callback(ctx, *args, **kwargs), timeout=45
            )
            add(
                "commands_live", name,
                bool(ctx.sent),
                f"{len(ctx.sent)} responses",
            )
            print(f"[selftest] {name} ok", flush=True)
        except asyncio.TimeoutError:
            add("commands_live", name, False, "timeout after 45s")
            print(f"[selftest] {name} TIMEOUT", flush=True)
        except Exception as e:
            add("commands_live", name, False, f"{type(e).__name__}: {e}")
            print(
                f"[selftest] {name} error {type(e).__name__}: {e}",
                flush=True,
            )

        if progress and (idx % 4 == 0 or idx == total_cmds):
            try:
                res = progress("COMMAND HARNESS", results)
                if asyncio.iscoroutine(res):
                    await res
            except Exception:
                pass

    if progress:
        try:
            res = progress("COMMAND HARNESS", results)
            if asyncio.iscoroutine(res):
                await res
        except Exception:
            pass

    return results

