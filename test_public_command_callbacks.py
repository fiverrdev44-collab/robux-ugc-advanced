"""Callback-level behavioral tests for the 34 public NOT TESTED commands.

Every test invokes the real registered callback from discord_ugc_bot. External
providers are mocked; no production database or Roblox API is contacted.
"""
import asyncio
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest import mock

import discord
from discord.ext import commands as dcommands

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import command_security as cs  # noqa: E402
import discord_ugc_bot as botmod  # noqa: E402

BOT = botmod.bot
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)


class FakeMessage:
    def __init__(self, content=None, embed=None, view=None):
        self.content = content
        self.embed = embed
        self.view = view
        self.deleted = False
        self.edits = []

    async def edit(self, content=None, embed=None, **kwargs):
        if content is not None:
            self.content = content
        if embed is not None:
            self.embed = embed
        self.edits.append((self.content, self.embed))
        return self

    async def delete(self):
        self.deleted = True


class FakeAuthor:
    def __init__(self):
        self.id = 900000000000000011
        self.display_name = "Tester"
        self.name = "Tester"
        self.bot = False


class FakeGuild:
    id = 1
    name = "Test Guild"
    owner_id = 1


class FakeChannel:
    id = 10
    guild = FakeGuild()
    name = "test-channel"

    def __init__(self):
        self.ctx = None

    async def send(self, content=None, embed=None, **kwargs):
        if self.ctx is not None:
            return await self.ctx.send(content=content, embed=embed, **kwargs)
        return FakeMessage(content=content, embed=embed)


class FakeTyping:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def __await__(self):
        async def _done():
            return self
        return _done().__await__()


class FakeCtx:
    def __init__(self, command_name=""):
        self.author = FakeAuthor()
        self.channel = FakeChannel()
        self.channel.ctx = self
        self.guild = FakeGuild()
        self.message = FakeMessage(content="")
        self.bot = BOT
        self.command = type(
            "Cmd", (), {"name": command_name,
                        "qualified_name": command_name,
                        "aliases": []})()
        self.clean_prefix = "!"
        self.invoked_with = command_name
        self.messages = []

    async def send(self, content=None, embed=None, view=None, **kwargs):
        msg = FakeMessage(content=content, embed=embed, view=view)
        self.messages.append(msg)
        return msg

    async def reply(self, content=None, embed=None, **kwargs):
        return await self.send(content=content, embed=embed, **kwargs)

    def typing(self):
        return FakeTyping()

    async def wait_for(self, event, **kwargs):
        return FakeMessage(content="cancel")

    def text(self):
        parts = []
        for msg in self.messages:
            if msg.content:
                parts.append(str(msg.content))
            if msg.embed is not None:
                parts.append(str(getattr(msg.embed, "title", "")))
                parts.append(str(getattr(msg.embed, "description", "")))
                for field in getattr(msg.embed, "fields", []):
                    parts.append(str(field.name))
                    parts.append(str(field.value))
            for _, embed in msg.edits:
                if embed is not None:
                    parts.append(str(getattr(embed, "title", "")))
                    parts.append(str(getattr(embed, "description", "")))
            if msg.content:
                parts.append(str(msg.content))
        return "\n".join(parts)


class FakeCursor:
    def __init__(self, handler=None):
        self.handler = handler or (lambda sql, params: {})
        self.result = {}

    def execute(self, sql, params=None):
        self.result = self.handler(str(sql), params) or {}

    def fetchone(self):
        return self.result.get("one")

    def fetchall(self):
        return self.result.get("all", [])

    def mogrify(self, template, args):
        return (str(template) % tuple(args)).encode()

    def close(self):
        pass


class FakeConn:
    def __init__(self, handler=None):
        self.cur = FakeCursor(handler)

    def cursor(self):
        return self.cur

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


@contextmanager
def _db(callback, handler):
    factory = lambda: FakeConn(handler)
    globals_ = callback.__globals__
    missing = object()
    old_globals = {k: globals_.get(k, missing)
                   for k in ("get_db", "get_research_db")}
    for key in ("get_db", "get_research_db"):
        globals_[key] = factory
    cell_state = []
    for name, cell in zip(callback.__code__.co_freevars,
                          callback.__closure__ or ()):
        if name in ("get_db", "get_research_db"):
            try:
                old = cell.cell_contents
            except ValueError:
                old = missing
            cell_state.append((cell, old))
            cell.cell_contents = factory
    try:
        yield
    finally:
        for key, old in old_globals.items():
            if old is missing:
                globals_.pop(key, None)
            else:
                globals_[key] = old
        for cell, old in cell_state:
            if old is missing:
                try:
                    del cell.cell_contents
                except Exception:
                    pass
            else:
                cell.cell_contents = old


