"""Pure tests for the conversational router. No Discord connection required."""
import asyncio
from vanta_conversation import (
    ConversationState, ConversationStore, classify_intent, clean_concept,
    extract_item_id, _intent, INTENTS, _run_registry,
    thread_name, parse_thread_name,
)


def test_item_extraction():
    assert extract_item_id("check this https://www.roblox.com/catalog/121930221694467/x") == 121930221694467
    assert extract_item_id("item 92364796546749 please") == 92364796546749
    assert extract_item_id("no id here") is None
    print("PASS item extraction")


def test_core_intents():
    cases = [
        ("yo check this item 121930221694467", "inspect_item"),
        ("chek this item 121930221694467", "inspect_item"),
        ("why is this item doing so badly? 121930221694467", "diagnose_item"),
        ("what went wrong with 121930221694467", "diagnose_item"),
        ("revive this item 121930221694467", "revive_item"),
        ("find me a niche with low competition", "find_opportunities"),
        ("what's trending and where is there a gap?", "find_opportunities"),
        ("give me ideas for a kawaii cat beanie", "create_ideas"),
        ("fix the title and description 121930221694467", "improve_metadata"),
        ("how much have i made recently?", "check_sales"),
        ("show my experiment results", "check_experiments"),
        ("show my search visibility", "check_visibility"),
        ("run a data audit", "data_audit"),
    ]
    for text, expected in cases:
        got = classify_intent(text, use_ai=False)["intent"]
        assert got == expected, (text, got, expected)
    print("PASS core intent routing")


def test_conversational_glue():
    assert classify_intent("hi", use_ai=False)["intent"] == "greeting"
    assert classify_intent("Did u disconnect?", use_ai=False)["intent"] == "presence"
    assert classify_intent("thanks", use_ai=False)["intent"] == "ack"
    assert classify_intent("yo check this item 121930221694467",
                           use_ai=False)["intent"] == "inspect_item"
    route = classify_intent("I want to inspect or change title of my item",
                            use_ai=False)
    assert route["intent"] == "clarify"
    assert "item ID" in route["question"]
    print("PASS conversational glue")


def test_image_and_help():
    assert classify_intent("yo i made this, how does it look?",
                           has_attachment=True, use_ai=False)["intent"] == "analyze_image"
    assert classify_intent("what can you do?", use_ai=False)["intent"] == "help"
    print("PASS image and help routing")


def test_followups():
    state = ConversationState(user_id=1)
    state.results = [111111111111, 222222222222]
    state.last_intent = "inspect_item"
    state.last_item_id = 111111111111
    assert classify_intent("the second one", state=state, use_ai=False)["item_id"] == 222222222222
    assert classify_intent("go deeper", state=state, use_ai=False)["intent"] == "diagnose_item"
    same = classify_intent("same for this item 333333333333", state=state, use_ai=False)
    assert same["intent"] == "inspect_item" and same["item_id"] == 333333333333
    better = classify_intent("make a better title and description", state=state, use_ai=False)
    assert better["intent"] == "improve_metadata" and better["item_id"] == 111111111111
    print("PASS follow-up context")


def test_family_and_concept():
    route = classify_intent("find a low competition beanie niche", use_ai=False)
    assert route["intent"] == "find_opportunities" and route["family"] == "headwear"
    assert clean_concept("give me ideas for a kawaii cat beanie") == "kawaii cat beanie"
    print("PASS family and concept extraction")


def test_signed_thread_names():
    name = thread_name(121930221694467)
    assert parse_thread_name(name) == 121930221694467
    assert parse_thread_name("vanta-121930221694467-000000000000") is None
    assert parse_thread_name("random-thread") is None
    print("PASS signed thread ownership")


def test_store_isolation():
    store = ConversationStore()
    a = store.create(1, 100)
    b = store.create(2, 200)
    a.last_item_id = 111
    assert store.get(1).last_item_id == 111
    assert store.get(2).last_item_id is None
    assert b.user_id == 200
    print("PASS conversation isolation")


class _FakeChannel:
    def __init__(self):
        self.messages = []
    async def send(self, content=None, **kwargs):
        self.messages.append(content or "")
    def typing(self):
        class _Ctx:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
        return _Ctx()


class _FakeMessage:
    def __init__(self, channel):
        self.channel = channel
        self.author = type("U", (), {"id": 1, "bot": False})()
        self.content = ""
        self.attachments = []
        self.id = 1


class _FakeCommand:
    def __init__(self):
        self.called = None
    async def callback(self, ctx, **kwargs):
        self.called = kwargs
        await ctx.send("Checked item 121930221694467")


class _FakeBot:
    def __init__(self):
        self.cmd = _FakeCommand()
    def get_command(self, name):
        return self.cmd if name == "verdict" else None


def test_registry_execution_and_context():
    channel = _FakeChannel()
    message = _FakeMessage(channel)
    bot = _FakeBot()
    state = ConversationState(user_id=1)
    route = {"intent": "inspect_item", "item_id": 121930221694467,
             "concept": None, "family": None}
    asyncio.run(_run_registry(bot, message, route, state))
    assert bot.cmd.called == {"item_id": 121930221694467}
    assert 121930221694467 in state.results
    assert state.last_intent == "inspect_item"
    assert any("Checked item" in m for m in channel.messages)
    print("PASS registry execution and context capture")


def test_invalid_intent_rejected():
    assert _intent("run_shell")["intent"] == "clarify"
    assert "run_shell" not in INTENTS
    pending = classify_intent("flurbo glimbo zorp", use_ai=True)
    assert pending["intent"] == "clarify" and pending.get("ai_fallback") is True
    print("PASS invalid intent rejection and AI fallback flag")


if __name__ == "__main__":
    test_item_extraction()
    test_core_intents()
    test_conversational_glue()
    test_image_and_help()
    test_followups()
    test_family_and_concept()
    test_signed_thread_names()
    test_store_isolation()
    test_registry_execution_and_context()
    test_invalid_intent_rejected()
    print("ALL TESTS PASSED")
