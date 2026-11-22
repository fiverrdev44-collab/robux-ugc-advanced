"""Regressions for the real 'last year' -> unwanted 30 day sales report.

Offline router, callback, and query-window checks. No Discord/API/DB traffic.
"""
import asyncio
from datetime import date
from types import SimpleNamespace
from unittest import mock
import vanta_conversation as vc
from reporting import window_bounds


class FakeCtx:
    def __init__(self, phrase):
        self.content = phrase
        self.author = SimpleNamespace(id=1)
        self.channel = SimpleNamespace(id=9, messages=[])
        async def send(content=None, **kwargs):
            self.channel.messages.append(content)
        self.channel.send = send


class FakeCommand:
    def __init__(self):
        self.kwargs = None
    async def callback(self, ctx, **kwargs):
        self.kwargs = kwargs
        await ctx.send("sales report")


class FakeBot:
    def __init__(self):
        self.calls = []
        self.cmd = FakeCommand()
    def get_command(self, name):
        self.calls.append(name)
        return self.cmd if name == "sales_report" else None


def test_year_parser_mappings():
    for phrase in ("last year", "past year", "previous year",
                   "this year", "yearly", "annual", "annually",
                   "sales last year", "sales for the past 12 months",
                   "sales last 365 days", "365 days",
                   "last 52 weeks", "past 1 year", "12 months sales"):
        assert vc.parse_sales_window(phrase) == 365, phrase
    assert vc.parse_sales_window("show sales last 30 days") == 30
    assert vc.parse_sales_window("sales last 7 days") == 7
    assert vc.parse_sales_window("last month sales") == 30
    assert vc.parse_sales_window("sales yesterday") == 1
    assert vc.parse_sales_window("sales today") == 1
    assert vc.parse_sales_offset("sales yesterday") == 1
    assert vc.parse_sales_window("what is the item price in days?") is None
    assert vc.parse_sales_window("first 3 months of 2025") is None


def test_explicit_year_sales_routes_to_registered_365_day_callback():
    for phrase, expected_days in (
        ("give me sales for last year", 365),
        ("show my sales last 365 days", 365),
        ("my revenue in past 12 months", 365),
        ("check my sales last 30 days", 30),
        ("show my sales last 7 days", 7),
    ):
        state = vc.ConversationState(user_id=1)
        with mock.patch.object(vc, "_v2_enabled", return_value=True):
            route = asyncio.run(vc.plan_message(phrase, False, state))
        assert route["intent"] == "check_sales", (phrase, route)
        assert route["days"] == expected_days, (phrase, route)
        bot = FakeBot()
        ctx = FakeCtx(phrase)
        with mock.patch.object(vc, "is_owner", return_value=True):
            asyncio.run(vc._run_registry(bot, ctx, route, state))
        assert bot.calls == ["sales_report"], (phrase, bot.calls)
        assert bot.cmd.kwargs == {"days": expected_days}, (phrase, bot.cmd.kwargs)


def test_bare_period_followup_after_sales_keeps_sales_intent():
    for phrase, expected in (("last year", 365), ("365 days", 365),
                             ("past 12 months", 365), ("this year", 365),
                             ("annual", 365), ("last 30 days", 30),
                             ("7 days", 7), ("last month", 30)):
        state = vc.ConversationState(user_id=1)
        state.last_intent = "check_sales"
        with mock.patch.object(vc, "_v2_enabled", return_value=True):
            route = asyncio.run(vc.plan_message(phrase, False, state))
        assert route["intent"] == "check_sales", (phrase, route)
        assert route["days"] == expected, (phrase, route)
        bot, ctx = FakeBot(), FakeCtx(phrase)
        with mock.patch.object(vc, "is_owner", return_value=True):
            asyncio.run(vc._run_registry(bot, ctx, route, state))
        assert bot.cmd.kwargs == {"days": expected}, (phrase, bot.cmd.kwargs)


def test_unrelated_bare_time_phrase_does_not_inherit_sales():
    state = vc.ConversationState(user_id=1)
    state.last_intent = "inspect_item"
    route = vc.classify_intent("last year", state=state)
    assert route["intent"] != "check_sales", route


def test_365_day_sql_uses_correct_utc_window_not_30():
    start, end, today = window_bounds(None, 365, anchor=date(2026, 11, 22))
    assert str(start) == "2025-11-23", (start, end)
    assert str(end) == "2026-11-23", (start, end)
    start30, end30, _ = window_bounds(None, 30, anchor=date(2026, 11, 22))
    assert str(start30) == "2026-10-24"
    assert end30 == end
    assert start != start30


if __name__ == "__main__":
    test_year_parser_mappings()
    test_explicit_year_sales_routes_to_registered_365_day_callback()
    test_bare_period_followup_after_sales_keeps_sales_intent()
    test_unrelated_bare_time_phrase_does_not_inherit_sales()
    test_365_day_sql_uses_correct_utc_window_not_30()
    print("PASS rolling 365-day sales intent, callback and UTC query window")