def _callback(name):
    cmd = BOT.get_command(name)
    assert cmd is not None, name
    return cmd.callback


def _run(name, ctx=None, **kwargs):
    ctx = ctx or FakeCtx(name)
    cb = _callback(name)
    asyncio.run(asyncio.wait_for(cb(ctx, **kwargs), 10))
    return ctx


def _assert_public(name):
    assert cs.authorize_command(name, 1).allowed, name


def _fake_paginator(*args, **kwargs):
    class V:
        def build_embed(self):
            return discord.Embed(title="FAKE PAGINATOR")
    return V()


def _rows_handler(sql, params):
    if "watchlist" in sql:
        return {"all": [("dance", 10, NOW)]}
    if "saved_consultations" in sql:
        return {"all": [("dance", "VIABLE", "ðŸŸ¡", NOW)]}
    if "item_history" in sql:
        return {"all": [(100, 10, NOW)]}
    if "SELECT name FROM items" in sql:
        return {"one": ("Tracked Item",)}
    if "description, favorite_count" in sql:
        return {"all": [("a", "cute dance", 100),
                        ("b", "cute fun", 50),
                        ("c", "cute wave", 25)]}
    if "SELECT name, description FROM items" in sql:
        return {"all": [("dance emote", "cute dance"),
                        ("dance move", "fun dance"),
                        ("dance wave", "wave dance")]}
    if "current_setting('TimeZone')" in sql:
        return {"one": ("UTC", NOW, NOW.date())}
    if "min(sale_date)" in sql:
        return {"one": (0, None, None)}
    if "GROUP BY sale_date" in sql:
        return {"all": []}
    if "select name, favorite_count, price, asset_type_id" in sql:
        return {"one": None}
    if "COUNT(DISTINCT item_id)" in sql:
        return {"one": (0, 0, None, None, 0)}
    if "HAVING COUNT(*) >= 2" in sql:
        return {"one": (0,)}
    if "MAX(favorite_count) - MIN(favorite_count) > 5" in sql:
        return {"one": (0,)}
    if "COALESCE(SUM(amount_robux" in sql:
        return {"one": (0, 0)}
    if "SELECT LOWER(name), COALESCE" in sql:
        return {"all": [("a", "cute"), ("b", "cute"), ("c", "cute")]}
    if "SELECT LOWER(name)" in sql:
        return {"all": [("a",), ("b",), ("c",)]}
    if "FROM items" in sql:
        return {"all": [("dance emote", "cute dance", 100),
                        ("dance move", "fun dance", 50),
                        ("dance wave", "wave dance", 25)]}
    return {"one": (0,), "all": []}


def test_emote_status_callback():
    _assert_public("emote_status")

    def handler(sql, params):
        if "asset_type_id = 61" in sql:
            return {"one": (42,)}
        if "name ~*" in sql:
            return {"one": (7,)}
        return {"one": (1000,)}
    ctx = FakeCtx("emote_status")
    with _db(_callback("emote_status"), handler):
        ctx = _run("emote_status", ctx)
    assert "Emote Coverage Diagnostic" in ctx.text()
    assert "42" in ctx.text()
    print("PASS emote_status callback output")


def test_watchlist_callback():
    _assert_public("watchlist")
    ctx = FakeCtx("watchlist")
    with _db(_callback("watchlist"), _rows_handler):
        ctx = _run("watchlist", ctx)
    assert "Watchlist" in ctx.text() and "dance" in ctx.text()
    print("PASS watchlist callback output")


def test_history_callback():
    _assert_public("history")
    ctx = FakeCtx("history")
    with _db(_callback("history"), _rows_handler):
        ctx = _run("history", ctx)
    assert "Consultation History" in ctx.text() and "dance" in ctx.text()
    print("PASS history callback output")


