"""Discord image-upload regressions for the observed Rapture rejection.

Tests exercise the actual command callback, no real Discord, AI, market API,
or DB writes. Exact header recognition matters because Discord sometimes
omits content_type even when an image preview is visible.
"""
import asyncio
from types import SimpleNamespace
from unittest import mock

from background_attachments import detect_background_image_mime, MAX_BACKGROUND_BYTES
import commands_ai


JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 12
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
WEBP = b"RIFF" + (12).to_bytes(4, "little") + b"WEBP" + b"VP8 "
BMP = b"BM" + b"\x00" * 18
NOTES = ("BioShock Rapture-inspired underwater city observation room. "
         "Massive panoramic window overlooking underwater skyscrapers "
         "and amber lights.")


class Attachment:
    def __init__(self, data, content_type=None, filename="Final.jpg", size=None):
        self.content_type = content_type
        self.filename = filename
        self.size = len(data) if size is None else size
        self._data = data

    async def read(self):
        return self._data


class FakeBot:
    def __init__(self):
        self.callbacks = {}

    def command(self, name=None, **kwargs):
        def register(handler):
            self.callbacks[name] = handler
            return handler
        return register


class Channel:
    def __init__(self):
        self.messages = []

    async def send(self, message=None, **kwargs):
        self.messages.append(message)


def execute(attachments, notes=NOTES, vision=None):
    bot = FakeBot()
    commands_ai.register_ai_commands(bot)
    channel = Channel()
    ctx = SimpleNamespace(
        message=SimpleNamespace(attachments=attachments),
        channel=channel, send=channel.send, vanta_state=None)
    checked_images = []
    searches = []

    def fake_vision(images, *_args, **_kwargs):
        checked_images.extend(images)
        return vision if vision is not None else {
            "visual_summary": "Underwater city observation room",
            "search_description": "underwater city",
            "distinctive_features": ["panoramic window", "amber lights"],
        }

    def search(query, family, *args):
        searches.append((query, family))
        return {"ok": False, "keyword": query, "error": "HTTP 429"}

    with (mock.patch.object(commands_ai, "is_available", return_value=True),
          mock.patch.object(commands_ai, "analyze_image_for_ugc", side_effect=fake_vision),
          mock.patch("convergence_live.verify_niche", side_effect=search),
          mock.patch("background_opportunities.lookup_background_opportunities",
                     return_value={"status": "unavailable", "angles": []}),
          mock.patch("category_creator_learning.lookup_creator_learning",
                     return_value={"status": "insufficient", "patterns": []}),
          mock.patch("gemini_brain._generate", return_value=None)):
        asyncio.run(bot.callbacks["background_analyze"](ctx, notes=notes))
    return "\n".join(str(m) for m in channel.messages), checked_images, searches


def test_image_signature_recognizer():
    assert detect_background_image_mime(JPEG) == "image/jpeg"
    assert detect_background_image_mime(PNG) == "image/png"
    assert detect_background_image_mime(WEBP) == "image/webp"
    assert detect_background_image_mime(BMP) == "image/bmp"
    for candidate in (b"garbage", b"", b"<svg></svg>", b"GIF89a",
                      b"notreallyjpeg"):
        assert detect_background_image_mime(candidate) is None
    assert detect_background_image_mime(bytearray(JPEG)) is None


def test_discord_jpg_with_no_mime_is_processed():
    rendered, images, searches = execute([Attachment(JPEG, None, "Final.jpg")])
    assert images and all(x["mime"] == "image/jpeg" for x in images), images
    assert searches and searches[0][1] == "backgrounds", searches
    assert "Attach a PNG" not in rendered
    assert "ROBLOX BACKGROUND SEARCH INTELLIGENCE" in rendered


def test_discord_octet_stream_and_mismatched_mime_are_processed():
    for raw_type, bytes_, wanted in [
        ("application/octet-stream", JPEG, "image/jpeg"),
        ("IMAGE/PNG", PNG, "image/png"),
        ("image/webp", WEBP, "image/webp"),
        ("image/png", JPEG, "image/jpeg"),
    ]:
        rendered, images, _ = execute([Attachment(bytes_, raw_type)])
        assert images and images[0]["mime"] == wanted, (raw_type, rendered)
        assert "Attach a PNG" not in rendered


def test_invalid_image_with_notes_falls_back_to_text_research():
    rendered, images, searches = execute([Attachment(b"not an image", None)])
    assert not images
    assert searches and searches[0][1] == "backgrounds"
    assert "Continuing from your written scene details only" in rendered
    assert "creator_notes_only" in rendered
    assert "ROBLOX BACKGROUND SEARCH INTELLIGENCE" in rendered


def test_invalid_image_without_grounded_text_gives_actionable_message():
    rendered, images, searches = execute(
        [Attachment(b"not an image")], notes="best viral title 100x CTR")
    assert not images and not searches
    assert "No supported image could be read" in rendered
    assert "Attach a PNG, JPEG, BMP or WebP under 8 MB" in rendered


def test_size_limit_and_multiple_files():
    rendered, images, searches = execute([
        Attachment(JPEG, size=MAX_BACKGROUND_BYTES + 1),
        Attachment(PNG, content_type=None, filename="backup.png")])
    assert images and all(x["mime"] == "image/png" for x in images)
    assert searches
    rendered, images, searches = execute([
        Attachment(JPEG, size=MAX_BACKGROUND_BYTES + 1)])
    assert not images and searches
    assert "over 8 MB" in rendered


if __name__ == "__main__":
    test_image_signature_recognizer()
    test_discord_jpg_with_no_mime_is_processed()
    test_discord_octet_stream_and_mismatched_mime_are_processed()
    test_invalid_image_with_notes_falls_back_to_text_research()
    test_invalid_image_without_grounded_text_gives_actionable_message()
    test_size_limit_and_multiple_files()
    print("PASS Discord JPEG/PNG/WebP attachment detection and scene-only fallback")
