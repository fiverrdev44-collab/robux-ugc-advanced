"""vanta_conversation.py — conversational-first VANTA interface.

A bounded thread-scoped router. It only listens inside threads named
`vanta-<user_id>`, maps natural language to an allow-listed registry of existing
command callbacks, and never executes arbitrary model output.
"""
import asyncio
import hashlib
import hmac
import json
import os
import re
import time
from dataclasses import dataclass, field

import discord

THREAD_RE = re.compile(r"^vanta-(\d+)-([a-f0-9]{12})$", re.I)
URL_ID_RE = re.compile(
    r"(?:catalog|marketplace|library|item)[^\d]{0,20}(\d{6,20})", re.I
)
ITEM_ID_RE = re.compile(r"\b(\d{6,20})\b")
SELECTION_RE = re.compile(
    r"^(?:the\s+)?(?:\d{1,2}|first|second|third|fourth|fifth|last)"
    r"(?:\s+one)?[.!]*$",
    re.I,
)

FAMILIES = {
    "emote": ("emote", "dance", "animation"),
    "hair": ("hair", "wig"),
    "headwear": ("hat", "beanie", "cap", "crown", "beret", "headwear"),
    "face": ("face", "mask", "glasses", "eyes", "eyelash", "eyebrow"),
    "accessory": ("wings", "backpack", "necklace", "chain", "scarf", "tail"),
    "clothing": ("shirt", "pants", "dress", "jacket", "hoodie", "shoes"),
    "gear": ("sword", "staff", "shield", "wand", "gear"),
}

INTENTS = {
    "inspect_item": "Check an existing item and return a KEEP/RENAME/KILL verdict",
    "diagnose_item": "Diagnose why an item is underperforming, with recovery titles",
    "revive_item": "Full revival plan for an item",
    "analyze_image": "Analyze an attached image as a UGC concept",
    "find_opportunities": "Find low-competition niches or trending opportunities",
    "create_ideas": "Generate a concept, title, description, and launch direction",
    "improve_metadata": "Improve the title/description/tags for an item",
    "check_sales": "Read recorded sales and revenue",
    "check_experiments": "Show experiment results and matched-control evidence",
    "check_visibility": "Show search-visibility coverage and freshness",
    "data_audit": "Show data-quality and integrity audit",
    "help": "Explain what VANTA can do",
    "greeting": "Greet the user and invite the next task",
    "presence": "Confirm the bot is still available",
    "ack": "Acknowledge a short confirmation",
    "cancel": "Cancel the current direction",
    "list_my_items": "List tracked launch items when no item ID is supplied",
    "tags": "Generate description keywords for an item",
    "clarify": "Ask one short clarifying question",
}

COMMAND_ARGS = {
    "inspect_item": ("verdict", "item"),
    "diagnose_item": ("autopsy", "item"),
    "revive_item": ("revive", "item"),
    "find_opportunities": ("opportunities", "family"),
    "create_ideas": ("chain", "concept"),
    "improve_metadata": ("autopsy", "item"),
    "tags": ("tags", "title"),
    "check_sales": ("sales_report", None),
    "check_experiments": ("experiments", None),
    "check_visibility": ("visibility", None),
    "data_audit": ("data_audit", None),
}

INTRO_TEXT = """**Talk to me like a person.**
No command names required.

Try:
• `yo check this item 123456789`
• `i made this, what do you think?` + image
• `find me a niche with low competition`
• `why is this item failing? 123456789`
• `make a better title and description for it`
• `how are my sales doing?`

You can also use the normal `!commands` here or anywhere else.

⚠️ This is a **public thread**; anyone who can view the channel can read it.
Do not share passwords, cookies, or private financial details. Use
**Private (DM)** from the Command Center for sensitive conversations.
"""

PRIVATE_INTRO = """**Private VANTA conversation.**

Talk normally: check items, diagnose failures, find niches, improve listings,
or ask about sales. No command names required. This DM is visible only to you
and the bot.
"""


@dataclass
class ConversationState:
    user_id: int
    results: list = field(default_factory=list)
    last_intent: str | None = None
    last_item_id: int | None = None
    last_concept: str | None = None
    last_family: str | None = None
    item_titles: dict = field(default_factory=dict)
    pending_intent: str | None = None
    messages: list = field(default_factory=list)
    history: list = field(default_factory=list)
    ai_calls: list = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)

    def touch(self):
        self.updated_at = time.time()


class ConversationStore:
    def __init__(self, ttl_seconds=86400):
        self.ttl = ttl_seconds
        self._states = {}

    def get(self, thread_id, user_id=None):
        now = time.time()
        for key, state in list(self._states.items()):
            if now - state.updated_at > self.ttl:
                self._states.pop(key, None)
        state = self._states.get(thread_id)
        if state is None and user_id is not None:
            state = ConversationState(user_id=user_id)
            self._states[thread_id] = state
        return state

    def create(self, thread_id, user_id):
        state = ConversationState(user_id=user_id)
        self._states[thread_id] = state
        return state


STORE = ConversationStore()


def _thread_secret():
    return (os.getenv("VANTA_THREAD_SECRET")
            or os.getenv("TOKEN")
            or "vanta-local-development").encode()


