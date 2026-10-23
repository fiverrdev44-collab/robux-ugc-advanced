"""
menu.py — VANTA 73 Battleship Control Room.
!start opens the tactical console.

Each button opens its own embed with a themed GIF banner.

GIF SETUP:
  1. Download .gif from giphy.com or tenor.com
  2. Upload to https://catbox.moe (no signup)
  3. Copy URL (ends in .gif)
  4. Paste below in the GIF_* constants
"""
import discord


# ─────────────────────────────────────────────────────────────
# GIF URLs — paste direct .gif links (must end in .gif)
# ─────────────────────────────────────────────────────────────
GIF_MAIN     = "https://i.imgur.com/H0WsJzz.gif"   # Main menu hero banner
GIF_FIRE     = "https://i.imgur.com/2Zu329H.gif"   # Launch new item
GIF_STRIKE   = "https://i.imgur.com/arpiHbp.gif"   # Variant of winner
GIF_INSPECT  = "https://i.imgur.com/mBEDVN0.gif"   # Check live item
GIF_SCAN     = "https://i.imgur.com/xRANWve.gif"   # Find trending niche
GIF_RECON    = "https://i.imgur.com/TaFRZCs.gif"   # Analyze image
GIF_LOAD     = "https://i.imgur.com/pM5i95K.gif"   # Generate tags
GIF_MANUAL   = "https://i.imgur.com/kQsJTZ1.gif"   # Full guide


COLOR_STEALTH = 0x000000


def _gif_ok(url):
    """Check URL looks like a usable direct-image link."""
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    if "REPLACE_ME" in url or "example" in url:
        return False
    return bool(url.lower().endswith((".gif", ".gifv", ".png", ".jpg", ".jpeg", ".webp")))


def _apply_gif(embed, gif_url):
    """Set the embed image if the URL is valid."""
    if _gif_ok(gif_url):
        try:
            embed.set_image(url=gif_url.strip())
        except Exception as e:
            print(f"[menu] GIF embed failed: {e}", flush=True)


