"""
menu.py — interactive workflow menu for the bot.
!start opens a guided flow with buttons.

Every button explains:
  - What command to run
  - What you'll get back
  - When to use it
"""
import discord


class MenuView(discord.ui.View):
    def __init__(self, bot, get_db):
        super().__init__(timeout=300)
        self.bot = bot
        self.get_db = get_db

    @discord.ui.button(label="🚀 Launch new item", style=discord.ButtonStyle.primary)
    async def launch_new(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "**🚀 Launch a new UGC item**\n"
            "_\u200b_\n"
            "**What this does:** AI builds a full launch kit for a brand-new item "
            "(statistical name + description + tags + price).\n"
            "_\u200b_\n"
            "**STEP 1** — Type your concept like you're telling a friend:\n"
            "`!chain purple kawaii cat beanie`\n"
            "`!chain spinning hip sway dance`\n"
            "`!chain fluffy winter beanie with ears`\n"
            "_\u200b_\n"
            "**STEP 2** — Wait ~20 seconds. Bot replies with:\n"
            "• 🥇 **Champion name** (tested against 73k Roblox items)\n"
            "• 📝 **Description** — copy-paste ready\n"
            "• 🏷️ **45 tags** for search discovery\n"
            "• 💰 **Price** recommendation\n"
            "_\u200b_\n"
            "**STEP 3** — Read the `✅ FINAL — DO THIS` block at the bottom. "
            "It tells you exactly:\n"
            "  1. What to name the item\n"
            "  2. What to paste as description\n"
            "  3. What price to set\n"
            "  4. What to post on TikTok\n"
            "_\u200b_\n"
            "**Then:** Upload to Roblox. Post 1 TikTok. Done.\n"
            "**In 14 days:** run `!verdict <item_id>` to check if it's working."
        )

    @discord.ui.button(label="🔧 Fix existing item", style=discord.ButtonStyle.secondary)
    async def fix_existing(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "**🔧 Check an item that's already live**\n"
            "_\u200b_\n"
            "**What this does:** Tells you whether to keep investing in an item "
            "or cut your losses. One label, one action.\n"
            "_\u200b_\n"
            "**STEP 1** — Get the item ID:\n"
            "Open the item on Roblox. The number at the end of the URL is the ID.\n"
            "Example: `roblox.com/catalog/`**`121930221694467`**`/Kpop-Beanie`\n"
            "_\u200b_\n"
            "**STEP 2** — Run:\n"
            "`!verdict 121930221694467`\n"
            "_\u200b_\n"
            "**STEP 3** — Bot replies with ONE of these labels:\n\n"
            "🔥 **DOUBLE_DOWN** — It's working. Real sales. Ship a variant this week.\n"
            "✅ **KEEP** — Steady. Post 3 TikToks this week, re-check in 14 days.\n"
            "🔧 **RENAME** — Buyers exist but title is weak. Run `!autopsy <id>` to fix.\n"
            "🪦 **KILL** — Dead. Stop spending time. Launch something else.\n"
            "⏳ **TOO_NEW** — Under 7 days old. Wait a few more days.\n"
            "_\u200b_\n"
            "**When to run it:** 14 days after you launch anything."
        )

    @discord.ui.button(label="🖼️ Start from image", style=discord.ButtonStyle.secondary)
    async def from_image(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "**🖼️ Start from an image**\n"
            "_\u200b_\n"
            "**What this does:** You upload a picture of your item. The bot reads "
            "colors, style, and features, then hands you a searchable concept to "
            "feed into `!chain`.\n"
            "_\u200b_\n"
            "**STEP 1** — In ONE message, attach 1-4 images and type:\n"
            "`!analyze_image`\n"
            "Or with notes: `!analyze_image purple beanie with cat ears`\n"
            "_\u200b_\n"
            "**STEP 2** — Bot replies with:\n"
            "• 👁️ What it sees (colors, style, features, item type)\n"
            "• 🎨 Aesthetic guess (kawaii / goth / y2k / etc.)\n"
            "• 📋 A `search_description` line you can copy\n"
            "_\u200b_\n"
            "**STEP 3** — Copy that line and run:\n"
            "`!chain <paste search_description here>`\n"
            "_\u200b_\n"
            "**Result:** Same launch kit as the Launch button, but anchored "
            "on what's actually in your image.\n"
            "_\u200b_\n"
            "**Tip:** 2-3 angles (front/side/detail) give better vision analysis."
        )

    @discord.ui.button(label="📈 Find trending niche", style=discord.ButtonStyle.secondary)
    async def trending(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "**📈 Find a trending niche**\n"
            "_\u200b_\n"
            "**What this does:** Scans the entire Roblox catalog. Ranks every "
            "keyword by demand, freshness, velocity, and competition. Surfaces "
            "the 5-10 best spots to enter.\n"
            "_\u200b_\n"
            "**STEP 1** — Pick a category and run:\n"
            "`!converge emotes` — dance/animation\n"
            "`!converge hair` — hair/hats/beanies\n"
            "`!converge face` — masks/glasses\n"
            "`!converge tops` — shirts/jackets\n"
            "`!converge classic` — classic clothing\n"
            "`!converge all_families` — scan everything at once\n"
            "_\u200b_\n"
            "**STEP 2** — Look at the results. Each keyword shows:\n"
            "🔥 **SNIPE ZONE** — untapped + rising. BEST opportunity.\n"
            "🟢 **GOLD** — low supply, high demand. Strong entry.\n"
            "⚪ **NEUTRAL** — steady but not hot. Safe play.\n"
            "🔴 **SATURATED** — skip.\n"
            "_\u200b_\n"
            "**STEP 3** — Take the top 🔥 or 🟢 keyword and run:\n"
            "`!chain <keyword> <family>`\n"
            "Example: `!chain hip sway emotes`\n"
            "_\u200b_\n"
            "**Why this matters:** You're seeing real market data instead of "
            "guessing from TikTok trends. 3-5x better niche picks."
        )

    @discord.ui.button(label="⭐ Make a variant", style=discord.ButtonStyle.success)
    async def variant(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "**⭐ Make a variant of a winner**\n"
            "_\u200b_\n"
            "**What this does:** Copies the winning keywords from an existing "
            "item and rebuilds the title/description/tags for a new theme "
            "(color, effect, aesthetic). **This is the #1 way to multiply "
            "sales on a proven concept.**\n"
            "_\u200b_\n"
            "**STEP 1** — Get the item ID of your top performer:\n"
            "Roblox page → number at the end of the URL.\n"
            "_\u200b_\n"
            "**STEP 2** — Run:\n"
            "`!chain variant <item_id>` — bot picks a variation\n"
            "`!chain variant <item_id> neon` — with a specific theme\n"
            "`!chain variant <item_id> winter` — seasonal variant\n"
            "_\u200b_\n"
            "**Valid themes:** `neon`, `cyber`, `midnight`, `frost`, "
            "`dark`, `deluxe`, `winter`, `pastel`, `goth`, `kawaii`\n"
            "_\u200b_\n"
            "**Example:**\n"
            "`!chain variant 121930221694467 winter`\n"
            "_\u200b_\n"
            "**Why this works:** Winning items have proven keywords. Variants "
            "reuse those keywords with a fresh angle → same discoverability, "
            "new buyers."
        )

    @discord.ui.button(label="🏷️ Generate tags", style=discord.ButtonStyle.success)
    async def tags_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "**🏷️ Generate 45 SEO tags**\n"
            "_\u200b_\n"
            "**What this does:** Mines every tag real top-sellers use in your "
            "niche, then builds a 45-tag block for your item. Every tag traces "
            "to a real item in the DB — zero hallucination.\n"
            "_\u200b_\n"
            "**STEP 1** — Pick your item name:\n"
            "Use the champion name from `!chain`'s FINAL block.\n"
            "_\u200b_\n"
            "**STEP 2** — Run:\n"
            "`!tags Winter Kawaii Cat Beanie`\n"
            "_\u200b_\n"
            "**With category** (more accurate):\n"
            "`!tags hair:Winter Kawaii Cat Beanie`\n"
            "`!tags emotes:Smooth Hip Sway Dance`\n"
            "_\u200b_\n"
            "**STEP 3** — Copy the tag line into your Roblox description.\n"
            "Paste it under your main description text, starting with `tags:`\n"
            "_\u200b_\n"
            "**Why this matters:** Search discovery. Most creators guess tags. "
            "These are mined from actual top-selling items."
        )

    @discord.ui.button(label="ℹ️ Full workflow", style=discord.ButtonStyle.secondary)
    async def workflow(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🔨 The UGC Bot Workflow",
            description=(
                "**The loop is 3 steps, in this order:**\n"
                "_\u200b_\n"
                "**STEP 1 — FIND A NICHE** (`!converge`)\n"
                "Scans the Roblox catalog. Ranks every keyword by real market signals.\n"
                "• Run: `!converge emotes` (or `hair`, `face`, `tops`, `classic`, `gear`)\n"
                "• Pick the top 🔥 SNIPE ZONE or 🟢 GOLD keyword\n"
                "_\u200b_\n"
                "**STEP 2 — BUILD THE ITEM** (`!chain`)\n"
                "AI builds a full launch kit for that keyword.\n"
                "• Run: `!chain <keyword from step 1>`\n"
                "• You get: champion name, description, 45 tags, price recommendation\n"
                "• Launch on Roblox. Post 1 TikTok.\n"
                "_\u200b_\n"
                "**STEP 3 — CHECK IN 14 DAYS** (`!verdict`)\n"
                "The bot inspects your item vs real peer items and tells you what to do.\n"
                "• Run: `!verdict <your new item id>`\n"
                "• You get ONE of:\n"
                "    🔥 **DOUBLE_DOWN** → make a variant this week\n"
                "    ✅ **KEEP** → post 3 TikToks, re-check in 14 days\n"
                "    🔧 **RENAME** → run `!autopsy <id>` to fix the title\n"
                "    🪦 **KILL** → launch something else\n"
                "    ⏳ **TOO_NEW** → wait a few more days\n"
                "_\u200b_\n"
                "**Then repeat the loop.** New scan → new item → launch → 14 days → verdict.\n"
                "_\u200b_\n"
                "**Weekly rhythm:**\n"
                "• Weekly: `!converge` + launch 1 new item\n"
                "• Daily: `!verdict` on your live items\n"
                "• On every winner: `!chain variant <id> <theme>`\n"
                "_\u200b_\n"
                "**Bonus tools:**\n"
                "• `!tags <name>` — 45 SEO tags\n"
                "• `!desc_forge <keyword>` — style-matched description\n"
                "• `!autopsy <id>` — deep failure analysis\n"
                "• `!brainstorm <concept>` — deep AI strategy session"
            ),
            color=0x00ff88,
        )
        await interaction.response.send_message(embed=embed)