def _thread_token(user_id):
    return hmac.new(_thread_secret(), str(user_id).encode(),
                    hashlib.sha256).hexdigest()[:12]


def thread_name(user_id):
    return f"vanta-{user_id}-{_thread_token(user_id)}"


def parse_thread_name(name):
    match = THREAD_RE.match(name or "")
    if not match:
        return None
    user_id, token = int(match.group(1)), match.group(2).lower()
    if hmac.compare_digest(token, _thread_token(user_id)):
        return user_id
    return None


def thread_user_id(channel):
    if not isinstance(channel, discord.Thread):
        return None
    return parse_thread_name(channel.name or "")


def extract_item_id(text):
    text = text or ""
    match = URL_ID_RE.search(text)
    if match:
        return int(match.group(1))
    match = ITEM_ID_RE.search(text)
    return int(match.group(1)) if match else None


def detect_family(text):
    low = (text or "").lower()
    for family, words in FAMILIES.items():
        if any(re.search(rf"\b{re.escape(w)}\b", low) for w in words):
            return family
    return None


def clean_concept(text, item_id=None):
    s = (text or "").lower()
    if item_id:
        s = s.replace(str(item_id), " ")
    s = URL_ID_RE.sub(" ", s)
    s = ITEM_ID_RE.sub(" ", s)
    s = re.sub(
        r"\b(?:yo|hey|hi|please|pls|can|could|would|you|me|my|i|im|i'm|"
        r"want|need|make|create|give|find|check|look|this|that|the|a|an|"
        r"for|with|and|or|to|of|in|on|item|ugc|please|thanks|thank|"
        r"better|title|description|metadata|tags|ideas?|concept|"
        r"niche|opportunity|opportunities|trending|trend|gap|low|"
        r"competition|revive|fix|improve|diagnose|analyze|analyse|"
        r"autopsy|verdict|deep|deeper|more|same|now|do|what|why|how|"
        r"is|are|doing|does|it|about|some|new|current|change|changed|"
        r"edit|update|redo|add|write|existing)\b",
        " ", s,
    )
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:120] or None


def _state_with_last_item(state, item_id):
    if item_id:
        return item_id
    return state.last_item_id if state else None


