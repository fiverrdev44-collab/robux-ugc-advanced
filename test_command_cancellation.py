"""Integration tests: the actual research command paths use cancellation.

These register the real commands on a fake bot, replace the PostgreSQL
connection with a fake that records ``cancel()``, and verify that a timed-out
command cancels the read-only database statement and emits exactly one
timeout message (no duplicates).
"""
import asyncio
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bot_core
import commands_advanced
import commands_intel
import commands_market
import execution_policy as ep


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, *a, **k):
        pass

    def fetchall(self):
        # Simulate a long-running query that stops when cancelled.
        deadline = time.time() + 5
        while time.time() < deadline:
            if self.conn.cancelled:
                return []
            time.sleep(0.01)
        return []

    def fetchone(self):
        return (0,)

    def close(self):
        pass


class FakeConn:
    def __init__(self):
        self.cancel_calls = 0
        self.cancelled = False
        self.closed = False

    def cursor(self):
        return FakeCursor(self)

    def cancel(self):
        self.cancel_calls += 1
        self.cancelled = True

    def close(self):
        self.closed = True


class FakeMessage:
    def __init__(self, channel):
        self.channel = channel

    async def edit(self, content=None, **kw):
        self.channel.edits.append(content)
        return self

    async def delete(self):
        pass


class FakeChannel:
    def __init__(self):
        self.sent = []
        self.edits = []

    async def send(self, content=None, **kw):
        self.sent.append(content)
        return FakeMessage(self)


class FakeCtx:
    def __init__(self):
        self.channel = FakeChannel()

    async def send(self, content=None, **kw):
        self.channel.sent.append(content)
        return FakeMessage(self.channel)


class FakeBot:
    def __init__(self):
        self.commands = {}

    def command(self, name=None, **kw):
        def deco(fn):
            self.commands[name or kw.get("name")] = fn
            return fn
        return deco


def _budget_messages(ctx):
    msgs = list(ctx.channel.sent) + list(ctx.channel.edits)
    return [m for m in msgs if m and "budget" in m.lower()]


class CommandCancellationTests(unittest.TestCase):
    def test_momentum_command_path_cancels_db(self):
        bot = FakeBot()
        commands_intel.register_intel_commands(
            bot, bot_core.get_db, bot_core.ASSET_TYPE_NAMES)
        conn = FakeConn()
        ctx = FakeCtx()

        def fake_momentum(*a, **k):
            while True:
                ep.check_cancelled()
                time.sleep(0.01)

        with mock.patch.object(bot_core.psycopg2, "connect",
                               return_value=conn), \
                mock.patch.object(commands_intel, "find_momentum_keywords",
                                  side_effect=fake_momentum), \
                mock.patch.object(ep, "budget_seconds", return_value=0.05):
            asyncio.run(bot.commands["momentum"](ctx))

        self.assertGreaterEqual(conn.cancel_calls, 1)
        self.assertEqual(len(_budget_messages(ctx)), 1)

    def test_gap_command_path_cancels_db(self):
        bot = FakeBot()
        commands_market.register_market_commands(bot)
        conn = FakeConn()
        ctx = FakeCtx()
        with mock.patch.object(bot_core.psycopg2, "connect",
                               return_value=conn), \
                mock.patch.object(ep, "budget_seconds", return_value=0.05):
            asyncio.run(bot.commands["gap"](ctx))

        self.assertGreaterEqual(conn.cancel_calls, 1)
        self.assertEqual(len(_budget_messages(ctx)), 1)

    def test_converge_command_path_cancels_db(self):
        bot = FakeBot()
        commands_advanced.register_advanced_commands(bot, bot_core.get_db)
        conn = FakeConn()
        ctx = FakeCtx()
        with mock.patch.object(bot_core.psycopg2, "connect",
                               return_value=conn), \
                mock.patch.object(ep, "budget_seconds", return_value=0.05):
            asyncio.run(bot.commands["converge"](ctx))

        self.assertGreaterEqual(conn.cancel_calls, 1)
        self.assertEqual(len(_budget_messages(ctx)), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
