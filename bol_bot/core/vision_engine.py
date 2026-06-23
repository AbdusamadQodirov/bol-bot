"""Vision-based field detection via Anthropic Claude.

Used as a fallback when Tesseract OCR misses fields (typically because
the BOL has *handwritten* values written over the printed form).
Claude is asked to return all date/time-looking fields together with
their normalised bounding boxes (0-1000 coordinate space) and a flag
indicating whether each one is printed or handwritten.

The bbox coordinate system follows Anthropic's convention: integers
0..1000 on each axis, regardless of the actual image pixel size.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import re
from dataclasses import dataclass
from typing import List, Tuple

from PIL import Image

from bol_bot.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class VisionCandidate:
    """One date/time field detected by Claude in the page image."""

    raw_text: str           # the literal text as written (e.g. "06/19/26 14:30")
    context: str            # nearby label, e.g. "Ship Date", "Time In"
    is_handwritten: bool    # True if handwritten, False if printed
    # bbox in NORMALISED 0..1000 space (top-left origin) — Claude's convention
    x0: int
    y0: int
    x1: int
    y1: int
    confidence: float = 1.0  # 0..1

    def as_dict(self) -> dict:
        return {
            "raw_text": self.raw_text,
            "context": self.context,
            "is_handwritten": self.is_handwritten,
            "bbox": [self.x0, self.y0, self.x1, self.y1],
            "confidence": self.confidence,
        }


_PROMPT = """You are extracting date/time fields from a Bill of Lading (BOL) shipping document image.

Return a JSON array. Each element is one date/time value that appears in the document, with:
- "raw_text": the EXACT text as written (preserve spelling, punctuation, case)
- "context":  the nearby label / field name (e.g. "Ship Date", "Time In", "Pickup", "Shipper Signature Date", "Origin")
- "is_handwritten": true if the value looks hand-written, false if it's printed/typed
- "bbox": [x0, y0, x1, y1] — TIGHT bounding box around ONLY the value (not the label), as integers in 0..1000 coordinate space (top-left origin, x right, y down)
- "confidence": float 0..1 (your confidence this is a real date/time field)

Rules:
- Include BOTH printed and handwritten dates/times
- Include time ranges like "06:00-10:00" as a single field
- Include date+time pairs like "6/19/2026 14:30" as a single field
- Exclude: phone numbers, zip codes, PO numbers, document IDs, barcodes
- Exclude: dates clearly belonging to delivery / destination unless they are the only ones
- Make the bbox AS TIGHT AS POSSIBLE around the value — this is critical: we will OVERWRITE the box

Return ONLY the JSON array, no prose, no markdown fence."""


def _encode_image(img: Image.Image) -> Tuple[str, str]:
    """Return (media_type, base64-encoded data)."""
    buf = io.BytesIO()
    # Cap dimension at 1568 px (Claude's vision sweet spot) to keep payload small
    max_dim = 1568
    if max(img.size) > max_dim:
        ratio = max_dim / max(img.size)
        new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
        img = img.resize(new_size, Image.LANCZOS)
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return "image/png", base64.b64encode(buf.getvalue()).decode("ascii")


def _extract_json_array(text: str) -> list:
    """Pull the first JSON array out of Claude's reply (defensive)."""
    text = text.strip()
    # Strip ```json fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    # Find the outermost [...]
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"No JSON array in response: {text[:200]!r}")
    return json.loads(text[start : end + 1])


def find_vision_candidates(img: Image.Image) -> List[VisionCandidate]:
    """Call Claude vision and return parsed candidates.

    Raises RuntimeError if API key is missing or the call fails permanently.
    Returns [] (not an exception) if Claude saw the image but found nothing.
    """
    settings = get_settings()
    if not settings.enable_vision:
        return []
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured")

    try:
        import anthropic
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("anthropic package not installed") from e

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    media_type, b64 = _encode_image(img)

    logger.info("vision.request", extra={"model": settings.anthropic_model, "bytes": len(b64)})

    try:
        message = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": b64,
                            },
                        },
                        {"type": "text", "text": _PROMPT},
                    ],
                }
            ],
        )
    except Exception as e:
        logger.exception("vision.api_error")
        raise RuntimeError(f"Claude vision API error: {e}") from e

    text_blocks = [b.text for b in message.content if getattr(b, "type", "") == "text"]
    raw_reply = "\n".join(text_blocks)
    logger.debug("vision.reply", extra={"reply_len": len(raw_reply)})

    try:
        items = _extract_json_array(raw_reply)
    except (ValueError, json.JSONDecodeError) as e:
        logger.error("vision.parse_error", extra={"err": str(e), "reply": raw_reply[:500]})
        return []

    out: List[VisionCandidate] = []
    for it in items:
        try:
            bbox = it.get("bbox") or []
            if len(bbox) != 4:
                continue
            x0, y0, x1, y1 = (int(round(float(v))) for v in bbox)
            # Clamp to 0..1000
            x0 = max(0, min(1000, x0))
            y0 = max(0, min(1000, y0))
            x1 = max(0, min(1000, x1))
            y1 = max(0, min(1000, y1))
            if x1 <= x0 or y1 <= y0:
                continue
            out.append(
                VisionCandidate(
                    raw_text=str(it.get("raw_text", "")).strip(),
                    context=str(it.get("context", "")).strip(),
                    is_handwritten=bool(it.get("is_handwritten", False)),
                    x0=x0, y0=y0, x1=x1, y1=y1,
                    confidence=float(it.get("confidence", 1.0)),
                )
            )
        except (TypeError, ValueError) as e:
            logger.warning("vision.item_skip", extra={"err": str(e), "item": it})
            continue

    # Drop empty raw_text and very low confidence (< 0.3)
    out = [c for c in out if c.raw_text and c.confidence >= 0.3]
    logger.info("vision.parsed", extra={"count": len(out)})
    return out


def candidate_to_pixel_rect(
    cand: VisionCandidate, image_width: int, image_height: int
) -> Tuple[int, int, int, int]:
    """Convert a candidate's 0..1000 normalised bbox to pixel coordinates."""
    x0 = int(cand.x0 / 1000.0 * image_width)
    y0 = int(cand.y0 / 1000.0 * image_height)
    x1 = int(cand.x1 / 1000.0 * image_width)
    y1 = int(cand.y1 / 1000.0 * image_height)
    # Add 2 px safety padding so we definitely cover the original ink
    x0 = max(0, x0 - 2)
    y0 = max(0, y0 - 2)
    x1 = min(image_width, x1 + 2)
    y1 = min(image_height, y1 + 2)
    return x0, y0, x1, y1