def classify_intent(text, has_attachment=False, state=None, use_ai=False):
    """Return an allow-listed intent dict. Deterministic first; AI only fallback."""
    low = (text or "").lower().strip()
    item_id = extract_item_id(low)
    family = detect_family(low)
    state = state or ConversationState(user_id=0)

    # Conversational glue before task routing.
    if re.search(
        r"\b(did (you|u) disconnect|are (you|u) there|(you|u) there|"
        r"still there|(you|u) alive|still online|r u there)\b", low
    ):
        return _intent("presence", confidence="high")
    if re.fullmatch(
        r"(hi|hey|hello|yo|sup|wassup|good morning|good evening)[!. ]*", low
    ):
        return _intent("greeting", confidence="high")
    if re.fullmatch(r"(thanks|thank you|ty|ok|okay|cool|nice|great|perfect)[!. ]*", low):
        return _intent("ack", confidence="high")
    if re.match(r"^(cancel|never ?mind|nvm|stop|forget it)\b", low):
        return _intent("cancel", confidence="high")

    # A bare item ID or URL establishes the item immediately.
    if item_id and re.fullmatch(r"(?:https?://\S+|\d{6,20})[.! ]*", low.strip()):
        return _intent("inspect_item", item_id=item_id,
                       concept=state.last_concept, family=family,
                       confidence="high")

    # Follow-ups first.
    ordinal = re.search(
        r"\b(1|2|3|4|5|first|1st|one|second|2nd|two|third|3rd|three|"
        r"fourth|4th|four|fifth|5th|five|the other one)\b", low
    )
    if ordinal and state.results:
        words = {
            "first": 0, "1st": 0, "one": 0, "1": 0,
            "second": 1, "2nd": 1, "two": 1, "the other one": 1, "2": 1,
            "third": 2, "3rd": 2, "three": 2, "3": 2,
            "fourth": 3, "4th": 3, "four": 3, "4": 3,
            "fifth": 4, "5th": 4, "five": 4, "5": 4,
        }
        index = words.get(ordinal.group(1).lower(), 0)
        if index < len(state.results):
            if re.search(r"\b(title|description|metadata|improve|better|rewrite)\b", low):
                intent = "improve_metadata"
            elif re.search(r"\b(why|fail|diagnos|wrong|dead)\b", low):
                intent = "diagnose_item"
            else:
                intent = (state.pending_intent or state.last_intent
                          or "inspect_item")
            return _intent(intent, item_id=state.results[index],
                           concept=state.last_concept, family=state.last_family,
                           confidence="followup")
        return _intent("clarify", question="That number is not in the current list.",
                       confidence="low")
    if ordinal and not state.results:
        return _intent("clarify", question="Which item do you mean? Send the ID or URL.",
                       confidence="low")

    if re.search(r"\b(go deeper|deeper|dig deeper|more detail|explain more)\b", low):
        target = state.last_item_id
        if target:
            return _intent("diagnose_item", item_id=target,
                           concept=state.last_concept, family=state.last_family,
                           confidence="followup")
        return _intent("clarify", question="Send the item ID or URL first.",
                       confidence="low")

    if re.search(r"\b(same for|do the same for|now do|now check|now analyze)\b", low):
        if item_id:
            return _intent(state.last_intent or "inspect_item", item_id=item_id,
                           concept=state.last_concept, family=state.last_family,
                           confidence="followup")
        return _intent("clarify", question="Which item should I use?", confidence="low")

    if (has_attachment and not item_id and re.search(
        r"\b(image|photo|picture|pic|look|check|inspect|think|made|design|render|thumbnail)\b",
        low,
    )):
        return _intent("analyze_image", confidence="high")

    if re.search(r"\b(revive|rebuild|relaunch|bring back|rescue|save this)\b", low):
        target = _state_with_last_item(state, item_id)
        if target:
            return _intent("revive_item", item_id=target,
                           concept=state.last_concept, family=family,
                           confidence="high")
        return _intent("clarify", question="Send the item ID or Roblox URL.",
                       confidence="low")

    if re.search(
        r"\b(autopsy|diagnos|why.*(fail|badly|bad|poorly|flop|dead|underperform|not selling)|"
        r"what.*(wrong|happened)|doing badly|not working)\b", low
    ):
        target = _state_with_last_item(state, item_id)
        if target:
            return _intent("diagnose_item", item_id=target,
                           concept=state.last_concept, family=family,
                           confidence="high")
        return _intent("clarify", question="Send the item ID or Roblox URL.",
                       confidence="low")

    if (state.pending_intent == "tags"
            and re.search(r"\b(name|existing|current|same)\b", low)):
        return _intent("tags", item_id=_state_with_last_item(state, item_id),
                       concept=state.last_concept, family=family,
                       confidence="followup")

    if re.search(r"\b(my|our)\b[^.!?]{0,25}\bitems?\b", low) and not item_id:
        if state.last_item_id and not re.search(r"\bitems\b", low):
            return _intent("inspect_item", item_id=state.last_item_id,
                           concept=state.last_concept, family=family,
                           confidence="followup")
        return _intent("list_my_items", confidence="high")

    if re.search(r"\b(sales?|revenue|robux|earned|income|how much.*made|made.*money)\b", low):
        return _intent("check_sales", confidence="high")

    if re.search(r"\b(experiment|uplift|did it work|applied|ignored|results)\b", low):
        return _intent("check_experiments", confidence="high")

    if re.search(r"\b(visibility|search position|rank(ing)?|showing up)\b", low):
        return _intent("check_visibility", confidence="high")

    if re.search(r"\b(audit|data quality|coverage|integrity)\b", low):
        return _intent("data_audit", confidence="high")

    if re.search(r"\b(sales?|revenue|robux|earned|income|how much.*made|made.*money)\b", low):
        return _intent("check_sales", confidence="high")

    if re.search(r"\b(experiment|uplift|did it work|applied|ignored|results)\b", low):
        return _intent("check_experiments", confidence="high")

    if re.search(r"\b(visibility|search position|rank(ing)?|showing up)\b", low):
        return _intent("check_visibility", confidence="high")

    if re.search(r"\b(audit|data quality|coverage|integrity)\b", low):
        return _intent("data_audit", confidence="high")

    if re.search(
        r"\b(check|chek|chekc|inspect|look at|verdict|keep or kill|how is|"
        r"what do you think|evaluate|review)\b", low
    ):
        target = _state_with_last_item(state, item_id)
        if target:
            return _intent("inspect_item", item_id=target,
                           concept=state.last_concept, family=family,
                           confidence="high")
        return _intent(
            "clarify",
            question="Send the item ID or Roblox URL. I can run a verdict, "
                     "or rebuild the title and description from the item data.",
            confidence="low",
        )

    if re.search(
        r"\b(niche|opportunit|trend|gap|low competition|what.*(create|make|next)|"
        r"find.*(idea|niche|item))\b", low
    ):
        if family:
            return _intent("find_opportunities", family=family, confidence="high")
        return _intent("find_opportunities", confidence="medium")

    if (state.pending_intent == "tags"
            and re.search(r"\b(name|existing|current|same)\b", low)):
        return _intent("tags", item_id=_state_with_last_item(state, item_id),
                       concept=state.last_concept, family=family,
                       confidence="followup")

    if re.search(r"\b(tags?|seo)\b", low):
        target = _state_with_last_item(state, item_id)
        concept = clean_concept(text, item_id)
        if re.search(r"\b(existing|current|same)\b.*\bname\b", low):
            return _intent("tags", item_id=target,
                           concept=state.last_concept, family=family,
                           confidence="high")
        return _intent("tags", item_id=target, concept=concept,
                       family=family, confidence="high")

    if re.search(
        r"\b(ideas?|brainstorm|concept|title|description|metadata|launch|"
        r"make.*better|improve|name)\b", low
    ):
        if re.search(r"\b(title|description|metadata|improve|better)\b", low):
            target = _state_with_last_item(state, item_id)
            if target:
                return _intent("improve_metadata", item_id=target,
                               concept=clean_concept(text, target), family=family,
                               confidence="high")
        concept = clean_concept(text, item_id)
        if concept:
            return _intent("create_ideas", concept=concept,
                           item_id=item_id, family=family, confidence="medium")
        return _intent("clarify", question="Describe the concept or item in a few words.",
                       confidence="low")

    if re.search(r"\b(help|what can you do|commands|how do i)\b", low):
        return _intent("help", confidence="high")

    result = _intent(
        "clarify",
        question="I didn't catch that. Try `check item <ID>`, "
                 "`rename to <theme>`, `find a niche`, `my items`, "
                 "or `how are my sales?`",
        confidence="low",
    )
    result["ai_fallback"] = bool(use_ai)
    return result


