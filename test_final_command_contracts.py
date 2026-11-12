"""Registration, dispatch, alias, and authorization contracts for every command."""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import command_security as cs  # noqa: E402


def test_every_registered_command_has_dispatch_and_policy():
    import discord_ugc_bot as bot_module
    bot = bot_module.bot
    runtime = {c.name: c for c in bot.commands}
    assert set(runtime) == cs.ALL_COMMANDS
    assert len(runtime) == 91
    assert "background_analyze" in runtime

    cs.configure_for_tests(user_limit=100, owner_limit=100,
                           global_limit=1000, window_seconds=60)
    cs.configure_emote_title_for_tests(user_limit=100, owner_limit=100,
                                       global_limit=1000, window_seconds=60)
    owner_patch = mock.patch.object(
        cs, "_owner_ids", return_value={900000000000000001})
    owner_patch.start()
    try:
        for name, command in runtime.items():
            policy = cs.policy_for(name)
            assert policy["known"] is True, name
            assert callable(command.callback), name
            assert command.name == name
            for alias in command.aliases:
                assert cs.canonical_command_name(alias) == name, (name, alias)
                assert bot.get_command(alias) is command, (name, alias)

            non_owner = cs.authorize_command(name, 900000000000000002)
            owner = cs.authorize_command(name, 900000000000000001)
            if policy["level"] == "owner":
                assert not non_owner.allowed, name
            else:
                assert non_owner.allowed, name
            assert owner.allowed, name
    finally:
        owner_patch.stop()
        cs.configure_for_tests()
        cs.configure_emote_title_for_tests()
        cs.reset_for_tests()
    print("PASS all 91 commands dispatch, alias, and authorization contracts")


def test_unknown_command_fails_closed():
    decision = cs.authorize_command("definitely_not_a_command", 1)
    assert not decision.allowed
    assert decision.level == "owner"
    print("PASS unknown command fails closed")


if __name__ == "__main__":
    test_every_registered_command_has_dispatch_and_policy()
    test_unknown_command_fails_closed()
    print("ALL FINAL COMMAND CONTRACT TESTS PASSED")
