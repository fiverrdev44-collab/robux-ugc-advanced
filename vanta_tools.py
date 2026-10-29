"""vanta_tools.py — single source of truth for the tool directory.

Descriptions are pulled from the registered commands at runtime. This file only
groups command names and supplies examples/input hints.
"""

TOOL_GROUPS = {
    "Strategy & listings": [
        "chain", "converge", "converge_debug", "verdict", "autopsy",
        "revive", "brainstorm", "creative", "creative_raw", "desc_forge",
        "tags", "playbook", "path", "guide", "consult",
    ],
    "Market intelligence": [
        "opportunities", "rising_gaps", "xray", "patterns", "failures",
        "early", "momentum", "momentum_debug", "predict", "oracle",
        "nextwave", "gap", "classic", "emote", "emote_status", "analyze",
        "desc_analyze", "opportunity", "trends", "velocity", "track",
        "watchlist", "history", "scan_status",
    ],
    "Sales & revenue": [
        "sales_report", "sales_for", "sales_backfill", "sales_post_now",
        "sales_probe", "sales_debug", "sales_scan", "sales_keywords",
        "revsim", "group_metrics", "cookie_check", "whales",
        "golden_hour", "meta_sniper", "vacuum", "stealth",
    ],
    "Launch & experiments": [
        "launch", "launch_sync", "ledger_sync", "hitrate", "experiments",
        "applied", "ignored", "data_audit", "visibility",
        "visibility_seed", "visibility_run",
    ],
    "Creators & operations": [
        "verified_scan", "creator_brain", "scan_run", "enrich_run",
        "snapshot_now", "suggest_probe", "suggest_run", "train", "dbtest",
        "logs", "version", "bot_update", "selftest", "selftest_db",
    ],
}

EXAMPLES = {
    "chain": "!chain hip sway dance",
    "converge": "!converge emotes",
    "verdict": "!verdict 121930221694467",
    "autopsy": "!autopsy 121930221694467",
    "revive": "!revive 121930221694467",
    "revsim": "!revsim 115 1500 moderate",
    "sales_report": "!sales_report 30",
    "experiments": "!experiments",
    "data_audit": "!data_audit",
    "visibility": "!visibility",
    "applied": "!applied last",
    "ignored": "!ignored last",
    "launch": "!launch 121930221694467",
    "tags": "!tags Hip Sway Dance Emote",
    "desc_forge": "!desc_forge hip sway",
    "xray": "!xray hip sway",
    "predict": "!predict kawaii aura emote",
    "oracle": "!oracle hip sway",
    "track": "!track 121930221694467",
}

INPUT = {
    "chain": "concept phrase",
    "converge": "family (optional)",
    "verdict": "item ID",
    "autopsy": "item ID",
    "revive": "item ID",
    "track": "item ID",
    "launch": "item ID",
    "sales_for": "item name",
    "revsim": "price, day-1 favorites, promo level",
    "oracle": "keyword",
    "analyze": "keyword",
    "opportunity": "keyword",
    "xray": "niche",
    "tags": "item name",
    "desc_forge": "keyword",
    "predict": "idea",
    "applied": "experiment ID or `last`",
    "ignored": "experiment ID or `last`",
    "visibility_seed": "query count",
    "visibility_run": "query count",
    "enrich_run": "batch count",
    "scan_run": "no arguments",
    "suggest_run": "no arguments",
    "logs": "line count",
    "group_metrics": "group ID",
    "sales_report": "days (optional)",
}

LIMITS = {
    "revsim": "Prior unless enough ledger D30 outcomes exist.",
    "experiments": "Matched controls are observational; <5 controls is exploratory.",
    "autopsy": "Live checks sample up to 300 results, not the full catalog.",
    "visibility": "Observed catalog-API results, not a hidden ranking score.",
    "enrich_run": "Owner-only; requires server cookie.",
    "scan_run": "Owner-only.",
    "suggest_run": "Owner-only.",
    "selftest": "Owner-only; internal audit.",
    "bot_update": "Owner-only; restarts the bot.",
    "data_audit": "Read-only; never deletes ambiguous rows.",
}


def all_names():
    return [name for names in TOOL_GROUPS.values() for name in names]


def validate_tool_groups(available_names):
    available = set(available_names or [])
    missing = sorted({name for name in all_names() if name not in available})
    duplicates = sorted({
        name for name in all_names() if all_names().count(name) > 1
    })
    return {"missing": missing, "duplicates": duplicates}


def directory_entries(bot):
    entries = []
    for group, names in TOOL_GROUPS.items():
        for name in names:
            command = bot.get_command(name)
            if not command:
                continue
            help_text = (command.help or "").strip().splitlines()
            summary = help_text[0] if help_text else "Registered command."
            entries.append({
                "group": group,
                "name": name,
                "summary": summary[:160],
                "input": INPUT.get(name, "see command help"),
                "example": EXAMPLES.get(name, f"!{name}"),
                "limit": LIMITS.get(name),
            })
    return entries