def _intent(name, item_id=None, concept=None, family=None,
            confidence="high", question=None):
    return {
        "intent": name if name in INTENTS else "clarify",
        "item_id": item_id,
        "concept": concept,
        "family": family,
        "confidence": confidence,
        "question": question,
    }


def _ai_route(text):
    started = time.time()
    try:
        from gemini_brain import _generate, get_last_usage, is_available
        if not is_available():
            return None
        prompt = f"""Classify the user's Roblox UGC request.
Allowed intents:
- inspect_item
- diagnose_item
- revive_item
- find_opportunities
- create_ideas
- improve_metadata
- check_sales
- check_experiments
- check_visibility
- data_audit
- help
- clarify
Return ONLY JSON:
{{"intent":"...", "item_id": 123 or null, "concept": "short phrase or null", "family": "emote|hair|headwear|face|accessory|clothing|gear|null"}}
Never invent a command or an ID. If unclear, use clarify.
USER: {text[:600]}
"""
        raw = _generate(prompt, json_mode=True, temperature=0.1, max_tokens=250)
        usage = get_last_usage()
        if not raw:
            return None
        import json
        data = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
        name = str(data.get("intent", "")).strip()
        if name not in INTENTS or name == "clarify":
            return _intent("clarify", question="Can you rephrase that in one sentence?",
                           confidence="low")
        item_id = data.get("item_id")
        try:
            item_id = int(item_id) if item_id else None
        except (TypeError, ValueError):
            item_id = None
        concept = clean_concept(str(data.get("concept") or ""))
        family = str(data.get("family") or "").strip().lower() or None
        if family not in FAMILIES:
            family = None
        print(f"[vanta-router] ai fallback chars={len(prompt)} "
              f"usage={usage or {'estimated_input': round(len(prompt)/4)}} "
              f"intent={name} elapsed={time.time()-started:.2f}s", flush=True)
        route = _intent(name, item_id=item_id, concept=concept, family=family,
                        confidence="ai")
        route["usage"] = usage or {"estimated_input": round(len(prompt) / 4)}
        return route
    except Exception as e:
        print(f"[vanta-router] ai fallback failed: {type(e).__name__}: {e}",
              flush=True)
        return None


class ProxyCtx:
    """Minimal context compatible with existing command callbacks."""
    def __init__(self, message):
        self.message = message
        self.channel = message.channel
        self.author = message.author
        self.sent = []

    async def send(self, content=None, **kwargs):
        self.sent.append({
            "content": content or "",
            "embed": kwargs.get("embed"),
            "embeds": kwargs.get("embeds"),
        })
        return await self.channel.send(content=content, **kwargs)

    def typing(self):
        return self.channel.typing()


async def _fetch_my_items():
    def _fetch():
        from bot_core import get_db
        conn = get_db(); cur = conn.cursor()
        try:
            cur.execute("""
                SELECT l.item_id, COALESCE(l.title, i.name),
                       COALESCE(i.favorite_count, l.favs_launch, 0)
                FROM launch_ledger l
                LEFT JOIN items i ON i.id = l.item_id
                ORDER BY l.launched_at DESC NULLS LAST
                LIMIT 8
            """)
            rows = cur.fetchall()
            if not rows:
                names = [x.strip() for x in
                         (os.getenv("MY_GROUP_NAMES") or "").split(",")
                         if x.strip()]
                if names:
                    cur.execute("""
                        SELECT id, name, COALESCE(favorite_count, 0)
                        FROM items WHERE lower(creator_name) = ANY(%s)
                        ORDER BY favorite_count DESC NULLS LAST LIMIT 8
                    """, ([n.lower() for n in names],))
                    rows = cur.fetchall()
            return rows
        finally:
            cur.close(); conn.close()

    try:
        return await asyncio.to_thread(_fetch)
    except Exception as e:
        print(f"[vanta] my items failed: {type(e).__name__}: {e}", flush=True)
        return []


async def _fetch_item_title(item_id):
    def _fetch():
        from bot_core import get_db
        conn = get_db(); cur = conn.cursor()
        try:
            cur.execute("SELECT name FROM items WHERE id = %s", (item_id,))
            row = cur.fetchone()
            return row[0] if row else None
        finally:
            cur.close(); conn.close()

    try:
        return await asyncio.to_thread(_fetch)
    except Exception:
        return None


