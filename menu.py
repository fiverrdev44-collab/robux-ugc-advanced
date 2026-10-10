"""
menu.py — interactive workflow menu for the bot.
!start opens a guided flow with buttons.
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
            "**Step 1 of 3 — Describe your concept**\n"
            "Type it like you're telling a friend.\n\n"
            "Example: `purple kawaii cat beanie with jewel`\n"
            "Or: `emotes:spinning hip sway dance`\n\n"
            "**Step 2 of 3** — Run:\n"
            "`!chain <your concept>`\n\n"
            "**Step 3 of 3** — Read the `✅ FINAL — DO THIS` block and do every line."
        )

    @discord.ui.button(label="🔧 Fix existing item", style=discord.ButtonStyle.secondary)
    async def fix_existing(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "**Step 1 of 3 — Get the item ID**\n"
            "On Roblox: open the item page. The number at the end of the URL is the ID.\n\n"
            "**Step 2 of 3** — Run:\n"
            "`!verdict <item_id>`\n\n"
            "**Step 3 of 3** — Do what the verdict says:\n"
            "• ✅ **KEEP** → post 1 TikTok today\n"
            "• 🔥 **DOUBLE_DOWN** → launch a variant this week\n"
            "• 🔧 **RENAME** → run `!autopsy <id>` to learn why\n"
            "• 🪦 **KILL** → stop. Run `!converge emotes` for a new niche."
        )

    @discord.ui.button(label="🖼️ Start from image", style=discord.ButtonStyle.secondary)
    async def from_image(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "**Step 1 of 2 — Upload your image**\n"
            "In the SAME message, attach 1-4 images and type:\n"
            "`!analyze_image <brief notes>`\n\n"
            "The bot reads the image → gives you colors, style, keywords.\n"
            "Copy the `search_description` line it produces.\n\n"
            "**Step 2 of 2** — Paste into chain:\n"
            "`!chain <paste here>`"
        )

    @discord.ui.button(label="📈 Find trending niche", style=discord.ButtonStyle.secondary)
    async def trending(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "**Step 1 of 2 — Pick a category**\n"
            "Run one of these:\n"
            "`!converge emotes`\n"
            "`!converge hair`\n"
            "`!converge back`\n\n"
            "Look at the top 3 results. You want:\n"
            "• 🔥 **SNIPE ZONE** — best\n"
            "• 🟢 **GOLD** — strong\n"
            "• ⚪ **NEUTRAL** with median > 80 — safe\n\n"
            "**Step 2 of 2** — Build it:\n"
            "`!chain <winning keyword> emote`"
        )

    @discord.ui.button(label="⭐ Make a variant", style=discord.ButtonStyle.success)
    async def variant(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "**Step 1 of 2 — Get your winner's item ID**\n"
            "On Roblox: open the item page, copy the number at the end of the URL.\n\n"
            "**Step 2 of 2** — Chain the variant:\n"
            "`!chain variant <item_id>` — AI picks a variation\n"
            "`!chain variant <item_id> neon` — with a specific theme\n\n"
            "**Valid themes:** `neon`, `cyber`, `midnight`, `frost`, `dark`, `deluxe`\n\n"
            "Example: `!chain variant 121930221694467 neon`"
        )

    @discord.ui.button(label="ℹ️ Full workflow", style=discord.ButtonStyle.secondary)
    async def workflow(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "**The 3-command workflow**\n\n"
            "**1. Building?**\n"
            "`!chain <concept>` → follow FINAL block\n"
            "`!chain variant <id> <theme>` → copy a winner\n\n"
            "**2. Checking?**\n"
            "`!verdict <item_id>` → do what it says\n\n"
            "**3. Need ideas?**\n"
            "`!converge emotes` → pick top 🔥 or 🟢\n\n"
            "**That's it. No other commands needed.**\n\n"
            "**Daily:** `!verdict` on your live items\n"
            "**Weekly:** `!converge` + launch one variant\n"
            "**14 days after launch:** `!verdict` the new item"
        )


def register_menu_commands(bot, get_db):

    @bot.command(name="start")
    async def start_cmd(ctx):
        """Opens the workflow menu."""
        embed = discord.Embed(
            title="🎯 UGC Bot — Workflow Menu",
            description=(
                "Pick what you want to do. I'll walk you through it.\n\n"
                "**Most common:** `🚀 Launch new item` or `⭐ Make a variant`"
            ),
            color=0x5865F2,
        )
        embed.set_footer(text="Menu closes in 5 minutes.")
        view = MenuView(bot, get_db)
        await ctx.send(embed=embed, view=view)