def register_menu_commands(bot, get_db):

    @bot.command(name="start")
    async def start_cmd(ctx):
        """Opens the workflow menu."""
        embed = discord.Embed(
            title="🎯 UGC Bot — Workflow Menu",
            description=(
                "Pick what you want to do. I'll walk you through it step by step.\n\n"
                "**🟢 Most common:**\n"
                "• 🚀 **Launch new item** — build a full launch kit for a new UGC\n"
                "• ⭐ **Make a variant** — copy your winner, add a new theme\n\n"
                "**🟡 When you have live items:**\n"
                "• 🔧 **Fix existing item** — keep it or kill it (runs `!verdict`)\n\n"
                "**🟠 When you need ideas:**\n"
                "• 📈 **Find trending niche** — scan the whole market for openings\n"
                "• 🖼️ **Start from image** — analyze a design and get concepts\n\n"
                "**🟢 Polish tools:**\n"
                "• 🏷️ **Generate tags** — 45 SEO tags from real top-sellers\n\n"
                "**ℹ️ Confused? Click** `Full workflow` **for the complete guide.**"
            ),
            color=0x5865F2,
        )
        embed.set_footer(text="Menu closes in 5 minutes.")
        view = MenuView(bot, get_db)
        await ctx.send(embed=embed, view=view)