# ══════════════════════════════════════════════════════════════════
# EASY MANUAL — sectioned guide
# ══════════════════════════════════════════════════════════════════
MANUAL_SECTIONS = {
    "start": (
        "🛰️ START HERE",
        "**What this bot does:** finds niches, names items, checks the market, "
        "tracks sales, and measures whether your launches actually beat peers.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "**THE LOOP — do this in order**\n"
        "**1.** `!converge emotes` — find a niche\n"
        "**2.** `!meta_sniper <niche>` — find missing words\n"
        "**3.** `!chain \"<concept>\"` — build the item\n"
        "**4.** Upload it to Roblox\n"
        "**5.** `!launch <item_id>` — log it\n"
        "**6.** `!hitrate` — measure after 20 launches\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Open this menu anytime with `!start`.\n"
        "Pick a section from the dropdown below to go deeper.",
    ),
    "buttons": (
        "🎛️ EVERY BUTTON",
        "**🚀 FIRE — Launch New Item**\n`!chain <concept>` → full launch kit\n"
        "**⭐ STRIKE — Variant of Winner**\n`!chain variant <id> <theme>` → clone a winner\n"
        "**🔧 INSPECT — Check Live Item**\n`!verdict <id>` → KEEP / RENAME / KILL\n"
        "**📡 SCAN — Find Trending Niche**\n`!converge <family>` e.g. `emotes`, `hair`, `face`, `tops`\n"
        "**🖼️ RECON — Analyze Idea**\n`!brainstorm <description>` (image vision is not enabled)\n"
        "**🏷️ LOAD — Generate Tags**\n`!tags <item name>` → 45 tags\n"
        "**🐋 WHALE — Studio Radar**\n`!whales [studio]` → top studios' drops\n"
        "**🎯 VACUUM — Search Sniper**\n`!vacuum` → low-supply phrases\n"
        "**📈 REVSIM — Revenue Forecast**\n`!revsim <price> [favs] [promo]`\n"
        "**⚡ VELOCITY — 48h Radar**\n`!golden_hour`\n"
        "**ℹ️ MANUAL — Full Guide**\nthis menu",
    ),
    "niche": (
        "📡 FIND A NICHE",
        "**`!converge emotes`**\n"
        "Ranks niches by demand, velocity, supply, freshness and competition.\n"
        "Look for **🔥 SNIPE ZONE** and **low supply**.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "**`!gap anime`** — golden / sweet / saturated gaps\n"
        "**`!early 7`** — items rising fast this week\n"
        "**`!opportunities`** — daily ranked feed\n"
        "**`!rising_gaps`** — emerging keywords\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "**How to read:** high score + low supply = good entry.\n"
        "High supply + old items = crowded; skip it.",
    ),
    "naming": (
        "🏷️ NAME & DESCRIBE",
        "**`!chain \"kawaii aura emote\"`**\n"
        "Returns: champion title, backup title, description, 45 tags, price, "
        "and a final **DO THIS** block.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "**`!tags <name>`** — 45 sales-weighted tags\n"
        "**`!playbook naming`** — naming rules\n"
        "**`!playbook pricing`** — pricing rules\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "**Rules:** 3–5 words, one aesthetic modifier, no keyword stuffing, "
        "include the item type. Never say *limited* or *free* unless true.",
    ),
    "market": (
        "🔬 CHECK THE MARKET",
        "**`!xray`** — full market dashboard\n"
        "**`!patterns emotes`** — words that lift favorites\n"
        "**`!failures emotes`** — words linked to flops\n"
        "**`!trends`** — top words across titles\n"
        "**`!momentum`** — keyword velocity\n"
        "**`!oracle anime`** — trend forecast\n"
        "**`!predict <idea>`** — success probability\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Use these to confirm a niche before building.",
    ),
    "item": (
        "🔧 CHECK YOUR ITEM",
        "**`!verdict <id>`** — after 14 days\n"
        "Returns: 🔥 DOUBLE_DOWN · ✅ KEEP · 🔧 RENAME · 🪦 KILL · ⏳ TOO_NEW\n"
        "**`!autopsy <id>`** — why it failed + pivot plan\n"
        "**`!sales_for <name>`** — sales for one item\n"
        "**`!history`** — past verdicts\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "If RENAME → run `!autopsy`, then update the title/description.",
    ),
    "sales": (
        "💰 SALES & MONEY",
        "**`!sales_report 30`** — units, Robux, top items, daily trend\n"
        "**`!sales_post_now`** — post the report now\n"
        "**`!sales_debug`** — why numbers look off (dates, channel)\n"
        "**`!revsim <price> [favs] [promo]`** — 30-day revenue forecast\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Reminder: Roblox keeps ~70%; creators keep ~30%.\n"
        "Revenue in the bot is your **net** creator share.",
    ),
    "learn": (
        "📈 LEARN & IMPROVE",
        "**`!launch <id>`** — log a new launch\n"
        "**`!launch_sync`** — auto-log all your group items\n"
        "**`!ledger_sync`** — fill D1/D7/D30 favorites + sales\n"
        "**`!hitrate 365`** — did your launches beat peers?\n"
        "**`!path`** — your current stage + next milestones\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "The ledger is how the bot learns from **your** results, not generic data.",
    ),
    "rules": (
        "📜 GOLDEN RULES",
        "**1.** More of what works — clone your top 2 items first.\n"
        "**2.** Launch 3–5 items per week, not 30 at once.\n"
        "**3.** One modifier per title. No stuffing.\n"
        "**4.** Never say *limited* or *free* unless true.\n"
        "**5.** Post one TikTok/Short per launch.\n"
        "**6.** Log every launch with `!launch`.\n"
        "**7.** Wait for 20 launches before trusting the hit rate.\n"
        "**8.** Don't sell R$2 items — they signal a cheap catalog.\n"
        "**9.** Don't launch into saturated niches.\n"
        "**10.** Data improves decisions; production and marketing make sales.",
    ),
    "trouble": (
        "🧯 TROUBLESHOOTING",
        "**Command not found** → `!bot_update`, wait 30s\n"
        "**No data / weird numbers** → `!scan_status`, `!dbtest`\n"
        "**`!vacuum` empty** → enrichment still filling favorites\n"
        "**Sales show 0** → `!sales_debug`, then `!sales_backfill`\n"
        "**Bot not certified** → `!selftest`, read the Failed section\n"
        "**Need tactics** → `!playbook <topic>`\n"
        "**Need a roadmap** → `!path`\n"
        "**Need this menu** → `!start`",
    ),
    "certify": (
        "🏅 CERTIFICATION & HELP",
        "**`!selftest`** — full NASA-grade audit + certificate\n"
        "**`!experiments`** — did the advice actually work?\n"
        "**`!playbook`** — every tactic by topic\n"
        "**`!path`** — your stage and next milestones\n"
        "**`!guide`** — interactive consultation\n"
        "**`!start`** — this menu\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "The certificate is an internal audit — it proves the bot is reliable, "
        "not that sales are guaranteed.",
    ),
}


