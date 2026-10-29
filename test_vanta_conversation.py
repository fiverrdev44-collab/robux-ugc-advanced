"""Pure tests for the conversational router. No Discord connection required."""
import asyncio
import vanta_conversation as vc
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
    assert classify_intent("check my item", use_ai=False)["intent"] == "list_my_items"
    assert classify_intent("tags", use_ai=False)["intent"] == "tags"
    assert classify_intent("tags cute beanie", use_ai=False)["concept"] == "cute beanie"
    assert classify_intent("tags", use_ai=False)["intent"] == "tags"
    assert classify_intent("tags cute beanie", use_ai=False)["concept"] == "cute beanie"
    bare = classify_intent("99610366014241", use_ai=False)
    assert bare["intent"] == "inspect_item" and bare["item_id"] == 99610366014241
    state = ConversationState(user_id=1)
    state.last_item_id = 99610366014241
    assert classify_intent("check", state=state, use_ai=False)["item_id"] == 99610366014241
    assert classify_intent("change title of my old item",
                           use_ai=False)["intent"] == "list_my_items"
    route = classify_intent("I want to inspect or change title of my item",
                            use_ai=False)
    assert route["intent"] == "list_my_items"
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
    assert classify_intent("the first one", state=state, use_ai=False)["item_id"] == 111111111111
    changed = classify_intent("change the title of the first one",
                              state=state, use_ai=False)
    assert changed["intent"] == "improve_metadata" and changed["item_id"] == 111111111111
    state.pending_intent = "tags"
    state.item_titles = {111111111111: "Aura Dance Emote"}
    picked = classify_intent("1", state=state, use_ai=False)
    assert picked["intent"] == "tags" and picked["item_id"] == 111111111111
    existing = classify_intent("can i use my existing name of item?",
                               state=state, use_ai=False)
    assert existing["intent"] == "tags"
    state.pending_intent = "tags"
    state.item_titles = {111111111111: "Aura Dance Emote"}
    picked = classify_intent("1", state=state, use_ai=False)
    assert picked["intent"] == "tags" and picked["item_id"] == 111111111111
    existing = classify_intent("can i use my existing name of item?",
                               state=state, use_ai=False)
    assert existing["intent"] == "tags"
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
    assert clean_concept("i want to change tags") is None
    change_tags = classify_intent("i want to change tags", use_ai=False)
    assert change_tags["intent"] == "tags" and change_tags["concept"] is None
    item_tags = classify_intent("change tags of item 121930221694467", use_ai=False)
    assert item_tags["intent"] == "tags" and item_tags["concept"] is None
    assert item_tags["item_id"] == 121930221694467
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


def test_ai_planner_validation():
    state = ConversationState(user_id=1)
    state.last_item_id = 99610366014241
    state.item_titles = {99610366014241: "Anime Battle Fighting Stance"}
    original = vc._planner_ai

    def fake(text, has_attachment, st):
        return {"action": "tags", "item_id": None, "concept": None,
                "family": "emotes", "confidence": 0.92, "clarify": None}

    vc._planner_ai = fake
    try:
        route = asyncio.run(vc.plan_message("tag it", False, state))
    finally:
        vc._planner_ai = original
    assert route["intent"] == "tags"
    assert route["item_id"] == 99610366014241

    def fake_bad(text, has_attachment, st):
        return {"action": "run_shell", "confidence": 0.99}

    vc._planner_ai = fake_bad
    try:
        route = asyncio.run(vc.plan_message("do the thing", False, state))
    finally:
        vc._planner_ai = original
    assert route["intent"] == "clarify"

    vc._planner_ai = fake
    try:
        route = asyncio.run(vc.plan_message("hi", False, state))
    finally:
        vc._planner_ai = original
    assert route["intent"] == "greeting"

    def fake_clarify(text, has_attachment, st):
        return {"action": "clarify", "confidence": 0.8,
                "clarify": "Which item do you mean?"}

    vc._planner_ai = fake_clarify
    try:
        route = asyncio.run(vc.plan_message("do the thing", False, state))
    finally:
        vc._planner_ai = original
    assert route["intent"] == "clarify"
    assert route["question"] == "Which item do you mean?"

    state.ai_calls = []
    vc._planner_ai = fake
    try:
        asyncio.run(vc.plan_message("tag it", False, state))
    finally:
        vc._planner_ai = original
    assert len(state.ai_calls) == 1
    print("PASS AI planner validation and fast paths")


def test_selection_skips_ai():
    state = ConversationState(user_id=1)
    state.pending_intent = "tags"
    state.results = [111111111111]
    state.item_titles = {111111111111: "Aura Dance Emote"}
    original = vc._planner_ai

    def boom(*args, **kwargs):
        raise AssertionError("planner should not run for selections")

    vc._planner_ai = boom
    try:
        route = asyncio.run(vc.plan_message("1", False, state))
    finally:
        vc._planner_ai = original
    assert route["intent"] == "tags" and route["item_id"] == 111111111111
    print("PASS selection fast path")


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
    test_ai_planner_validation()
    test_selection_skips_ai()
    test_invalid_intent_rejected()
    print("ALL TESTS PASSED")