def test_scan_status_callback():
    _assert_public("scan_status")
    cb = _callback("scan_status")
    stats = {"discovered": 10, "analyzed": 9, "snapshots": 8,
             "suggestions": 7, "learned": 6, "consultations": 5}
    with mock.patch.dict(cb.__globals__, {
            "get_db": lambda: FakeConn(),
            "get_db_stats": lambda cur: stats}):
        ctx = _run("scan_status")
    assert "Market Intelligence Status" in ctx.text()
    assert "10" in ctx.text() and "9" in ctx.text()
    print("PASS scan_status callback output")


def test_trends_callback():
    _assert_public("trends")
    ctx = FakeCtx("trends")
    with _db(_callback("trends"), _rows_handler):
        ctx = _run("trends", ctx)
    assert "Top Trend Words" in ctx.text() or "No data" in ctx.text()
    print("PASS trends callback output")


def test_analyze_callback_valid_and_missing():
    _assert_public("analyze")
    ctx = FakeCtx("analyze")
    with _db(_callback("analyze"), _rows_handler), \
            mock.patch.object(__import__("commands_market"),
                              "SimplePaginator", _fake_paginator):
        ctx = _run("analyze", ctx, keyword="dance")
    assert "Analyzed" in ctx.text() or "FAKE PAGINATOR" in ctx.text()

    missing = FakeCtx("analyze")
    with _db(_callback("analyze"), lambda sql, params: {"all": []}):
        missing = _run("analyze", missing, keyword="dance")
    assert "No data" in missing.text() or "Not enough data" in missing.text()
    print("PASS analyze valid/missing paths")


def test_opportunity_emote_classic_callbacks():
    import commands_market as cm
    data = {"top_keywords": [("dance", 100, 10, 20)],
            "total_items": 10, "described": 5, "avg_favs": 100,
            "median_favs": 80, "static_share": 0.1, "emote_share": 0.9}
    for name, keyword in (("opportunity", "dance"), ("emote", "dance"),
                          ("classic", "shirt")):
        _assert_public(name)
        ctx = FakeCtx(name)
        with mock.patch.object(cm, "analyze_opportunity",
                               return_value=data), \
                mock.patch.object(cm, "MultiViewPaginator",
                                  _fake_paginator), \
                _db(_callback(name), _rows_handler):
            ctx = _run(name, ctx, keyword=keyword)
        assert ctx.messages, name
    print("PASS opportunity/emote/classic callbacks")


def test_gap_callback():
    import commands_market as cm
    import execution_policy as ep

    async def fake_cancel(name, work):
        return (([(b"dance", 1000.0, 2, 10.0)], None), False, None)

    _assert_public("gap")
    ctx = FakeCtx("gap")
    with mock.patch.object(ep, "to_thread_cancellable", fake_cancel), \
            mock.patch.object(cm, "SimplePaginator", _fake_paginator):
        ctx = _run("gap", ctx)
    assert "FAKE PAGINATOR" in ctx.text() or "Market Gaps" in ctx.text()
    print("PASS gap callback output")


def test_velocity_callback():
    _assert_public("velocity")
    rows = [(1, "Dance", 10, "Maker", 61, 100, 3)]
    ctx = FakeCtx("velocity")
    with _db(_callback("velocity"), lambda sql, params: {"all": rows}):
        ctx = _run("velocity", ctx)
    assert "Fastest Rising Items" in ctx.text() and "Dance" in ctx.text()
    print("PASS velocity callback output")


def test_track_callback():
    _assert_public("track")
    ctx = FakeCtx("track")
    with _db(_callback("track"), _rows_handler):
        ctx = _run("track", ctx, item_id=123)
    assert "Tracking" in ctx.text() and "Tracked Item" in ctx.text()
    print("PASS track callback output")


def test_sales_report_callback():
    import sales_listener
    data = {"total_units": 1, "total_robux": 100, "top_items": [("Item", 1, 100)],
            "daily": [], "unresolved": [], "coverage": {"event_id": 1,
            "event_id_complete": True, "complete": True},
            "window": {"start": "a", "end_exclusive": "b", "today_partial": False}}
    _assert_public("sales_report")
    with mock.patch.object(sales_listener, "sales_summary",
                           return_value=data):
        ctx = _run("sales_report")
    assert "SALES REPORT" in ctx.text() and "Sale records" in ctx.text()
    print("PASS sales_report callback output")