SIMPLE_MANUAL = {
    "beginner": (
        "🟢 START HERE — 5 STEPS",
        "**Do these in order. Ignore everything else.**\n"
        "━━━━━━━━━━━━━━\n"
        "**1. Find what to make**\n"
        "Type: `!converge emotes`\n"
        "Pick one that says **🔥 SNIPE ZONE**.\n\n"
        "**2. Make the name and description**\n"
        "Type: `!chain \"the thing you picked\"`\n"
        "Example: `!chain \"cute cat beanie\"`\n"
        "Copy the **champion name**, **description**, and **tags**.\n\n"
        "**3. Upload it to Roblox**\n"
        "Use the name, description, and tags from step 2.\n\n"
        "**4. Tell the bot**\n"
        "Type: `!launch <item id>`\n"
        "The item id is the number at the end of the item link.\n\n"
        "**5. Check it later**\n"
        "After 14 days, type: `!verdict <item id>`\n"
        "It says: keep it, rename it, or kill it.\n"
        "━━━━━━━━━━━━━━\n"
        "That's the whole bot. Everything else is optional.",
    ),
    "buttons": (
        "🎛️ THE BUTTONS — SIMPLE",
        "**You only need these at first:**\n"
        "🚀 **FIRE** → builds a new item. Type `!chain <idea>`.\n"
        "⭐ **STRIKE** → copies a winner. Type `!chain variant <id> <theme>`.\n"
        "🔧 **INSPECT** → checks an item. Type `!verdict <id>`.\n"
        "ℹ️ **MANUAL** → this guide.\n"
        "━━━━━━━━━━━━━━\n"
        "**Ignore these until you've launched a few items:**\n"
        "📡 SCAN · 🖼️ RECON · 🏷️ LOAD · 🐋 WHALE · 🎯 VACUUM · 📈 REVSIM · ⚡ VELOCITY\n"
        "They are extra tools, not steps.",
    ),
    "find": (
        "📡 STEP 1 — FIND WHAT TO MAKE",
        "**Type:** `!converge emotes`\n"
        "You get a ranked list.\n"
        "━━━━━━━━━━━━━━\n"
        "**Pick one that has:**\n"
        "• a high score\n"
        "• **🔥 SNIPE ZONE**\n"
        "• low supply (not many items)\n"
        "━━━━━━━━━━━━━━\n"
        "**Example:**\n"
        "`!converge emotes`\n"
        "→ `#1 kawaii aura 🔥 SNIPE ZONE`\n"
        "People want it, few items exist. Make that.\n"
        "━━━━━━━━━━━━━━\n"
        "Other families: `hair`, `face`, `neck`, `back`, `waist`, `tops`, `classic`.",
    ),
    "make": (
        "🏷️ STEP 2 — MAKE THE NAME",
        "**Type:** `!chain \"your idea\"`\n"
        "**Example:** `!chain \"cute cat beanie\"`\n"
        "━━━━━━━━━━━━━━\n"
        "You get:\n"
        "• 🥇 **Champion name** — copy this\n"
        "• 📝 **Description** — copy this\n"
        "• 🏷️ **45 tags** — copy these\n"
        "• 💰 **Price** — use this\n"
        "━━━━━━━━━━━━━━\n"
        "**Rules:**\n"
        "• 3–5 words\n"
        "• one style word (kawaii, y2k, gothic)\n"
        "• no keyword spam\n"
        "• never say *limited* or *free* unless true",
    ),
    "upload": (
        "🚀 STEP 3 — PUT IT ON ROBLOX",
        "1. Open the Roblox Creator Dashboard.\n"
        "2. Upload your 3D item.\n"
        "3. Paste the **name**, **description**, and **tags** from `!chain`.\n"
        "4. Set the price the bot gave you.\n"
        "5. Publish it.\n"
        "━━━━━━━━━━━━━━\n"
        "**Then tell the bot:**\n"
        "`!launch <item id>`\n"
        "The item id is the number at the end of the item link.\n"
        "Example: `!launch 92364796546749`\n"
        "━━━━━━━━━━━━━━\n"
        "Why? So the bot can track how it performs.",
    ),
    "check": (
        "🔧 STEP 4 — CHECK HOW IT DID",
        "**Wait 14 days.** Then type:\n"
        "`!verdict <item id>`\n"
        "━━━━━━━━━━━━━━\n"
        "You get one answer:\n"
        "🔥 **DOUBLE_DOWN** → make more like it\n"
        "✅ **KEEP** → leave it alone\n"
        "🔧 **RENAME** → run `!autopsy <id>` first\n"
        "🪦 **KILL** → stop making that type\n"
        "⏳ **TOO_NEW** → wait longer\n"
        "━━━━━━━━━━━━━━\n"
        "**Golden rule:** if it says DOUBLE_DOWN, make 3 variants this week.",
    ),
    "money": (
        "💰 SEE YOUR MONEY",
        "**Type:** `!sales_report 30`\n"
        "Shows: units sold, Robux, top items, daily trend.\n"
        "━━━━━━━━━━━━━━\n"
        "**Remember:** Roblox keeps ~70%. You keep ~30%.\n"
        "The bot shows your **net** share.\n"
        "━━━━━━━━━━━━━━\n"
        "**Type:** `!sales_debug` if a number looks wrong.",
    ),
    "advanced": (
        "🧰 WHEN YOU'RE READY",
        "**Only after you've launched a few items:**\n"
        "`!vacuum` — phrases with almost no items\n"
        "`!meta_sniper <niche>` — words competitors miss\n"
        "`!sales_keywords` — words that actually sell\n"
        "`!whales` — what top studios are dropping\n"
        "`!golden_hour` — items rising fast\n"
        "`!xray` — market dashboard\n"
        "`!autopsy <id>` — why an item failed\n"
        "`!hitrate` — did launches beat peers?\n"
        "`!path` — your next milestone\n"
        "`!playbook` — tactics by topic\n"
        "`!selftest` — certify the bot",
    ),
    "help": (
        "🧯 IF SOMETHING BREAKS",
        "**Command not found** → `!bot_update`, wait 30 seconds\n"
        "**Weird numbers** → `!dbtest`\n"
        "**Sales show 0** → `!sales_debug`, then `!sales_backfill`\n"
        "**`!vacuum` empty** → data still loading; try later\n"
        "**Bot offline** → SSH Server 2: `sudo systemctl restart ugc-bot`\n"
        "**Need this menu** → `!start`",
    ),
}


class ManualSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label=title[:100],
                value=key,
                description=body.splitlines()[0][:100],
            )
            for key, (title, body) in SIMPLE_MANUAL.items()
        ]
        super().__init__(
            placeholder="Pick a manual section…",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        key = self.values[0]
        title, body = SIMPLE_MANUAL[key]
        embed = discord.Embed(
            title=title,
            description=body,
            color=COLOR_STEALTH,
        )
        embed.set_footer(text="VANTA 73 · easy manual · pick another section below")
        await interaction.response.edit_message(embed=embed, view=self.view)


class ManualView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)
        self.add_item(ManualSelect())


class CommandCenterView(discord.ui.View):
    """Conversation-first start screen; legacy commands stay available."""

    def __init__(self, bot):
        super().__init__(timeout=600)
        self.bot = bot

    async def _start(self, interaction, starter=None):
        from vanta_conversation import start_conversation
        await start_conversation(interaction, self.bot, starter=starter)

    @discord.ui.button(label="💬 Talk to VANTA", style=discord.ButtonStyle.primary, row=0)
    async def talk(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._start(interaction)

    @discord.ui.button(label="🎯 Find opportunities", style=discord.ButtonStyle.success, row=0)
    async def find_opportunities(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._start(interaction, "find me a niche with low competition")

    @discord.ui.button(label="🔍 Analyze an item", style=discord.ButtonStyle.secondary, row=0)
    async def analyze_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._start(interaction, "I want to check an item. I will send the ID next.")

    @discord.ui.button(label="📊 Check performance", style=discord.ButtonStyle.secondary, row=1)
    async def performance(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._start(interaction, "show my experiment results")

    @discord.ui.button(label="🔒 Private (DM)", style=discord.ButtonStyle.secondary, row=1)
    async def private_dm(self, interaction: discord.Interaction, button: discord.ui.Button):
        from vanta_conversation import start_dm_conversation
        await start_dm_conversation(interaction, self.bot)

    @discord.ui.button(label="🧰 All tools", style=discord.ButtonStyle.secondary, row=1)
    async def all_tools(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🧰 ALL TOOLS",
            description=(
                "The conversational thread is the primary interface. "
                "Every legacy command still works with `!`.\n"
            ),
            color=COLOR_STEALTH,
        )
        embed.add_field(
            name="Strategy",
            value="`!chain` `!converge` `!verdict` `!autopsy` `!revive` "
                  "`!brainstorm` `!creative` `!desc_forge` `!tags`",
            inline=False,
        )
        embed.add_field(
            name="Market",
            value="`!opportunities` `!xray` `!patterns` `!failures` `!early` "
                  "`!momentum` `!oracle` `!nextwave` `!gap`",
            inline=False,
        )
        embed.add_field(
            name="Sales + evidence",
            value="`!sales_report` `!sales_for` `!hitrate` `!revsim` "
                  "`!experiments` `!data_audit` `!visibility`",
            inline=False,
        )
        embed.add_field(
            name="Owner / ops",
            value="`!launch` `!launch_sync` `!ledger_sync` `!enrich_run` "
                  "`!scan_run` `!selftest` `!version`",
            inline=False,
        )
        embed.set_footer(
            text="Use !start classic for the old console · !guide for the full manual"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="ℹ️ Manual", style=discord.ButtonStyle.secondary, row=1)
    async def manual(self, interaction: discord.Interaction, button: discord.ui.Button):
        title, body = SIMPLE_MANUAL["beginner"]
        embed = discord.Embed(title=title, description=body, color=COLOR_STEALTH)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class MenuView(discord.ui.View):
    def __init__(self, bot, get_db):
        super().__init__(timeout=300)
        self.bot = bot
        self.get_db = get_db

    @discord.ui.button(label="🚀 FIRE — Launch New Item", style=discord.ButtonStyle.primary)
    async def launch_new(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🚀 FIRE — LAUNCH NEW ITEM",
            description=(
                "_Builds a full launch kit for a brand-new UGC._\n"
                "_\u200b_\n"
                "**TARGET:** Niche keyword from `!converge`\n"
                "**PAYLOAD:** Champion title + description + 45 tags + price\n"
                "**TIME:** ~20 seconds per strike\n"
                "_\u200b_\n"
                "**STEP 1 — AIM**\n"
                "Type your concept like you're telling a friend:\n"
                "`!chain purple kawaii cat beanie`\n"
                "`!chain spooky halloween dance`\n"
                "`!chain fluffy winter beanie`\n"
                "_\u200b_\n"
                "**STEP 2 — READ THE FIRING SOLUTION**\n"
                "Bot replies with:\n"
                "• 🥇 Champion name (tested against 73k Roblox items)\n"
                "• 📝 Description — copy-paste ready\n"
                "• 🏷️ 45 tags for search discovery\n"
                "• 💰 Price recommendation\n"
                "_\u200b_\n"
                "**STEP 3 — DEPLOY**\n"
                "Read the `✅ FINAL — DO THIS` block at the bottom.\n"
                "Upload to Roblox. Post 1 TikTok.\n"
                "_\u200b_\n"
                "**In 14 days:** run `!verdict <item_id>` for damage assessment."
            ),
            color=COLOR_STEALTH,
        )
        _apply_gif(embed, GIF_FIRE)
        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="⭐ STRIKE — Variant of Winner", style=discord.ButtonStyle.success)
    async def variant(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="⭐ STRIKE — VARIANT OF WINNER",
            description=(
                "_Copies a proven winner's keywords with a fresh theme._\n"
                "_\u200b_\n"
                "**TARGET:** Your own top-performing item\n"
                "**PAYLOAD:** Same keywords + new theme = new buyers\n"
                "**DOCTRINE:** Highest ROI action in the fleet\n"
                "_\u200b_\n"
                "**STEP 1 — GET THE ID**\n"
                "Open the item on Roblox. The number at the end of the URL is the ID.\n"
                "_\u200b_\n"
                "**STEP 2 — FIRE**\n"
                "`!chain variant <item_id>` — bot picks a variation\n"
                "`!chain variant <item_id> neon` — with a specific theme\n"
                "`!chain variant <item_id> halloween` — seasonal\n"
                "_\u200b_\n"
                "**THEMES:** `neon` `cyber` `midnight` `frost` `dark` `deluxe` "
                "`winter` `pastel` `goth` `kawaii` `halloween` `spooky` `pumpkin`\n"
                "_\u200b_\n"
                "**WHY THIS WORKS:** Proven keywords × fresh angle = same "
                "discoverability, new buyers."
            ),
            color=COLOR_STEALTH,
        )
        _apply_gif(embed, GIF_STRIKE)
        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="🔧 INSPECT — Check Live Item", style=discord.ButtonStyle.secondary)
    async def fix_existing(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🔧 INSPECT — CHECK LIVE ITEM",
            description=(
                "_Tells you whether to keep pushing an item or kill it._\n"
                "_\u200b_\n"
                "**TARGET:** Any item already live on Roblox\n"
                "**PAYLOAD:** Sales · age · velocity · percentile · conversion\n"
                "**WHEN:** 14 days after you launch anything\n"
                "_\u200b_\n"
                "**STEP 1 — GET THE ID**\n"
                "Open the item on Roblox. The number at the end of the URL is the ID.\n"
                "_\u200b_\n"
                "**STEP 2 — RUN DIAGNOSTIC**\n"
                "`!verdict 121930221694467`\n"
                "_\u200b_\n"
                "**STEP 3 — READ THE VERDICT**\n"
                "🔥 **DOUBLE_DOWN** — It's working. Ship a variant this week.\n"
                "✅ **KEEP** — Steady. Post 3 TikToks, re-check in 14 days.\n"
                "🔧 **RENAME** — Buyers exist but title is weak. Run `!autopsy <id>`.\n"
                "🪦 **KILL** — Dead. Launch something else.\n"
                "⏳ **TOO_NEW** — Under 7 days old. Wait a few more days."
            ),
            color=COLOR_STEALTH,
        )
        _apply_gif(embed, GIF_INSPECT)
        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="📡 SCAN — Find Trending Niche", style=discord.ButtonStyle.secondary)
    async def trending(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="📡 SCAN — FIND TRENDING NICHE",
            description=(
                "_Radar sweeps the whole catalog. Finds weak spots to attack._\n"
                "_\u200b_\n"
                "**TARGET:** Every keyword in the Roblox catalog\n"
                "**CONTACTS:** 73k items · 44k search signals\n"
                "**REFRESH:** Every 6h (auto pipeline)\n"
                "_\u200b_\n"
                "**STEP 1 — ACTIVATE SONAR**\n"
                "`!converge emotes` — dance/animation\n"
                "`!converge hair` — hair/hats/beanies\n"
                "`!converge face` — masks/glasses\n"
                "`!converge tops` — shirts/jackets\n"
                "`!converge classic` — classic clothing\n"
                "`!converge gear` — swords/staffs\n"
                "_\u200b_\n"
                "**STEP 2 — READ THE CLASSIFICATION**\n"
                "🔥 **SNIPE ZONE** — untapped. Best firing solution.\n"
                "🟢 **GOLD** — low supply, high demand.\n"
                "⚪ **NEUTRAL** — steady but not hot.\n"
                "🔴 **SATURATED** — do not engage.\n"
                "_\u200b_\n"
                "**STEP 3 — LOCK ON AND FIRE**\n"
                "`!chain <keyword> <family>`\n"
                "Example: `!chain halloween emote`"
            ),
            color=COLOR_STEALTH,
        )
        _apply_gif(embed, GIF_SCAN)
        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="🖼️ RECON — Analyze Image", style=discord.ButtonStyle.secondary)
    async def from_image(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🖼️ RECON — ANALYZE IMAGE",
            description=(
                "_Reads a design image. Extracts colors, style, keywords._\n"
                "_\u200b_\n"
                "**TARGET:** A picture of your UGC design\n"
                "**PAYLOAD:** Colors · style · features · item type · keywords\n"
                "**ENGINE:** Gemini vision\n"
                "_\u200b_\n"
                "**STEP 1 — UPLOAD INTEL**\n"
                "In ONE message, attach 1-4 images and type:\n"
                "`!analyze_image`\n"
                "Or with notes: `!analyze_image purple beanie with cat ears`\n"
                "_\u200b_\n"
                "**STEP 2 — READ SENSOR OUTPUT**\n"
                "Bot returns: colors, style, features, item type, aesthetic guess, "
                "and a `search_description` line you can copy.\n"
                "_\u200b_\n"
                "**STEP 3 — FEED TO FIRE**\n"
                "`!chain <paste search_description here>`\n"
                "_\u200b_\n"
                "**Tip:** 2-3 angles (front/side/detail) improve targeting."
            ),
            color=COLOR_STEALTH,
        )
        _apply_gif(embed, GIF_RECON)
        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="🏷️ LOAD — Generate Tags", style=discord.ButtonStyle.success)
    async def tags_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🏷️ LOAD — GENERATE TAGS",
            description=(
                "_Loads 45 SEO tags mined from real top-sellers in your niche._\n"
                "_\u200b_\n"
                "**TARGET:** Your item's champion name\n"
                "**PAYLOAD:** 45 search-optimized tags\n"
                "**SOURCE:** Real top-seller tag blocks + search demand\n"
                "_\u200b_\n"
                "**STEP 1 — SELECT NAME**\n"
                "Use the champion title from `!chain` FINAL block.\n"
                "_\u200b_\n"
                "**STEP 2 — LOAD WARHEADS**\n"
                "`!tags Winter Kawaii Cat Beanie`\n"
                "_\u200b_\n"
                "**With family scoping** (higher accuracy):\n"
                "`!tags hair:Winter Kawaii Cat Beanie`\n"
                "`!tags emotes:Smooth Hip Sway Dance`\n"
                "_\u200b_\n"
                "**STEP 3 — DEPLOY TO ROBLOX**\n"
                "Paste tag line into your description, starting with `tags:`\n"
                "_\u200b_\n"
                "**Why it matters:** Search discovery. Most creators guess tags. "
                "Yours are mined from actual winners."
            ),
            color=COLOR_STEALTH,
        )
        _apply_gif(embed, GIF_LOAD)
        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="🐋 WHALE — Studio Radar", style=discord.ButtonStyle.secondary, row=2)
    async def whale_radar(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🐋 WHALE — TOP STUDIO RADAR",
            description=(
                "_Surveils top 50 studios (Erythia, Rush, Foov) within 15 minutes of drop._\n"
                "_\u200b_\n"
                "**TARGET:** Monitored elite studios dropping new UGC items\n"
                "**PAYLOAD:** Asset ID · item title · price · favorite velocity\n"
                "**DOCTRINE:** Catch studio meta shifts before they saturate\n"
                "_\u200b_\n"
                "**STEP 1 — ACTIVATE RADAR**\n"
                "`!whales` — sweep all top 50 monitored studios\n"
                "`!whales Erythia` — track specific studio drops\n"
                "`!whales Rush` — check Rush Production\n"
                "_\u200b_\n"
                "**STEP 2 — ASSESS THREAT**\n"
                "Bot replies with:\n"
                "• 🏷️ New item name & direct Roblox catalog link\n"
                "• 💰 Price point & category\n"
                "• ⭐ Early favorite velocity\n"
                "_\u200b_\n"
                "**STEP 3 — COUNTER-STRIKE**\n"
                "When a top studio validates a winning theme:\n"
                "Fire `!chain variant <item_id> <theme>` with your unique twist."
            ),
            color=COLOR_STEALTH,
        )
        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="🎯 VACUUM — Search Sniper", style=discord.ButtonStyle.secondary, row=2)
    async def vacuum_sniper(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🎯 VACUUM — SEARCH SNIPER",
            description=(
                "_Finds high-volume player search terms with zero or low catalog supply._\n"
                "_\u200b_\n"
                "**TARGET:** 54,397 mined Roblox autocomplete suggestions\n"
                "**PAYLOAD:** High monthly search volume vs <= 5 catalog items\n"
                "**DOCTRINE:** Launch where thousands search and nobody sells\n"
                "_\u200b_\n"
                "**STEP 1 — FIRE SNIPER**\n"
                "`!vacuum` — scan top zero-supply search gaps\n"
                "`!vacuum 10` — retrieve top 10 market gaps\n"
                "_\u200b_\n"
                "**STEP 2 — SELECT VACUUM TARGET**\n"
                "Look for high query volume with 0 to 3 catalog items.\n"
                "Example: `gothic cyber horns` (45k searches · 3 items)\n"
                "_\u200b_\n"
                "**STEP 3 — LOCK ON & LAUNCH**\n"
                "Take that exact winning query and fire:\n"
                "`!chain <vacuum query>`\n"
                "_\u200b_\n"
                "**WHY THIS WORKS:** Instant top-page search ranking with zero competition."
            ),
            color=COLOR_STEALTH,
        )
        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="📈 REVSIM — Revenue Forecast", style=discord.ButtonStyle.secondary, row=3)
    async def revsim_forecast(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="📈 REVSIM — PRE-LAUNCH REVENUE SIMULATOR",
            description=(
                "_Forecasts 30-day unit sales and Robux return before you model._\n"
                "_\u200b_\n"
                "**TARGET:** Any upcoming item concept or price point\n"
                "**PAYLOAD:** 30d units + gross Robux + 70% creator net profit\n"
                "**CALIBRATION:** Tested against 43,877 real item snapshots\n"
                "_\u200b_\n"
                "**STEP 1 — RUN SIMULATION**\n"
                "`!revsim 105 1000 organic` — organic launch baseline\n"
                "`!revsim 125 2000 moderate` — Discord / group shout push\n"
                "`!revsim 150 3000 aggressive` — top creator whale push\n"
                "_\u200b_\n"
                "**STEP 2 — READ FINANCIAL CURVE**\n"
                "Bot replies with:\n"
                "• 📦 Estimated 30-day unit sales\n"
                "• 💰 Gross Robux volume\n"
                "• 💎 Creator net earnings (after 30% Roblox cut)\n"
                "• 📈 Day 1, 3, 7, and 30 favorite trajectory curve\n"
                "_\u200b_\n"
                "**WHY THIS WORKS:** Know your profit margins before spending modeling hours."
            ),
            color=COLOR_STEALTH,
        )
        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="⚡ VELOCITY — 48h Radar", style=discord.ButtonStyle.secondary, row=3)
    async def velocity_radar(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="⚡ VELOCITY — 48-HOUR TESTING WINDOW",
            description=(
                "_Scans early favorite spikes during Roblox's golden algorithmic test._\n"
                "_\u200b_\n"
                "**TARGET:** Items published within the last 48 hours\n"
                "**PAYLOAD:** Real-time favorite acceleration (+150 favs/hr)\n"
                "**WHEN:** Check daily to catch breakout viral hits early\n"
                "_\u200b_\n"
                "**STEP 1 — ACTIVATE RADAR**\n"
                "`!velocity` — scan top accelerating items\n"
                "`!velocity 8` — top 8 momentum leaders\n"
                "_\u200b_\n"
                "**STEP 2 — READ SENSOR OUTPUT**\n"
                "Look for items gaining >100-200 favorites per hour.\n"
                "Roblox pushes these items to the global front page.\n"
                "_\u200b_\n"
                "**STEP 3 — RIDE THE WAVE**\n"
                "See what's accelerating and launch a complementary variant while hot."
            ),
            color=COLOR_STEALTH,
        )
        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="🧪 LABS — Experiments", style=discord.ButtonStyle.success, row=4)
    async def experiments_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🧪 LABS — CLOSED-LOOP EXPERIMENTS",
            description=(
                "_Every recommendation gets an ID, a baseline, and a measured "
                "7-day outcome. This is how the bot learns what actually works._\n"
            ),
            color=0x8B5CF6,
        )
        embed.add_field(
            name="STEP 1 — after `!autopsy`",
            value=(
                "Rename or reprice the item — the watcher auto-detects it within 15 min.\n"
                "`!applied last` — only needed for a keep+post (no name/price change)\n"
                "`!ignored last` — skipped the newest advice\n"
                "`!experiments` — read results (optional)"
            ),
            inline=False,
        )
        embed.add_field(
            name="STEP 2 — after 7 days",
            value=(
                "`!experiments` — shows day 7 / 14 / 30 velocity and sales uplift"
            ),
            inline=False,
        )
        embed.add_field(
            name="WHY",
            value=(
                "Opinions do not compound. Measured outcomes do. After "
                "10–20 experiments, the bot has real evidence for your "
                "creator account instead of generic advice."
            ),
            inline=False,
        )
        embed.set_footer(text="VANTA 73 · LABS · no prediction without measurement")
        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="ℹ️ MANUAL — Easy Guide", style=discord.ButtonStyle.secondary, row=4)
    async def workflow(self, interaction: discord.Interaction, button: discord.ui.Button):
        title, body = SIMPLE_MANUAL["beginner"]
        embed = discord.Embed(
            title=title,
            description=body,
            color=COLOR_STEALTH,
        )
        embed.set_footer(text="Pick a section from the dropdown below")
        await interaction.response.send_message(embed=embed, view=ManualView())