async def _run_registry(bot, message, route, state):
    intent = route["intent"]
    item_id = route.get("item_id")
    concept = route.get("concept")
    family = route.get("family")

    if intent == "greeting":
        await message.channel.send(
            "Hey — what are we working on? Send an item ID/URL, describe a "
            "concept, or attach an image."
        )
        return
    if intent == "presence":
        await message.channel.send(
            "I'm here. Send an item ID/URL, a concept, or an image and I'll "
            "route it to the right engine."
        )
        return
    if intent == "ack":
        await message.channel.send(
            "Anytime. Send the next item or ask for a follow-up."
        )
        return
    if intent == "cancel":
        state.last_item_id = None
        state.results = []
        await message.channel.send("Stopped. Tell me the next thing you want to do.")
        return
    if intent == "list_my_items":
        rows = await _fetch_my_items()
        if not rows:
            await message.channel.send(
                "I don't have a tracked launch list yet. Send an item ID/URL, "
                "or run `!launch_sync`."
            )
            return
        state.results = [int(r[0]) for r in rows]
        state.item_titles = {int(r[0]): (r[1] or "") for r in rows}
        state.last_intent = "inspect_item"
        state.history.append({"intent": "list_my_items", "at": time.time()})
        lines = ["**Your tracked items:**"]
        for index, (item_id, title, favs) in enumerate(rows, 1):
            lines.append(
                f"**{index}.** `{item_id}` — {(title or '?')[:60]} · {int(favs or 0):,}♥"
            )
        lines.append(
            "\nReply with a number or ID. For a title rewrite, say "
            "`change the title of the first one`."
        )
        await message.channel.send("\n".join(lines)[:1900])
        return

    if intent == "analyze_image":
        name = "analyze_image"
        kwargs = {}
    elif intent == "help":
        await message.channel.send(
            "I can inspect items, diagnose failures, find niches, generate "
            "titles/descriptions, check sales, and show experiment evidence.\n"
            "Try: `check item 123456789`, `find a low-competition niche`, "
            "or attach an image and say `what do you think?`."
        )
        return
    elif intent in COMMAND_ARGS:
        name, arg_kind = COMMAND_ARGS[intent]
        kwargs = {}
        if intent == "find_opportunities" and family:
            name, arg_kind = "converge", "family"
        if intent == "improve_metadata" and not item_id:
            if concept:
                name, arg_kind = "chain", "concept"
            else:
                await message.channel.send(
                    "Send the item ID or describe the listing you want improved."
                )
                return
        if arg_kind == "item":
            if not item_id:
                await message.channel.send("Send the item ID or Roblox URL first.")
                return
            kwargs = {"item_id": item_id}
        elif arg_kind == "concept":
            if not concept:
                await message.channel.send("Describe the concept in a few words.")
                return
            kwargs = {"args": concept}
        elif arg_kind == "title":
            title = concept or (state.item_titles.get(item_id)
                                if item_id else None)
            if not title and item_id:
                title = await _fetch_item_title(item_id)
            if not title:
                rows = await _fetch_my_items()
                if rows:
                    state.results = [int(r[0]) for r in rows]
                    state.item_titles = {int(r[0]): (r[1] or "") for r in rows}
                    state.pending_intent = "tags"
                    lines = ["**Which item?**"]
                    for i, (iid, name, favs) in enumerate(rows, 1):
                        lines.append(f"**{i}.** `{iid}` — {(name or '?')[:60]}")
                    lines.append("\nReply with a number.")
                    await message.channel.send("\n".join(lines)[:1900])
                else:
                    await message.channel.send(
                        "Send the item name you want tags for."
                    )
                return
            kwargs = {"args": title}
        elif arg_kind == "family":
            if family:
                kwargs = {"family": family}
    else:
        await message.channel.send("I didn't catch that. Try naming the task.")
        return

    command = bot.get_command(name)
    if not command:
        await message.channel.send(f"That engine is unavailable right now (`{name}`).")
        return

    label = {
        "inspect_item": "Checking the item",
        "diagnose_item": "Running a full diagnosis",
        "revive_item": "Building a revival plan",
        "find_opportunities": "Scanning for open niches",
        "create_ideas": "Building a launch direction",
        "improve_metadata": "Rebuilding the listing",
        "check_sales": "Reading recorded sales",
        "check_experiments": "Reading experiment evidence",
        "check_visibility": "Reading visibility coverage",
        "data_audit": "Running the data audit",
        "analyze_image": "Analyzing the image",
    }.get(intent, "Working")
    await message.channel.send(f"_{label}…_")

    proxy = ProxyCtx(message)
    started = time.time()
    try:
        await asyncio.wait_for(
            command.callback(proxy, **kwargs), timeout=300
        )
    except asyncio.TimeoutError:
        await message.channel.send(
            "_That engine took too long. The legacy command still works: "
            f"`!{name}`._"
        )
        return
    except Exception as e:
        print(f"[vanta-router] {name} failed: {type(e).__name__}: {e}", flush=True)
        await message.channel.send(
            f"_That engine failed (`{type(e).__name__}`). Try `!{name}`._"
        )
        return

    captured = []
    for item in proxy.sent:
        captured.append(item.get("content") or "")
        embed = item.get("embed")
        if embed:
            captured.extend([embed.title or "", embed.description or ""])
            for field in embed.fields:
                captured.extend([field.name, field.value])
    ids = []
    for text in captured:
        ids.extend(int(x) for x in ITEM_ID_RE.findall(text or ""))
    if ids:
        state.results = list(dict.fromkeys(ids))[:8]
    state.last_intent = intent
    state.last_item_id = item_id or (state.results[0] if state.results else None)
    state.last_concept = concept or state.last_concept
    state.last_family = family or state.last_family
    state.pending_intent = None
    state.history.append({"intent": intent, "item_id": item_id,
                          "concept": concept, "at": time.time()})
    state.history = state.history[-8:]
    state.touch()
    print(f"[vanta-router] intent={intent} cmd={name} "
          f"elapsed={time.time()-started:.2f}s", flush=True)


