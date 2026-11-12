"""Regression cases copied from actual VANTA conversation failures.

No live Discord / Roblox / production DB traffic. Route + registered callback
and SQL date boundaries are tested deterministically.
"""
import asyncio
from datetime import date
from types import SimpleNamespace
from unittest import mock

import vanta_conversation as vc
from vanta_dialogue import classify_social, social_reply


class FakeCtx:
    def __init__(self, text):
        self.content = text
        self.author = SimpleNamespace(id=1)
        self.channel = SimpleNamespace(id=9, messages=[])
        async def send(content=None, **kwargs):
            self.channel.messages.append(content)
        self.channel.send = send


class FakeCommand:
    def __init__(self):
        self.name = None
        self.kwargs = None
    async def callback(self, ctx, **kwargs):
        self.kwargs = kwargs
        await ctx.send("sales report")


class FakeBot:
    def __init__(self):
        self.cmd = FakeCommand()
        self.calls = []
    def get_command(self, name):
        self.calls.append(name)
        return self.cmd if name == "sales_report" else None


def test_yesterday_parser():
    assert vc.parse_sales_window("show me yesterday sales") == 1
    assert vc.parse_sales_offset("show me yesterday sales") == 1
    assert vc.parse_sales_window("what were my sales yesterday?") == 1
    assert vc.parse_sales_window("show sales today") == 1
    assert vc.parse_sales_offset("show sales today") == 0
    assert vc.parse_sales_window("show my sales last 7 days") == 7
    assert vc.parse_sales_offset("show my sales last 7 days") == 0
    assert vc.parse_sales_window("sales last 30 days") == 30


def test_yesterday_routes_to_correct_registered_args():
    for phrase in ("show me yesterday sales", "what were my sales yesterday?"):
        state = vc.ConversationState(user_id=1)
        with mock.patch.object(vc, "_v2_enabled", return_value=True):
            route = asyncio.run(vc.plan_message(phrase, False, state))
        assert route["intent"] == "check_sales", route
        assert route["days"] == 1 and route["day_offset"] == 1, route
        bot = FakeBot()
        ctx = FakeCtx(phrase)
        with mock.patch.object(vc, "is_owner", return_value=True):
            asyncio.run(vc._run_registry(bot, ctx, route, state))
        assert bot.calls == ["sales_report"], bot.calls
        assert bot.cmd.kwargs == {"days": 1, "day_offset": 1}, bot.cmd.kwargs


def test_background_capability_is_not_a_market_scan():
    questions = [
        "do u do backgrounds?",
        "do you do backgrounds",
        "can you support backgrounds?",
        "hey vanta do u do backgrounds?",
        "are u familiar with avatar backgrounds?",
    ]
    for question in questions:
        state = vc.ConversationState(user_id=1)
        with mock.patch.object(vc, "_v2_enabled", return_value=True):
            route = asyncio.run(vc.plan_message(question, False, state))
        assert route["intent"] == "conversation_capabilities", (question, route)
        ctx = FakeCtx(question)
        bot = FakeBot()
        asyncio.run(vc._run_registry(bot, ctx, route, state))
        assert bot.calls == [], (question, bot.calls)
        assert "Background" in ctx.channel.messages[-1]
        assert "What would you like" in ctx.channel.messages[-1]


def test_real_background_request_still_routes_to_market_intelligence():
    # "Can you find background opportunities" is not a capability question.
    question = "find me a low competition background niche"
    assert classify_social(question) is None
    route = vc.classify_intent(question, use_ai=False)
    assert route["intent"] == "find_opportunities" and route["family"] == "backgrounds"
    assert classify_social("can you make a background concept?") is None
    assert classify_social("do u do backgrounds for money?") is None


def test_sales_period_spans_complete_yesterday():
    import sales_listener
    from datetime import timedelta
    from reporting import window_bounds, describe_window
    anchor = date(2026, 11, 12)
    start, end, _ = window_bounds(None, 1, anchor=anchor)
    assert (start, end) == (date(2026,11,12),date(2026,11,13))
    assert (start - timedelta(days=1), end - timedelta(days=1)) == (
        date(2026,11,11),date(2026,11,12))
    info = describe_window(date(2026,11,11),date(2026,11,12),anchor)
    assert info["today_partial"] is False
    assert info["start"] == "2026-11-11"
    assert info["end_exclusive"] == "2026-11-12"


def test_real_sales_summary_filters_yesterday_only():
    import sales_listener
    import item_resolver
    class Cursor:
        def __init__(self):
            self.params = []
        def execute(self, sql, params=None):
            self.params.append((sql, params))
        def fetchone(self):
            return (date(2026, 11, 12),)
        def fetchall(self):
            return [(date(2026, 11, 11), 17, 331)]
        def close(self):
            pass
    class Conn:
        def __init__(self):
            self.cur = Cursor()
        def cursor(self):
            return self.cur
        def close(self):
            pass
    conn = Conn()
    boundaries = []
    def breakdown(cur, start, end):
        boundaries.append((start, end))
        return {
            "totals": {"records": 17, "robux": 331},
            "items": [],
        }
    with mock.patch.object(sales_listener, "get_db", return_value=conn), \
         mock.patch.object(item_resolver, "sales_breakdown", side_effect=breakdown), \
         mock.patch.object(sales_listener, "window_coverage_stats", return_value={
             "internally_consistent": False, "fallback_fingerprint": 1,
         }):
        result = sales_listener.sales_summary(1, day_offset=1)
    assert boundaries == [(date(2026,11,11),date(2026,11,12))]
    assert result["window"]["today_partial"] is False
    assert result["total_units"] == 17 and result["total_robux"] == 331
    daily_sql = [(query, params) for query, params in conn.cur.params
                 if "from my_sales" in query.lower()]
    assert len(daily_sql) == 1
    assert daily_sql[0][1] == (date(2026,11,11),date(2026,11,12))
    print("PASS SQL sales summary reads exactly yesterday UTC")


if __name__ == "__main__":
    test_yesterday_parser()
    test_yesterday_routes_to_correct_registered_args()
    test_background_capability_is_not_a_market_scan()
    test_real_background_request_still_routes_to_market_intelligence()
    test_sales_period_spans_complete_yesterday()
    test_real_sales_summary_filters_yesterday_only()
    print("ALL EXACT-INTENT ROUTING REGRESSIONS PASSED")
