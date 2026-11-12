"""Pure, bounded conversational intent detection for VANTA 2.0.

This module cannot execute commands, access the database, or make AI calls.
"""
import re

_GREETING = re.compile(
    r"^(?:(?:hey+|hi+|hello+|yo+|sup|wassup|alr|alright|ok(?:ay)?|"
    r"vanta|pls|please)\b[\s,.!?:-]*)+", re.I,
)

_RULES = (
    ("privacy_clear", re.compile(
        r"(?:please\s+)?(?:forget|clear|erase|delete|wipe|reset)\s+"
        r"(?:(?:this|our|my|the)\s+)?(?:chat|conversation|chat history|"
        r"conversation history|memory|context|everything we discussed)"
        r"(?:\s+(?:please|now|for me))?[.!?]*", re.I)),
    ("privacy_off", re.compile(
        r"(?:please\s+)?(?:stop remembering(?:\s+(?:this|our|my)\s+"
        r"(?:chat|conversation|messages))?|don'?t remember (?:our|my|this)\s+"
        r"(?:chats?|conversations?|messages?)|turn off (?:conversation\s+)?memory|"
        r"disable (?:conversation\s+)?memory)[.!?]*", re.I)),
    ("privacy_on", re.compile(
        r"(?:please\s+)?(?:start remembering(?:\s+(?:our|my|this)\s+"
        r"(?:chat|conversation|messages))?|turn on (?:conversation\s+)?memory|"
        r"enable (?:conversation\s+)?memory|remember our chats again)[.!?]*", re.I)),
    ("privacy_status", re.compile(
        r"(?:what do you remember(?: about (?:me|our chat|this conversation))?|"
        r"is (?:your |conversation )?memory (?:on|off|enabled|disabled)|"
        r"do you remember (?:our chat|what we discussed))[.!?]*", re.I)),
    ("conversation_recall", re.compile(
        r"(?:what were we (?:talking|chatting) about|where were we|"
        r"can (?:you|u) remind me what we (?:discussed|worked on)|"
        r"remember (?:that|the|our) (?:background|item|idea|concept)"
        r"(?: we (?:discussed|talked about))?)[.!?]*", re.I)),
    ("conversation_help", re.compile(
        r"(?:(?:i\s+)?(?:need|want|wanna|wanted|would like)\s+"
        r"(?:a\s+)?(?:something|smth|sth|sumthin|help|some help|a hand|"
        r"to ask (?:you|u) something)|"
        r"(?:can|could|will|would)\s+(?:you|u)\s+help(?:\s+me)?|"
        r"help me(?:\s+please)?|i (?:have|got) (?:a|one|some) questions?|"
        r"got a (?:question|minute)|i don'?t know (?:what to do|where to start)|"
        r"not sure (?:what to do|where to start))[.!?]*", re.I)),
    ("conversation_fatigue", re.compile(
        r"(?:(?:i(?:'m| am)|im|i feel)\s+(?:so\s+|really\s+|very\s+)?"
        r"(?:tired|exhausted|stressed|frustrated|lost|confused|overwhelmed|"
        r"fed up|burned out|burnt out)|this is exhausting|"
        r"i can'?t be bothered|i give up)[.!?]*", re.I)),
    ("conversation_casual", re.compile(
        r"(?:how (?:are|r) (?:you|u)|how'?s it going|what'?s up|"
        r"whats good|you good|u good|can we (?:just )?(?:chat|talk)|"
        r"lets (?:just )?(?:chat|talk)|i just want to talk|"
        r"lol+|lmao+|haha+|hehe+|tell me a joke|how have you been)[.!?]*", re.I)),
)

# Capability questions are not action requests; never run marketplace scans here.
_CAPABILITY = re.compile(
    r"(?:do (?:you|u|ya) (?:do|support|understand|handle|work with)|"
    r"can (?:you|u) (?:do|support|handle|work with)|"
    r"are (?:you|u) (?:able to|good at|familiar with)|"
    r"what (?:can you|can u) do (?:with|for))\s+"
    r"(?:roblox\s+|ugc\s+|avatar\s+|my\s+)?"
    r"(backgrounds?|backdrops?|emotes?|dances?|hats?|beanies?|accessories|titles?|descriptions?)"
    r"(?:\s+(?:ugc|stuff|items?))?[.!?]*", re.I,
)

_FOCUS = re.compile(
    r"(?:(?:my|a|the|new|some)\s+)?"
    r"(?:backgrounds?|backdrops?|emotes?|dances?|hats?|beanies?|"
    r"accessories|my items|titles?|descriptions?|ideas?)[.!?]*", re.I,
)


def strip_greeting(text):
    value = (text or "").strip()
    for _ in range(3):
        stripped = _GREETING.sub("", value, count=1).strip()
        if stripped == value:
            break
        value = stripped
    return value.strip(" ,")


def classify_social(text, state=None):
    """Return a social intent or None; leave real tasks to existing router."""
    core = strip_greeting(text)
    if not core:
        return None
    if _CAPABILITY.fullmatch(core):
        return "conversation_capabilities"
    for intent, pattern in _RULES:
        if pattern.fullmatch(core):
            return intent
    pending = getattr(state, "pending_action", None) or {}
    if pending.get("intent") == "open_help" and _FOCUS.fullmatch(core):
        return "conversation_focus"
    return None


def social_reply(kind, state, text=""):
    """Short replies only; never imply observed sales or unseen marketplace data."""
    item_id = getattr(state, "last_item_id", None)
    family = getattr(state, "last_family", None)
    concept = getattr(state, "last_concept", None)
    title = (getattr(state, "item_titles", None) or {}).get(item_id)
    if kind == "conversation_capabilities":
        matched = _CAPABILITY.fullmatch(strip_greeting(text))
        focus = matched.group(1).lower() if matched else "UGC"
        if focus.startswith(("background", "backdrop")):
            return ("Yes! I support Roblox Avatar Backgrounds (AssetType 92). "
                    "I can analyze a design image, help with titles and descriptions, "
                    "and research background opportunities when you ask. "
                    "What would you like to do with your background?")
        return ("Yes, I can help with " + focus[:48] +
                ": concept ideas, listing improvements, and market research "
                "where category data is available. What do you need?")
    if kind == "conversation_help":
        return ("Of course. What's on your mind? Tell me in your own words. "
                "I can help with backgrounds, titles, items, sales or UGC ideas.")
    if kind == "conversation_focus":
        focus = strip_greeting(text).lower().strip(".!?")
        if "background" in focus or "backdrop" in focus:
            focus = "backgrounds"
            state.last_family = "backgrounds"
        elif "emote" in focus or "dance" in focus:
            state.last_family = "emote"
        return ("Got it: " + focus[:80] +
                ". Do you want ideas, titles, design feedback, or research?")
    if kind == "conversation_recall":
        details = []
        if title:
            details.append("item " + title[:80])
        elif item_id:
            details.append("item #" + str(item_id))
        if family:
            details.append("category " + family[:40])
        if concept:
            details.append("concept " + str(concept)[:80])
        if not details:
            return ("I don't have an active item or concept in this conversation "
                    "right now. Tell me what we were working on.")
        return "Current context: " + ", ".join(details) + ". What should we do next?"
    if kind == "conversation_fatigue":
        return ("We can keep it simple. Tell me the one thing you need next. "
                "No command names required.")
    if kind == "conversation_casual":
        if "joke" in text.lower():
            return "Why did the Roblox hat lose its job? It couldn't stay on top of things."
        return "Hey! I'm here. What do you feel like talking about?"
    return "Tell me what you need."