ITEM_ACTIONS = {"inspect_item", "diagnose_item", "revive_item",
                "improve_metadata"}
CONCEPT_ACTIONS = {"create_ideas"}


def _planner_prompt(text, has_attachment, state):
    last_title = state.item_titles.get(state.last_item_id, "")
    candidates = [
        {"id": i, "name": state.item_titles.get(i, "")}
        for i in (state.results or [])[:6]
    ]
    recent = [m for m in state.messages[-6:] if m]
    return f"""You are the intent planner for a Roblox UGC assistant.
The user speaks casually, may use slang, typos, incomplete sentences, or follow-ups.
Choose exactly ONE allowed action and extract arguments.

ALLOWED ACTIONS
- inspect_item: check/verdict/keep-or-kill/performance of one existing item
- diagnose_item: why an item is failing or underperforming
- revive_item: revive/rebuild/relaunch an item
- find_opportunities: niches, trends, gaps, what to create next
- create_ideas: new concept, title ideas, brainstorm for a new item
- improve_metadata: change/improve title, description, or listing of an item
- tags: keywords/tags/SEO for an item (or the user's existing item name)
- analyze_image: attached image critique
- check_sales: recorded sales/revenue
- check_experiments: experiment results/uplift
- check_visibility: search visibility coverage
- data_audit: data quality/integrity
- help: explain capabilities
- clarify: ask one short question when a required target is unclear

CAPABILITIES BEHIND THESE ACTIONS (choose the closest action; never output a
command name as the action)
- inspect_item -> verdict on an item (keep/rename/kill)
- diagnose_item -> autopsy: why it failed, what to change
- revive_item -> full relaunch plan for a dead item
- improve_metadata -> rebuild an existing listing's title/description
- create_ideas -> chain/brainstorm: new concept, verified titles, launch plan
- find_opportunities -> niches, gaps, rising keywords, what to make next
- tags -> keyword ideas for a name/item
- analyze_image -> attached image feedback
- check_sales -> recorded sales, revenue, per-item sales
- check_experiments -> applied/ignored advice, measured outcomes
- check_visibility -> search visibility coverage
- data_audit -> data quality and coverage
- help -> what the bot can do, command names, how to use it
If the user names a specific command (xray, playbook, whale, revsim, etc.),
map it to the closest action above and let the system run it; do not invent.

RULES
- Resolve "it", "this", "that", "my item", "the listing" to last_item when available.
- Resolve "the second one"/"number 2"/"that one" from candidates.
- Inherit last_concept when the user says "same", "again", "that", or omits the theme but clearly means it.
- Never invent an item ID or a command. Only use IDs present in context or explicit in the message.
- If the user asks to use their existing/current item name, use last_item.
- If the action needs an item and none is known, use clarify.
- If the action needs a concept and none is given or inherited, use clarify.
- A rename/retitle/rebrand toward a theme is create_ideas with that theme — never diagnose_item for a rename.
- "why is it dead / what went wrong / fix it" about an item is diagnose_item, not create_ideas.
- Tags/SEO/keywords requests are tags; use last_item when the user implies their own item.
- Small talk ("thanks", "lol", "ok") is ack; capability questions are help. Do not invent work for small talk.
- Prefer the user's wording for concept; do not translate or embellish it.
- For tags with no known item, item_id may be null; the system will list their items.
- Return JSON ONLY, no markdown.

EXAMPLES
"rename viral russian" -> {"action":"create_ideas","concept":"viral russian"}
"call it russian dance instead" -> {"action":"create_ideas","concept":"russian dance"}
"make my listing cuter" -> {"action":"improve_metadata"} (last_item)
"why is it flopping" -> {"action":"diagnose_item"} (last_item)
"what about the first one" -> {"action":"inspect_item"} (candidates[0])
"same but for hair" -> create_ideas with last_concept + family hair
"how are sales" -> check_sales
"thanks" -> ack

CONTEXT
last_item: {state.last_item_id} ({last_title})
last_concept: {state.last_concept}
last_intent: {state.last_intent}
candidates: {candidates}
pending_action: {state.pending_intent}
recent_user_messages: {recent}
has_attachment: {has_attachment}

JSON SCHEMA
{{"action": "one_allowed_action", "item_id": 123 or null,
  "concept": "short phrase or null", "family": "emote|hair|headwear|face|accessory|clothing|gear|null",
  "confidence": 0.0, "clarify": "one short question or null"}}

USER MESSAGE
{text[:800]}
"""


