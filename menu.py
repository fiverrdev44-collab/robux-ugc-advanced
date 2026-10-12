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

    @discord.ui.button(label="ℹ️ MANUAL — Full Guide", style=discord.ButtonStyle.secondary)
    async def workflow(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="⚓ VANTA 73 — COMBAT MANUAL",
            description=(
                "**THE LOOP — 3 PHASES, IN ORDER**\n"
                "_\u200b_\n"
                "**PHASE 1 — SCAN FOR NICHES**  (`!converge`)\n"
                "Radar sweep across the whole catalog. Ranks every keyword by real signals.\n"
                "• Fire: `!converge emotes` (or `hair`, `face`, `tops`, `classic`, `gear`)\n"
                "• Lock onto the top 🔥 SNIPE ZONE or 🟢 GOLD contact\n"
                "_\u200b_\n"
                "**PHASE 2 — FIRE MAIN WARHEAD**  (`!chain`)\n"
                "Builds a full launch kit for that keyword.\n"
                "• Fire: `!chain <keyword from Phase 1>`\n"
                "• You get: champion name, description, 45 tags, price\n"
                "• Deploy: Upload to Roblox. Post 1 TikTok.\n"
                "_\u200b_\n"
                "**PHASE 3 — AFTER-ACTION REPORT**  (`!verdict`)\n"
                "14 days post-launch. Damage assessment vs real peers.\n"
                "• Fire: `!verdict <your new item id>`\n"
                "• You get ONE of:\n"
                "    🔥 **DOUBLE_DOWN** → ship a cluster strike this week\n"
                "    ✅ **KEEP** → hold position, post 3 TikToks\n"
                "    🔧 **RENAME** → fire `!autopsy <id>` for diagnostics\n"
                "    🪦 **KILL** → abandon, re-scan\n"
                "    ⏳ **TOO_NEW** → wait for sensor lock\n"
                "_\u200b_\n"
                "**FLEET RHYTHM**\n"
                "• Weekly: `!converge` → `!chain` → launch 1 new ship\n"
                "• Daily: `!verdict` on every live ship\n"
                "• Every winner: `!chain variant <id> <theme>`\n"
                "_\u200b_\n"
                "**SECONDARY WEAPONS**\n"
                "• `!tags <name>` — 45 SEO warheads\n"
                "• `!desc_forge <keyword>` — style-matched description\n"
                "• `!autopsy <id>` — deep failure analysis\n"
                "• `!brainstorm <concept>` — deep strategy strike\n"
                "_\u200b_\n"
                "**MOTTO:** *Kills on contact. Never misses. Never sleeps.*"
            ),
            color=COLOR_STEALTH,
        )
        _apply_gif(embed, GIF_MANUAL)
        await interaction.response.send_message(embed=embed)


def register_menu_commands(bot, get_db):

    @bot.command(name="start")
    async def start_cmd(ctx):
        """Opens the tactical console."""
        embed = discord.Embed(
            title="⚓ VANTA 73 — TACTICAL CONSOLE",
            description=(
                "**STATUS: ALL WEAPONS HOT · ALL SYSTEMS NOMINAL**\n"
                "_\u200b_\n"
                "**🚀 FIRE — Launch New Item**\n"
                "Build a full launch kit (name + description + tags + price).\n"
                "_\u200b_\n"
                "**⭐ STRIKE — Variant of Winner**\n"
                "Copy your best item, add a new theme. Fastest path to sales.\n"
                "_\u200b_\n"
                "**🔧 INSPECT — Check Live Item**\n"
                "Keep it, rename it, or kill it. Runs `!verdict` on any item.\n"
                "_\u200b_\n"
                "**📡 SCAN — Find Trending Niche**\n"
                "Radar sweep of the whole market. Find weak spots to attack.\n"
                "_\u200b_\n"
                "**🖼️ RECON — Analyze Image**\n"
                "Upload a design picture. Get keywords + concept back.\n"
                "_\u200b_\n"
                "**🏷️ LOAD — Generate Tags**\n"
                "45 SEO tags mined from real top-sellers. Copy-paste ready.\n"
                "_\u200b_\n"
                "**ℹ️ Click MANUAL for the full 3-phase combat guide.**"
            ),
            color=COLOR_STEALTH,
        )

        _apply_gif(embed, GIF_MAIN)

        embed.set_footer(
            text="VANTA 73 · Stealth UGC Hunter · Absorbs 99.96% of competition"
        )

        view = MenuView(bot, get_db)
        await ctx.send(embed=embed, view=view)
