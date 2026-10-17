"""
bot_ui.py — all discord.ui.View classes + nav helper.
"""
import asyncio
import discord


class MultiViewPaginator(discord.ui.View):
    def __init__(self, data):
        super().__init__(timeout=300)
        self.data = data
        self.view_mode = "keywords"
        self.page = 0
        self.per_page = 8
        self.rebuild_buttons()

    def build_embed(self):
        d = self.data
        seed = d["seed"]
        if self.view_mode == "keywords":
            items = d["top_keywords"]
            max_page = max(0, (len(items) - 1) // self.per_page)
            self.page = min(self.page, max_page)
            start = self.page * self.per_page
            chunk = items[start:start + self.per_page]
            embed = discord.Embed(title=f"🎯 Keywords for `{seed}`",
                                  description=f"Showing **{start+1}–{min(start+self.per_page, len(items))}** of **{len(items)}**.",
                                  color=0x00ff88)
            for i, (w, af, c, sc) in enumerate(chunk, start + 1):
                embed.add_field(name=f"{i}. {w}",
                                value=f"Score: **{sc:,.0f}** | AvgFav: **{af:,.0f}** | Comp: **{c:,}**",
                                inline=False)
            embed.set_footer(text=f"Page {self.page+1}/{max_page+1}")
        elif self.view_mode == "adjacent":
            adjs = d["adjacent"]
            embed = discord.Embed(title=f"🔗 Adjacent Keywords for `{seed}`",
                                  description="Words alongside your seed.", color=0x66ccff)
            if adjs:
                half = (len(adjs) + 1) // 2
                left = " · ".join(f"`{w}`" for w in adjs[:half])
                right = " · ".join(f"`{w}`" for w in adjs[half:])
                if left: embed.add_field(name="\u200b", value=left, inline=True)
                if right: embed.add_field(name="\u200b", value=right, inline=True)
            else:
                embed.add_field(name="No adjacent keywords", value="Try a broader seed.", inline=False)
        elif self.view_mode == "description":
            descs = d["description_keywords"]
            embed = discord.Embed(title=f"📝 Hidden Description Keywords for `{seed}`",
                                  description="SEO words buried in descriptions.", color=0xaa66ff)
            if descs:
                half = (len(descs) + 1) // 2
                left = " · ".join(f"`{w}`" for w in descs[:half])
                right = " · ".join(f"`{w}`" for w in descs[half:])
                if left: embed.add_field(name="\u200b", value=left, inline=True)
                if right: embed.add_field(name="\u200b", value=right, inline=True)
            else:
                embed.add_field(name="No description keywords", value="Try a different seed.", inline=False)
        elif self.view_mode == "market":
            embed = discord.Embed(title=f"💰 Market Info for `{seed}`",
                                  description="Competitive intelligence.", color=0xffaa00)
            embed.add_field(name="💰 Price",
                            value=f"Median: **{d['median_price']} R$**\nBest: **{d['best_price']} R$**",
                            inline=True)
            embed.add_field(name="📊 Health",
                            value=f"Comp: **{d['total_matches']}**\n{d['saturation']}",
                            inline=True)
            embed.add_field(name="👥 Creators",
                            value=f"Unique: **{d['unique_creators']}**\nTop: **{d['top_creator_share']}%**",
                            inline=True)
            if d["top_styles"]:
                styles_str = "\n".join(f"`{s}` — {c} items" for s, c in d["top_styles"])
                embed.add_field(name="🎨 Styles", value=styles_str, inline=False)
            if d["study_items"]:
                study_str = "\n".join(f"`{iid}` — {name[:45]} ({favs:,} favs)"
                                      for iid, name, _, favs, _, _ in d["study_items"])
                embed.add_field(name="👀 Study These", value=study_str, inline=False)
        return embed

    def rebuild_buttons(self):
        self.clear_items()
        d = self.data
        kw_btn = discord.ui.Button(label=f"🎯 Keywords ({len(d['top_keywords'])})",
                                   style=discord.ButtonStyle.success if self.view_mode == "keywords" else discord.ButtonStyle.secondary, row=1)
        kw_btn.callback = self.set_keywords; self.add_item(kw_btn)
        adj_btn = discord.ui.Button(label=f"🔗 Adjacent ({len(d['adjacent'])})",
                                    style=discord.ButtonStyle.success if self.view_mode == "adjacent" else discord.ButtonStyle.secondary, row=1)
        adj_btn.callback = self.set_adjacent; self.add_item(adj_btn)
        desc_btn = discord.ui.Button(label=f"📝 Description ({len(d['description_keywords'])})",
                                     style=discord.ButtonStyle.success if self.view_mode == "description" else discord.ButtonStyle.secondary, row=1)
        desc_btn.callback = self.set_description; self.add_item(desc_btn)
        market_btn = discord.ui.Button(label="💰 Market",
                                       style=discord.ButtonStyle.success if self.view_mode == "market" else discord.ButtonStyle.secondary, row=1)
        market_btn.callback = self.set_market; self.add_item(market_btn)
        if self.view_mode == "keywords":
            total = len(d["top_keywords"])
            max_page = max(0, (total - 1) // self.per_page)
            first = discord.ui.Button(label="⏮️", style=discord.ButtonStyle.secondary, row=0, disabled=(self.page == 0))
            first.callback = self.first_page; self.add_item(first)
            prev = discord.ui.Button(label="◀️", style=discord.ButtonStyle.primary, row=0, disabled=(self.page == 0))
            prev.callback = self.prev_page; self.add_item(prev)
            ind = discord.ui.Button(label=f"Page {self.page+1}/{max_page+1}",
                                    style=discord.ButtonStyle.secondary, row=0, disabled=True)
            self.add_item(ind)
            nxt = discord.ui.Button(label="▶️", style=discord.ButtonStyle.primary, row=0, disabled=(self.page >= max_page))
            nxt.callback = self.next_page; self.add_item(nxt)
            last = discord.ui.Button(label="⏭️", style=discord.ButtonStyle.secondary, row=0, disabled=(self.page >= max_page))
            last.callback = self.last_page; self.add_item(last)

    async def set_keywords(self, i):
        self.view_mode = "keywords"; self.page = 0; self.rebuild_buttons()
        await i.response.edit_message(embed=self.build_embed(), view=self)
    async def set_adjacent(self, i):
        self.view_mode = "adjacent"; self.rebuild_buttons()
        await i.response.edit_message(embed=self.build_embed(), view=self)
    async def set_description(self, i):
        self.view_mode = "description"; self.rebuild_buttons()
        await i.response.edit_message(embed=self.build_embed(), view=self)
    async def set_market(self, i):
        self.view_mode = "market"; self.rebuild_buttons()
        await i.response.edit_message(embed=self.build_embed(), view=self)
    async def first_page(self, i):
        self.page = 0; self.rebuild_buttons()
        await i.response.edit_message(embed=self.build_embed(), view=self)
    async def prev_page(self, i):
        self.page = max(0, self.page - 1); self.rebuild_buttons()
        await i.response.edit_message(embed=self.build_embed(), view=self)
    async def next_page(self, i):
        total = len(self.data["top_keywords"])
        max_page = max(0, (total - 1) // self.per_page)
        self.page = min(max_page, self.page + 1); self.rebuild_buttons()
        await i.response.edit_message(embed=self.build_embed(), view=self)
    async def last_page(self, i):
        total = len(self.data["top_keywords"])
        max_page = max(0, (total - 1) // self.per_page)
        self.page = max_page; self.rebuild_buttons()
        await i.response.edit_message(embed=self.build_embed(), view=self)


class SimplePaginator(discord.ui.View):
    def __init__(self, keyword, items, title_prefix, color, per_page=10):
        super().__init__(timeout=180)
        self.keyword = keyword; self.items = items
        self.title_prefix = title_prefix; self.color = color
        self.per_page = per_page; self.page = 0
        self.max_page = max(0, (len(items) - 1) // per_page)
        self.rebuild()

    def rebuild(self):
        self.clear_items()
        first = discord.ui.Button(label="⏮️", style=discord.ButtonStyle.secondary, disabled=(self.page == 0))
        first.callback = self.first_page; self.add_item(first)
        prev = discord.ui.Button(label="◀️", style=discord.ButtonStyle.primary, disabled=(self.page == 0))
        prev.callback = self.prev_page; self.add_item(prev)
        ind = discord.ui.Button(label=f"Page {self.page+1}/{self.max_page+1}",
                                style=discord.ButtonStyle.secondary, disabled=True)
        self.add_item(ind)
        nxt = discord.ui.Button(label="▶️", style=discord.ButtonStyle.primary, disabled=(self.page >= self.max_page))
        nxt.callback = self.next_page; self.add_item(nxt)
        last = discord.ui.Button(label="⏭️", style=discord.ButtonStyle.secondary, disabled=(self.page >= self.max_page))
        last.callback = self.last_page; self.add_item(last)

    def build_embed(self):
        start = self.page * self.per_page
        end = start + self.per_page
        chunk = self.items[start:end]
        embed = discord.Embed(title=f"{self.title_prefix}: `{self.keyword}`",
                              description=f"Showing **{start+1}–{min(end, len(self.items))}** of **{len(self.items)}**.",
                              color=self.color)
        for i, (w, af, c, sc) in enumerate(chunk, start + 1):
            embed.add_field(name=f"{i}. {w}",
                            value=f"Score: **{sc:,.0f}** | AvgFav: **{af:,.0f}** | Comp: **{c:,}**",
                            inline=False)
        embed.set_footer(text=f"Page {self.page+1} of {self.max_page+1}")
        return embed

    async def first_page(self, i):
        self.page = 0; self.rebuild()
        await i.response.edit_message(embed=self.build_embed(), view=self)
    async def prev_page(self, i):
        self.page = max(0, self.page - 1); self.rebuild()
        await i.response.edit_message(embed=self.build_embed(), view=self)
    async def next_page(self, i):
        self.page = min(self.max_page, self.page + 1); self.rebuild()
        await i.response.edit_message(embed=self.build_embed(), view=self)
    async def last_page(self, i):
        self.page = self.max_page; self.rebuild()
        await i.response.edit_message(embed=self.build_embed(), view=self)


class GuideNav(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)
        self.choice = None

    def _disable_all(self):
        for c in self.children:
            try: c.disabled = True
            except Exception: pass

    async def _handle(self, interaction: discord.Interaction, choice: str):
        self.choice = choice
        self._disable_all()
        try:
            await interaction.response.edit_message(view=self)
        except discord.errors.InteractionResponded:
            pass
        except Exception as e:
            print(f"⚠️ Interaction edit failed: {e}", flush=True)
            try: await interaction.response.defer()
            except Exception: pass
        self.stop()

    @discord.ui.button(label="▶ Continue", style=discord.ButtonStyle.success, row=0)
    async def cont(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle(interaction, "continue")

    @discord.ui.button(label="⏭ Skip to Strategy", style=discord.ButtonStyle.secondary, row=0)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle(interaction, "skip")

    @discord.ui.button(label="⏹ Stop", style=discord.ButtonStyle.danger, row=0)
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle(interaction, "stop")


async def ask_nav(ctx, prompt, timeout=600):
    nav = GuideNav()
    try:
        msg = await ctx.send(prompt, view=nav)
    except Exception as e:
        print(f"⚠️ Nav send failed: {e}", flush=True)
        return "continue"
    try:
        await asyncio.wait_for(nav.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            for c in nav.children: c.disabled = True
            await msg.edit(view=nav)
        except Exception: pass
        return "continue"
    return nav.choice or "continue"
