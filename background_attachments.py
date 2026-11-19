"""Validate a Discord background image from its bytes, not attachment metadata.

Discord may omit content_type or report application/octet-stream for an
otherwise valid JPEG/PNG. A Discord preview is not proof of a supported MIME.
No decoding, file writes, network requests, or trusting filenames required.
"""
MAX_BACKGROUND_BYTES = 8 * 1024 * 1024

def detect_background_image_mime(payload):
    """Return a supported canonical MIME from a bounded image magic header.

    Reject extension-only, metadata-only, and unsupported image formats.
    The caller enforces the size cap before invoking a model.
    """
    if not isinstance(payload, bytes) or not payload:
        return None
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if payload.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if payload.startswith(b"BM") and len(payload) >= 14:
        return "image/bmp"
    if (len(payload) >= 12 and payload[:4] == b"RIFF"
            and payload[8:12] == b"WEBP"):
        return "image/webp"
    return None