def test_sales_for_callback():
    import sales_listener
    data = {"name": "Item", "days": 30, "units": 1, "robux": 100,
            "last_sale": NOW}
    _assert_public("sales_for")
    with mock.patch.object(sales_listener, "item_sales_summary",
                           return_value=data):
        ctx = _run("sales_for", item_name="Item")
    assert "Sales for" in ctx.text() and "Item" in ctx.text()

    with mock.patch.object(sales_listener, "item_sales_summary",
                           return_value=None):
        ctx = _run("sales_for", item_name="Missing")
    assert "No sales found" in ctx.text()
    print("PASS sales_for callback output")


def test_momentum_predict_oracle_nextwave_opportunities_callbacks():
    import commands_intel as ci

    async def fake_thread(name, work):
        fixtures = {
            "momentum": ([{"word": "dance", "momentum_ratio": 2.0}],
                         False, None),
            "predict": ({"heuristic_score": 70, "probability": 70,
                         "verdict": "STRONG", "factors": {}}, False, None),
            "oracle": ({"keyword": "dance", "direction": "HEATING"}, False,
                       None),
            "nextwave": ([{"word": "float", "combined_score": 10}], False,
                         None),
            "opportunities": (([{"keyword": "dance", "combined_score": 1,
                                 "heuristic_score": 50, "verdict": "STRONG",
                                 "momentum_ratio": 1, "velocity": 1,
                                 "item_count": 2}],
                               [{"word": "float"}]), False, None),
        }
        return fixtures[name]

    patches = [
        mock.patch.object(ci, "to_thread_cancellable", fake_thread),
        mock.patch.object(ci, "format_momentum_report", lambda *a, **k: "MOMENTUM"),
        mock.patch.object(ci, "format_prediction", lambda *a, **k: "PREDICTION"),
        mock.patch.object(ci, "format_oracle_forecast", lambda *a, **k: "ORACLE"),
        mock.patch.object(ci, "format_next_wave", lambda *a, **k: "NEXTWAVE"),
        mock.patch.object(ci, "format_daily_feed", lambda *a, **k: "OPPORTUNITIES"),
    ]
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        for name, kwargs in (("momentum", {}), ("predict", {"idea": "dance"}),
                             ("oracle", {"keyword": "dance"}),
                             ("nextwave", {}), ("opportunities", {})):
            _assert_public(name)
            ctx = _run(name, **kwargs)
            assert ctx.text(), name
    print("PASS momentum/predict/oracle/nextwave/opportunities callbacks")


def test_xray_early_patterns_failures_callbacks():
    import commands_xray as cx

    with mock.patch.object(cx, "build_xray", return_value={}), \
            mock.patch.object(cx, "format_xray", return_value="XRAY"), \
            mock.patch.object(cx, "find_early_winners", return_value=[]), \
            mock.patch.object(cx, "format_early_winners",
                              return_value="EARLY"), \
            mock.patch.object(cx, "mine_patterns", return_value=[]), \
            mock.patch.object(cx, "format_patterns", return_value="PATTERNS"), \
            mock.patch.object(cx, "mine_failure_patterns", return_value=[]), \
            mock.patch.object(cx, "format_failure_patterns",
                              return_value="FAILURES"):
        for name, kwargs in (("xray", {}), ("early", {}),
                             ("patterns", {}), ("failures", {})):
            _assert_public(name)
            ctx = FakeCtx(name)
            with _db(_callback(name), _rows_handler):
                ctx = _run(name, ctx, **kwargs)
            assert ctx.text(), name
    print("PASS xray/early/patterns/failures callbacks")


def test_whales_callback():
    _assert_public("whales")
    rows = [(1, "Item", "Studio", 10, 100, NOW)]
    ctx = FakeCtx("whales")
    with _db(_callback("whales"),
             lambda sql, params: {"all": rows}):
        ctx = _run("whales", ctx)
    assert ctx.text(), "whales"
    print("PASS whales callback output")


