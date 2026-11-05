"""commands_emote.py — Emote Reference Title Engine command."""
import re

from execution_policy import to_thread_cancellable

URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def split_args(args):
    """Split "description [url]" into (description, url)."""
    text = (args or "").strip()
    m = URL_RE.search(text)
    url = m.group(0) if m else None
    description = re.sub(r"\s+", " ", URL_RE.sub(" ", text)).strip()
    return description, url


def register_emote_commands(bot, get_db):
    @bot.command(name="emote_title")
    async def emote_title_cmd(ctx, *, args: str = ""):
        """!emote_title <description> [optional TikTok URL]"""
        from emote_title_engine import generate, format_report

        description, url = split_args(args)
        if not description:
            return await ctx.send(
                "Usage: `!emote_title <description> [optional TikTok URL]`\n"
                "Example: `!emote_title a dreamy fairy that floats and glows "
                "softly`"
            )

        progress = await ctx.send("🧪 Building validated emote titles…")

        def _run():
            return generate(description, url=url)

        result, timed_out, err = await to_thread_cancellable("emote_title", _run)
        if timed_out:
            return await progress.edit(content=(
                "⏱️ Emote title generation exceeded its research budget; no "
                "result was fabricated."
            ))
        if err is not None:
            return await progress.edit(
                content=f"❌ {type(err).__name__}: {err}")

        try:
            body = format_report(result)
        except Exception as e:
            return await progress.edit(content=f"❌ {e}")

        try:
            await progress.delete()
        except Exception:
            pass
        for chunk in [body[i:i + 1900] for i in range(0, len(body), 1900)]:
            await ctx.send(chunk)