def register_menu_commands(bot, get_db):

    @bot.command(name="start")
    async def start_cmd(ctx, mode: str = ""):
        """Open the VANTA command center."""
        if mode.lower() in ("classic", "legacy"):
            embed = discord.Embed(
                title="VANTA 73 — TACTICAL CONSOLE",
                description=(
                    "**LEGACY CONSOLE**\n"
                    "_The conversational command center is now the default: `!start`_\n"
                    "\n**Quick commands**\n"
                    "`!converge emotes` · `!chain <concept>` · `!verdict <id>`\n"
                    "`!autopsy <id>` · `!sales_report` · `!experiments`\n"
                    "\nUse `!guide` for the full manual."
                ),
                color=COLOR_STEALTH,
            )
            await ctx.send(embed=embed, view=MenuView(bot, get_db))
            return

        embed = discord.Embed(
            title="VANTA 73 — COMMAND CENTER",
            description=(
                "**Talk to me like a person.** No command names required.\n\n"
                "Try:\n"
                "• `check this item 123456789`\n"
                "• `i made this, what do you think?` + image\n"
                "• `find me a niche with low competition`\n"
                "• `why is this item failing? 123456789`\n"
                "• `make a better title and description for it`\n"
                "• `how are my sales doing?`\n\n"
                "I open a dedicated thread for the conversation. Follow-ups like "
                "`go deeper`, `the second one`, or `same for this item` work there."
            ),
            color=COLOR_STEALTH,
        )
        embed.add_field(
            name="Conversation first",
            value="Describe the goal. VANTA chooses the existing engine.",
            inline=False,
        )
        embed.add_field(
            name="Verified data",
            value="No invented stats, sales, rankings, or completion claims.",
            inline=False,
        )
        embed.set_footer(
            text="VANTA 73 · conversational intelligence · legacy commands still work"
        )
        await ctx.send(embed=embed, view=CommandCenterView(bot))
