"""vanta_guide.py — interactive Field Manual for VANTA 73.

The guide teaches workflows and launches the same conversational router. It
does not duplicate engines or route intents independently.
"""
import discord

from vanta_tools import directory_entries, validate_tool_groups

COLOR = 0x2B6CB0
SECTIONS = {
    "start": {
        "title": "START HERE",
        "body": (
            "Use ordinary language. You do not need command names.\n\n"
            "`check this item 123456789`\n"
            "`find me a niche with low competition`\n"
            "`why is this item failing? 123456789`\n"
            "`i made this, what do you think?` + image\n"
            "`make a better title and description`\n"
            "`how are my sales doing?`\n\n"
            "Follow-ups work when context exists: `go deeper`, "
            "`the second one`, `same for this item 123456789`."
        ),
        "actions": [
            ("Talk to VANTA", None),
            ("Check an item", "check this item"),
            ("Find opportunities", "find me a niche with low competition"),
        ],
        "examples": [
            "check this item 121930221694467",
            "why is this item failing? 121930221694467",
            "i made this, what do you think?  (attach image)",
        ],
    },
    "item": {
        "title": "I HAVE AN EXISTING ITEM",
        "body": (
            "Provide the item ID or a Roblox catalog URL. VANTA can run a "
            "verdict, diagnose underperformance, compare peers, and rebuild "
            "the title/description.\n\n"
            "If data is missing, it will say so instead of inventing it."
        ),
        "actions": [
            ("Check verdict", "check this item"),
            ("Diagnose failure", "why is this item failing?"),
            ("Improve listing", "change the title and description for this item"),
        ],
        "examples": [
            "check this item 121930221694467",
            "why is it failing? 121930221694467",
            "change the title and description for 121930221694467",
        ],
    },
    "create": {
        "title": "I WANT TO CREATE SOMETHING",
        "body": (
            "Describe a concept, attach a design image, or ask for ideas. "
            "VANTA can brainstorm, analyze an image, find adjacent concepts, "
            "and build a verification-aware launch direction.\n\n"
            "Creative output is a hypothesis, not proof of demand."
        ),
        "actions": [
            ("Brainstorm ideas", "give me ideas for a kawaii cat beanie"),
            ("Analyze an image", "i made this, what do you think?"),
            ("Build launch kit", "chain kawaii cat beanie"),
        ],
        "examples": [
            "give me ideas for a kawaii cat beanie",
            "i made this, what do you think?  (attach image)",
            "chain kawaii cat beanie",
        ],
    },
    "market": {
        "title": "MARKET INTELLIGENCE",
        "body": (
            "Explore opportunities, gaps, momentum, trends, and niches. "
            "Observed measurements are separated from estimates and hypotheses.\n\n"
            "Coverage can be incomplete. The bot reports what it actually has."
        ),
        "actions": [
            ("Find gaps", "find me a niche with low competition"),
            ("Analyze keyword", "analyze hip sway"),
            ("Next wave", "find emerging next-wave keywords"),
        ],
        "examples": [
            "find me a niche with low competition",
            "analyze hip sway",
            "find emerging next-wave keywords",
        ],
    },
    "performance": {
        "title": "SALES, TRACKING & EXPERIMENTS",
        "body": (
            "Read recorded sales, launch performance, visibility coverage, "
            "and experiment evidence.\n\n"
            "No sales figure is estimated unless it is explicitly labeled. "
            "Matched-control results are observational."
        ),
        "actions": [
            ("Sales report", "how much have i made recently?"),
            ("Experiment results", "show my experiment results"),
            ("Visibility coverage", "show my search visibility"),
        ],
        "examples": [
            "how much have i made recently?",
            "show my experiment results",
            "show my search visibility",
        ],
    },
    "tools": {
        "title": "ALL TOOLS",
        "body": "Browse every registered command by purpose.",
        "actions": [],
        "examples": [],
    },
}

SELECT_OPTIONS = [
    discord.SelectOption(label=SECTIONS[key]["title"][:100], value=key)
    for key in ("start", "item", "create", "market", "performance", "tools")
]


def _home_embed():
    return discord.Embed(
        title="VANTA 73 — FIELD MANUAL",
        description=(
            "**Describe the outcome. VANTA chooses the tools.**\n\n"
            "The manual teaches workflows and launches the same conversational "
            "router used by `!start`.\n\n"
            "Pick a section below, or start with **Talk to VANTA**."
        ),
        color=COLOR,
    ).set_footer(text="VANTA 73 · verified data, measured outcomes")


def _section_embed(key):
    sec = SECTIONS.get(key) or SECTIONS["start"]
    embed = discord.Embed(title=f"VANTA — {sec['title']}",
                          description=sec["body"], color=COLOR)
    if sec.get("examples"):
        embed.add_field(
            name="Try",
            value="\n".join(f"• `{x}`" for x in sec["examples"])[:1024],
            inline=False,
        )
    return embed


