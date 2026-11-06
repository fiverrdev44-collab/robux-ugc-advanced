"""Discord adapter for the M4 original UGC concept engine."""
from execution_policy import to_thread_cancellable

from original_concept_engine import (
    SUPPORTED_CATEGORY_TEXT,
    category_label,
    m4_enabled,
    render_concept_request,
    resolve_concept_category,
)


def register_concept_commands(bot, get_db):
    @bot.command(name="concept")
    async def concept_cmd(ctx, *, text: str = ""):
        """!concept <category> | <creative request>"""
        if not m4_enabled():
            await ctx.send(
                "⚠️ M4 original concept generation is disabled "
                "(`PHASE2_M4_ENABLED=0`).")
            return
        if "|" not in (text or ""):
            await ctx.send(
                "Usage: `!concept <category> | <creative request>`\n"
                f"Supported categories: {SUPPORTED_CATEGORY_TEXT}")
            return
        raw_category, request = text.split("|", 1)
        raw_category = raw_category.strip().lower()
        request = request.strip()
        if raw_category == "accessory":
            await ctx.send(
                "Choose a specific accessory category: neck, shoulder, "
                "front, back, or waist.")
            return
        category = resolve_concept_category(raw_category)
        if category is None:
            await ctx.send(
                f"❌ Unsupported category `{raw_category}`. "
                f"Supported: {SUPPORTED_CATEGORY_TEXT}.")
            return
        if not request:
            await ctx.send(
                "Usage: `!concept <category> | <creative request>`")
            return

        await ctx.send(
            f"🎨 Generating up to three original {category_label(category)} "
            "concepts from stored evidence; no live marketplace scan will "
            "run...")

        def _run():
            return render_concept_request(category, request, get_db)

        body, timed_out, err = await to_thread_cancellable("concept", _run)
        if timed_out:
            await ctx.send(
                "⏱️ Concept generation exceeded its research budget; no "
                "concept was fabricated. Re-run with a narrower request.")
            return
        if err is not None:
            await ctx.send(f"❌ {err}")
            return
        for chunk in [body[i:i + 1900] for i in range(0, len(body), 1900)]:
            await ctx.send(chunk)