def _validate_plan(plan, state, has_attachment):
    if not isinstance(plan, dict):
        return None
    action = str(plan.get("action") or "").strip()
    if action == "clarify":
        question = str(plan.get("clarify") or "").strip()
        return _intent("clarify", confidence="ai",
                       question=(question or "Can you tell me a bit more?")[:200])
    if action not in INTENTS:
        return None
    item_id = plan.get("item_id")
    try:
        item_id = int(item_id) if item_id else None
    except (TypeError, ValueError):
        item_id = None
    concept = clean_concept(str(plan.get("concept") or ""))
    family = str(plan.get("family") or "").strip().lower() or None
    if family not in FAMILIES:
        family = None
    if action in CONCEPT_ACTIONS and not concept:
        concept = state.last_concept
    if not family:
        family = state.last_family
    confidence = plan.get("confidence")
    try:
        confidence = float(confidence) if confidence is not None else 0.5
    except (TypeError, ValueError):
        confidence = 0.5

    if action in ITEM_ACTIONS:
        item_id = item_id or state.last_item_id
        if not item_id:
            return _intent("clarify", question="Which item? Send the ID or URL.",
                           confidence="low")
    if action == "tags":
        item_id = item_id or state.last_item_id
    if action in CONCEPT_ACTIONS and not concept:
        return _intent("clarify",
                       question="Describe the concept or theme in a few words.",
                       confidence="low")
    if action == "improve_metadata" and not item_id and not concept:
        return _intent("clarify",
                       question="Send the item ID or describe the listing you want improved.",
                       confidence="low")
    if action == "analyze_image" and not has_attachment:
        return _intent("clarify",
                       question="Attach the image you want me to analyze.",
                       confidence="low")
    if confidence < 0.40 and not item_id and not concept:
        return _intent("clarify", question="Can you say that another way?",
                       confidence="low")
    return _intent(action, item_id=item_id, concept=concept, family=family,
                   confidence="ai")


def _planner_ai(text, has_attachment, state):
    started = time.time()
    try:
        from gemini_brain import _generate, get_last_usage, is_available
        if not is_available():
            return None
        prompt = _planner_prompt(text, has_attachment, state)
        raw = _generate(prompt, json_mode=True, temperature=0.0, max_tokens=400)
        usage = get_last_usage()
        if not raw:
            return None
        data = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
        print(f"[vanta-planner] usage={usage or {'estimated_input': round(len(prompt)/4)}} "
              f"elapsed={time.time()-started:.2f}s", flush=True)
        return data
    except Exception as e:
        print(f"[vanta-planner] failed: {type(e).__name__}: {e}", flush=True)
        return None


def _is_selection(text):
    return bool(SELECTION_RE.fullmatch((text or "").strip()))


RENAME_RE = re.compile(
    r"\b(?:re-?name|retitle|re-?title|rebrand|re-?brand|"
    r"change\s+(?:its\s+|the\s+)?name)\b(.*)$", re.I)

FILLER_RE = re.compile(
    r"^(?:alr|alright|ok|okay|so|hey|yo|hi|hello|um|uh|pls|please|"
    r"can you|can u|could you|would you|i wanna|i want to|i want|"
    r"i need to|i need|need to|let'?s|help me|i'd like to|id like to|"
    r"gonna|quick question|question)[\s,]+", re.I)

REPLACE_RE = re.compile(
    r"^(?:to|into|as|it|this|that|my item|the item|an item|the listing|"
    r"my listing|please|pls)\b[\s,]*", re.I)


def _strip_fillers(text):
    """Drop conversational lead-ins so `alr i wanna rename x` behaves like
    `rename x`."""
    cleaned = (text or "").strip()
    while True:
        nxt = FILLER_RE.sub("", cleaned, count=1).strip()
        if nxt == cleaned:
            break
        cleaned = nxt
    return cleaned or (text or "").strip()


def _rename_concept(text):
    """Extract the new theme from any rename phrasing."""
    m = RENAME_RE.search((text or "").strip())
    if not m:
        return None
    rest = m.group(1).strip(" ,.!?-")
    while True:
        nxt = REPLACE_RE.sub("", rest, count=1).strip(" ,.!?-")
        if nxt == rest:
            break
        rest = nxt
    return rest or None