def _tools_embed(entries, page, per_page=6):
    pages = max(1, (len(entries) + per_page - 1) // per_page)
    page = max(0, min(page, pages - 1))
    start = page * per_page
    embed = discord.Embed(
        title="VANTA — ALL TOOLS",
        description=f"Page **{page + 1}/{pages}** · {len(entries)} registered tools",
        color=COLOR,
    )
    for entry in entries[start:start + per_page]:
        value = f"{entry['summary']}\nInput: **{entry['input']}** · `{entry['example']}`"
        if entry.get("limit"):
            value += f"\n_Limit: {entry['limit']}_"
        embed.add_field(name=f"{entry['group']} · `!{entry['name']}`",
                        value=value[:1024], inline=False)
    if not entries:
        embed.description = "No registered tools found."
    return embed, page, pages


class ToolsView(discord.ui.View):
    def __init__(self, bot, entries, page=0):
        super().__init__(timeout=300)
        self.bot = bot
        self.entries = entries
        self.page = page
        self.per_page = 6
        self._sync()

    def _sync(self):
        _, self.page, pages = _tools_embed(self.entries, self.page, self.per_page)
        for child in self.children:
            if child.custom_id == "tools_prev":
                child.disabled = self.page <= 0
            if child.custom_id == "tools_next":
                child.disabled = self.page >= pages - 1

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary,
                       custom_id="tools_prev")
    async def prev(self, interaction, button):
        self.page -= 1
        self._sync()
        await interaction.response.edit_message(
            embed=_tools_embed(self.entries, self.page, self.per_page)[0],
            view=self,
        )

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary,
                       custom_id="tools_next")
    async def next(self, interaction, button):
        self.page += 1
        self._sync()
        await interaction.response.edit_message(
            embed=_tools_embed(self.entries, self.page, self.per_page)[0],
            view=self,
        )

    @discord.ui.button(label="Back to manual", style=discord.ButtonStyle.secondary,
                       row=1)
    async def back(self, interaction, button):
        await interaction.response.edit_message(
            embed=_home_embed(), view=GuideHomeView(self.bot)
        )


class GuideHomeView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=300)
        self.bot = bot

    @discord.ui.select(placeholder="Choose a section…", options=SELECT_OPTIONS)
    async def section(self, interaction, select):
        key = select.values[0]
        if key == "tools":
            return await open_tools(interaction, self.bot, edit=True)
        await interaction.response.edit_message(
            embed=_section_embed(key), view=GuideSectionView(self.bot, key)
        )

    @discord.ui.button(label="Talk to VANTA", style=discord.ButtonStyle.primary, row=1)
    async def talk(self, interaction, button):
        from vanta_conversation import start_conversation
        await start_conversation(interaction, self.bot)

    @discord.ui.button(label="All tools", style=discord.ButtonStyle.secondary, row=1)
    async def tools(self, interaction, button):
        await open_tools(interaction, self.bot, edit=True)


class GuideSectionView(discord.ui.View):
    def __init__(self, bot, key):
        super().__init__(timeout=300)
        self.bot = bot
        self.key = key
        section = SECTIONS.get(key) or SECTIONS["start"]
        for index, (label, starter) in enumerate(section.get("actions") or []):
            button = discord.ui.Button(
                label=label[:80],
                style=(discord.ButtonStyle.primary if index == 0
                       else discord.ButtonStyle.secondary),
                row=index // 3,
            )
            button.callback = self._make_action(starter)
            self.add_item(button)

        examples = section.get("examples") or []
        if examples:
            ex = discord.ui.Button(label="See examples",
                                   style=discord.ButtonStyle.secondary, row=1)
            ex.callback = self._make_examples(examples)
            self.add_item(ex)

        back = discord.ui.Button(label="Back to manual",
                                 style=discord.ButtonStyle.secondary, row=1)
        back.callback = self._back
        self.add_item(back)

        tools = discord.ui.Button(label="All tools",
                                  style=discord.ButtonStyle.secondary, row=1)
        tools.callback = self._tools
        self.add_item(tools)

    def _make_action(self, starter):
        async def callback(interaction):
            from vanta_conversation import start_conversation
            await start_conversation(interaction, self.bot, starter=starter)
        return callback

    def _make_examples(self, examples):
        async def callback(interaction):
            await interaction.response.send_message(
                "Try:\n" + "\n".join(f"• `{x}`" for x in examples),
                ephemeral=True,
            )
        return callback

    async def _back(self, interaction):
        await interaction.response.edit_message(
            embed=_home_embed(), view=GuideHomeView(self.bot)
        )

    async def _tools(self, interaction):
        await open_tools(interaction, self.bot, edit=True)


async def open_guide(interaction, bot, section=None, edit=False):
    if section:
        embed = _section_embed(section)
        view = (GuideSectionView(bot, section)
                if section != "tools" else None)
        if view is None:
            return await open_tools(interaction, bot, edit=edit)
    else:
        embed, view = _home_embed(), GuideHomeView(bot)
    if edit:
        await interaction.response.edit_message(embed=embed, view=view)
    else:
        await interaction.response.send_message(embed=embed, view=view)


async def open_tools(interaction, bot, page=0, edit=False):
    entries = directory_entries(bot)
    view = ToolsView(bot, entries, page)
    embed, _, _ = _tools_embed(entries, page)
    if edit:
        await interaction.response.edit_message(embed=embed, view=view)
    else:
        await interaction.response.send_message(embed=embed, view=view)


def register_manual_commands(bot):
    @bot.command(name="guide", aliases=["manual", "field_manual"])
    async def guide_cmd(ctx, section: str = ""):
        """Open the VANTA Field Manual."""
        import asyncio
        if section.lower() == "tools":
            entries = directory_entries(bot)
            embed, _, _ = _tools_embed(entries, 0)
            await ctx.send(embed=embed, view=ToolsView(bot, entries, 0))
            return
        key = section.lower() if section.lower() in SECTIONS else None
        if key and key != "tools":
            await ctx.send(embed=_section_embed(key),
                           view=GuideSectionView(bot, key))
            return
        await ctx.send(embed=_home_embed(), view=GuideHomeView(bot))

    @bot.command(name="tools")
    async def tools_cmd(ctx, page: int = 0):
        """Browse every registered VANTA command by purpose."""
        entries = directory_entries(bot)
        embed, _, _ = _tools_embed(entries, max(0, page - 1))
        await ctx.send(embed=embed,
                       view=ToolsView(bot, entries, max(0, page - 1)))
