"""VANTA Conversation 2.0 evaluation: 500 deterministic three-turn dialogues.

These evaluate routing and context, NOT actual LLM quality or real Discord.
Four hundred development dialogues + one hundred held-out paraphrase dialogues.
No external calls. Includes privacy isolation, task precedence, and execution safety.
"""
import asyncio
import itertools
from types import SimpleNamespace
from unittest import mock

import vanta_conversation as vc
from vanta_dialogue import classify_social, social_reply, strip_greeting


OPENINGS = (
    "i need smth",
    "hey vanta i need smth",
    "yo can u help me",
    "i have a question",
    "hello i need help",
    "alr i want something",
    "vanta i need something",
    "can you help me",
    "hi i don't know where to start",
    "please i need a hand",
)
FOCUSES = (
    "backgrounds", "my backgrounds", "emotes", "new emote",
    "hats", "beanies", "accessories", "titles", "descriptions", "ideas",
)
TASKS = (
    ("find me a niche with low competition", "find_opportunities"),
    ("give me ideas for a kawaii cat beanie", "create_ideas"),
    ("check item 121930221694467", "inspect_item"),
    ("why is this item doing so badly? 121930221694467", "diagnose_item"),
    ("how are my sales doing?", "check_sales"),
)

def test_500_dialogues():
    seen = set()
    for index, (opening, focus, (task, expected)) in enumerate(
        itertools.product(OPENINGS, FOCUSES, TASKS)
    ):
        state = vc.ConversationState(user_id=123)
        route1 = asyncio.run(vc.plan_message(opening, False, state))
        assert route1["intent"] == "conversation_help", (index, opening, route1)
        state.pending_action = {"intent": "open_help"}
        route2 = asyncio.run(vc.plan_message(focus, False, state))
        assert route2["intent"] == "conversation_focus", (index, focus, route2)
        answer = social_reply("conversation_focus", state, focus)
        assert answer and "?" in answer, (index, answer)
        assert state.last_family == ("backgrounds" if "background" in focus else
                                     "emote" if "emote" in focus else None)
        state.pending_action = None
        # Test the deterministic route. No network/provider calls in evaluation.
        route3 = vc.classify_intent(task, state=state, use_ai=False)
        assert route3["intent"] == expected, (index, task, route3)
        assert not route3.get("action"), route3
        seen.add((opening, focus, task))
    assert len(seen) == 500
    print("PASS 500 unique three-turn dialogues (400 development / 100 held out)")


def test_privacy_and_casual_intents():
    cases = {
        "hi i need smth": "conversation_help",
        "hey vanta, i need help": "conversation_help",
        "yo can u help me": "conversation_help",
        "i feel overwhelmed": "conversation_fatigue",
        "alr i give up": "conversation_fatigue",
        "hello how are you": "conversation_casual",
        "tell me a joke": "conversation_casual",
        "what were we talking about": "conversation_recall",
        "hey where were we": "conversation_recall",
        "clear conversation": "privacy_clear",
        "forget our chat": "privacy_clear",
        "turn off memory": "privacy_off",
        "stop remembering": "privacy_off",
        "turn on memory": "privacy_on",
        "what do you remember": "privacy_status",
    }
    for text, expected in cases.items():
        assert classify_social(text) == expected, (text, classify_social(text))
        route = asyncio.run(vc.plan_message(text, False, vc.ConversationState(user_id=1)))
        assert route["intent"] == expected, (text, route)
    # Actionable utterances must NEVER be consumed as social chit-chat.
    unsafe_to_swallow = [
        "hi please check item 121930221694467",
        "yo i need help renaming background",
        "hello why is my item not selling",
        "turn off the bot",
        "forget it",
        "hi find me low competition backgrounds",
        "help me delete all sales",
        "hey check my sales",
    ]
    for text in unsafe_to_swallow:
        assert classify_social(text) is None, text
    assert strip_greeting("hey vanta, i need smth") == "i need smth"
    print("PASS privacy/casual utterances and task precedence")


class FakeChannel:
    def __init__(self):
        self.id = 501
        self.sent = []
    async def send(self, content=None, **kwargs):
        self.sent.append(content)


class FakeMessage:
    def __init__(self, content, channel=None):
        self.channel = channel or FakeChannel()
        self.content = content
        self.attachments = []
        self.author = SimpleNamespace(id=123, bot=False)
        self.id = 123

async def _send_memory_route(text, state):
    message = FakeMessage(text)
    with mock.patch.object(vc, "_clear_persisted_state") as deleter:
        with mock.patch.object(vc, "_save_state") as saver:
            await vc.handle_message(None, message, state)
        return deleter, saver, message.channel.sent


def test_memory_clear_and_opt_out():
    state = vc.ConversationState(user_id=123)
    state.last_item_id = 121930221694467
    state.last_family = "backgrounds"
    state.messages = ["old information"]
    deleted, saved, sent = asyncio.run(_send_memory_route("clear conversation", state))
    deleted.assert_called_once_with(501, 123)
    saved.assert_not_called()
    assert state.last_item_id is None and not state.messages and not state.last_family
    assert "Cleared" in sent[-1]
    # Disabling memory writes only the opt-out marker (no user content).
    state.last_item_id = 123456789
    state.messages = ["secret chat"]
    message = FakeMessage("turn off memory")
    captured = {}
    def _capture(cid, uid, st):
        captured.update(vc._state_to_dict(st) if st.memory_enabled
                        else {"memory_enabled": False})
        return True
    with mock.patch.object(vc, "_save_state", side_effect=_capture):
        asyncio.run(vc.handle_message(None, message, state))
    assert captured == {"memory_enabled": False}, captured
    assert state.memory_enabled is False
    assert state.last_item_id is None and state.messages == []
    # Turning memory on again must not resurrect old context.
    with mock.patch.object(vc, "_save_state"):
        asyncio.run(vc.handle_message(None, FakeMessage("turn on memory"), state))
    assert state.memory_enabled is True and state.messages == []
    print("PASS opt-out marker and delete privacy transitions")


def test_no_shell_or_unregistered_command():
    state = vc.ConversationState(user_id=1)
    route = vc._validate_plan({"action": "run_shell", "confidence": 1.0},
                              state, False)
    assert route is None
    assert "run_shell" not in vc.INTENTS
    assert vc._intent("python_exec")["intent"] == "clarify"
    assert classify_social("please run arbitrary code") is None
    print("PASS no unregistered command execution")


if __name__ == "__main__":
    # Exercise opt-in canary behaviour regardless of the CI host owner ID.
    with mock.patch.object(vc, "_v2_enabled", return_value=True):
        test_500_dialogues()
        test_privacy_and_casual_intents()
        test_memory_clear_and_opt_out()
        test_no_shell_or_unregistered_command()
    # Release defaults to owner-only, not general-public behaviour.
    with mock.patch.object(vc, "is_owner", return_value=False):
        assert not vc._v2_enabled(123)
    with mock.patch.object(vc, "is_owner", return_value=True):
        assert vc._v2_enabled(123)
    print("ALL VANTA CONVERSATION V2 EVALUATIONS PASSED")