async def plan_message(text, has_attachment, state):
    # Drop conversational lead-ins ("alr", "i wanna", "can you") first.
    text = _strip_fillers(text)
    # Deterministic fast path for bare IDs/URLs and small talk.
    fast = classify_intent(text, has_attachment=has_attachment, state=state,
                          use_ai=False)
    if fast["intent"] in ("greeting", "presence", "ack", "cancel", "help"):
        return fast
    if fast["intent"] in ("check_sales", "check_experiments",
                          "check_visibility", "data_audit", "list_my_items"):
        return fast
    if extract_item_id(text) and re.fullmatch(
        r"(?:https?://\S+|\d{6,20})[.! ]*", (text or "").strip().lower()
    ):
        return fast
    if (text or "").strip().startswith("!"):
        return fast
    # "rename to <theme>" is a new-concept request, never a diagnosis.
    if RENAME_RE.search((text or "").strip()):
        concept = _rename_concept(text)
        target = state.last_item_id
        if concept:
            pick = re.match(
                r"^(?:item\s+)?(\d{6,20}|[1-5]|first|second|third|fourth|fifth)"
                r"\s*(?:to|into|as)?\s*(.+)$", concept, re.I)
            if pick:
                token, concept = pick.group(1).lower(), pick.group(2).strip()
                index = {"1": 0, "first": 0, "2": 1, "second": 1, "3": 2,
                         "third": 2, "4": 3, "fourth": 3, "5": 4,
                         "fifth": 4}.get(token)
                if index is not None and index < len(state.results or []):
                    target = state.results[index]
                elif token.isdigit() and len(token) >= 6:
                    target = int(token)
        if concept:
            state.last_concept = concept
            if fast.get("family"):
                state.last_family = fast["family"]
            return _intent("create_ideas", concept=concept,
                           family=fast.get("family"),
                           item_id=target, confidence="high")
        if state.last_item_id:
            return _intent("improve_metadata", item_id=state.last_item_id,
                           confidence="high")
        return _intent("list_my_items", confidence="high")
    # Ordinals/numbers are already resolved against pending context.
    if _is_selection(text) and fast["intent"] != "clarify":
        return fast

    now = time.time()
    state.ai_calls = [t for t in state.ai_calls if now - t < 3600]
    if len(state.ai_calls) < 20:
        try:
            plan = await asyncio.wait_for(
                asyncio.to_thread(_planner_ai, text, has_attachment, state),
                timeout=30,
            )
        except asyncio.TimeoutError:
            print("[vanta-planner] timeout", flush=True)
            plan = None
        route = _validate_plan(plan, state, has_attachment)
        if route:
            if route.get("concept"):
                state.last_concept = route["concept"]
            if route.get("family"):
                state.last_family = route["family"]
            state.ai_calls.append(time.time())
            state.ai_calls = [t for t in state.ai_calls
                              if time.time() - t < 3600]
            return route
    return fast


async def handle_message(bot, message, state):
    text = (message.content or "").strip()
    has_attachment = bool(message.attachments)
    if not text and not has_attachment:
        await message.channel.send("Send a message, an item ID, or an image.")
        return
    state.messages.append(text[:400])
    state.messages = state.messages[-6:]
    route = await plan_message(text, has_attachment, state)
    if route["intent"] == "clarify":
        await message.channel.send(
            route.get("question") or
            "I didn't catch that. Try `check item <ID>`, `rename to <theme>`, "
            "`find a niche`, `my items`, or `how are my sales?`")
        return
    await _run_registry(bot, message, route, state)


async def maybe_handle(bot, message):
    if isinstance(message.channel, discord.DMChannel):
        if message.author.bot:
            return True
        state = STORE.get(message.channel.id, message.author.id)
        if state is None:
            return False
        if (message.content or "").startswith("!"):
            return False
        try:
            await handle_message(bot, message, state)
        except Exception as e:
            print(f"[vanta] DM handling failed: {type(e).__name__}: {e}",
                  flush=True)
        return True

    expected_user = thread_user_id(message.channel)
    if expected_user is None:
        return False
    if message.author.bot or message.author.id != expected_user:
        return True
    if (message.content or "").startswith("!"):
        return False
    state = STORE.get(message.channel.id, expected_user)
    if state is not None and state.user_id != expected_user:
        print("[vanta] thread ownership mismatch — ignored", flush=True)
        return True
    try:
        await handle_message(bot, message, state)
    except Exception as e:
        print(f"[vanta] message handling failed: {type(e).__name__}: {e}", flush=True)
        try:
            await message.channel.send("_Something went wrong. Try `!help`._")
        except Exception:
            pass
    return True


class _SyntheticMessage:
    def __init__(self, channel, author, content):
        self.channel = channel
        self.author = author
        self.content = content
        self.attachments = []
        self.id = 0
        self.created_at = None


async def start_conversation(interaction, bot, starter=None):
    channel = interaction.channel
    if not isinstance(channel, discord.TextChannel):
        return await interaction.response.send_message(
            "Start me from a normal text channel so I can create your thread.",
            ephemeral=True,
        )
    try:
        thread = await channel.create_thread(
            name=thread_name(interaction.user.id),
            type=discord.ChannelType.public_thread,
            auto_archive_duration=1440,
            reason="VANTA conversation",
        )
    except Exception as e:
        print(f"[vanta] thread create failed: {type(e).__name__}: {e}", flush=True)
        return await interaction.response.send_message(
            "I need **Create Public Threads** permission here.",
            ephemeral=True,
        )
    STORE.create(thread.id, interaction.user.id)
    await thread.send(INTRO_TEXT)
    await interaction.response.send_message(
        f"Your conversation is open: {thread.mention}", ephemeral=True
    )
    if starter:
        state = STORE.get(thread.id, interaction.user.id)
        await handle_message(
            bot, _SyntheticMessage(thread, interaction.user, starter), state
        )


async def start_dm_conversation(interaction, bot):
    try:
        dm = await interaction.user.create_dm()
    except Exception as e:
        print(f"[vanta] DM create failed: {type(e).__name__}: {e}", flush=True)
        return await interaction.response.send_message(
            "I can't open a DM with you. Check your privacy settings.",
            ephemeral=True,
        )
    STORE.create(dm.id, interaction.user.id)
    await dm.send(PRIVATE_INTRO)
    await interaction.response.send_message(
        "🔒 Private conversation opened in your DMs.", ephemeral=True
    )