def test_golden_hour_callback():
    import commands_supercomputer as csc
    metrics = {"items": [{"item_id": 1, "name": "Dance", "creator": "Maker",
                         "favorites": 100, "price": 10,
                         "velocity_measured": True, "velocity": 1.0,
                         "snapshot_span_hours": 24}],
               "measured_count": 1}
    _assert_public("golden_hour")
    with mock.patch.object(csc, "golden_hour_metrics",
                           return_value=metrics), \
            _db(_callback("golden_hour"), _rows_handler):
        ctx = _run("golden_hour")
    assert "48-Hour Recent Items" in ctx.text() and "Dance" in ctx.text()
    print("PASS golden_hour callback output")


def test_version_callback():
    _assert_public("version")
    ctx = _run("version")
    assert "Bot version" in ctx.text()
    print("PASS version callback output")


def test_ai_status_callback():
    import commands_ai
    _assert_public("ai_status")
    with mock.patch.object(commands_ai, "is_available", return_value=True):
        ctx = _run("ai_status")
    assert "AI Status: ONLINE" in ctx.text()
    print("PASS ai_status callback output")


def test_emote_title_callback():
    import emote_title_engine
    _assert_public("emote_title")
    with mock.patch.object(emote_title_engine, "generate",
                           return_value={"ok": True}), \
            mock.patch.object(emote_title_engine, "format_report",
                              return_value="EMOTE TITLE REPORT"):
        ctx = _run("emote_title", args="dreamy fairy floats")
    assert "EMOTE TITLE REPORT" in ctx.text()

    empty = _run("emote_title", args="")
    assert "Usage" in empty.text()
    print("PASS emote_title callback output and missing input")


def test_guide_cancel_callback():
    _assert_public("guide")
    cb = _callback("guide")
    with mock.patch.dict(cb.__globals__, {
            "get_db": lambda: (_ for _ in ()).throw(RuntimeError("no db"))}):
        ctx = _run("guide", idea="cancel")
    assert "Cancelled" in ctx.text()
    print("PASS guide cancel callback path")


def test_start_callback():
    _assert_public("start")
    ctx = _run("start")
    assert "COMMAND CENTER" in ctx.text() or ctx.messages
    print("PASS start callback output")


def test_help_callback():
    _assert_public("help")
    ctx = FakeCtx("help")
    old_context = BOT.help_command.context
    BOT.help_command.context = ctx
    try:
        asyncio.run(asyncio.wait_for(
            BOT.help_command.command_callback(ctx), 10))
    finally:
        BOT.help_command.context = old_context
    assert ctx.messages
    print("PASS help callback output")


def test_rising_gaps_callback():
    import commands_advanced as ca
    _assert_public("rising_gaps")
    result = {"candidates": [{"word": "float", "score": 1}]}
    with mock.patch.object(ca, "find_rising_gaps", return_value=result), \
            mock.patch.object(ca, "format_rising_gaps",
                              return_value="RISING GAPS"), \
            _db(_callback("rising_gaps"), _rows_handler):
        ctx = _run("rising_gaps", args="emote")
    assert "RISING GAPS" in ctx.text()
    print("PASS rising_gaps callback output")


def test_experiments_callback():
    import experiments
    import matched_experiments
    _assert_public("experiments")
    with mock.patch.object(experiments, "auto_apply_changes",
                           return_value=0), \
            mock.patch.object(experiments, "measure_due", return_value=0), \
            mock.patch.object(experiments, "summary", return_value={}), \
            mock.patch.object(experiments, "format_summary",
                              return_value="EXPERIMENTS"), \
            mock.patch.object(matched_experiments, "evaluate_due",
                              return_value=0), \
            mock.patch.object(matched_experiments, "recent_lines",
                              return_value=""), \
            _db(_callback("experiments"), _rows_handler):
        ctx = _run("experiments")
    assert "EXPERIMENTS" in ctx.text()
    print("PASS experiments callback output")


def test_visibility_callback():
    import search_visibility
    _assert_public("visibility")
    with mock.patch.object(search_visibility, "coverage",
                           return_value={}), \
            mock.patch.object(search_visibility, "format_coverage",
                              return_value="VISIBILITY"), \
            _db(_callback("visibility"), _rows_handler):
        ctx = _run("visibility")
    assert "VISIBILITY" in ctx.text()
    print("PASS visibility callback output")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_")]
    for test in tests:
        test()
    print(f"ALL {len(tests)} PUBLIC COMMAND CALLBACK TESTS PASSED")

