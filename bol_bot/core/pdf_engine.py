"""PDF/scan/image manipulation: detect candidates, redact, overlay.

Improvements over v1:
- Multi-page text and scanned PDFs are fully supported (vision still
  processes one page at a time, but the user can pick the page).
- ``replace_text_in_pdf`` tries to match the original font size by
  measuring the redacted rectangle and snapping to a sensible point size.
- ``preprocess_for_ocr`` is applied before Tesseract on scanned pages.
- ``is_scanned_pdf`` performs per-page checks (any page with very little
  text triggers fallback) so we don't get fooled by a metadata page.
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

import fitz  # PyMuPDF
import pytesseract
from PIL import Image, ImageFont

from bol_bot.config import get_settings
from bol_bot.utils.datetime_utils import TimeMatch, find_datetime_candidates
from bol_bot.utils.document_scanner import preprocess_for_ocr

logger = logging.getLogger(__name__)

# Font preference: Liberation Sans is metric-compatible with Arial/Helvetica
_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/Arial.ttf",
)


def _load_bol_font(fontsize: int) -> "ImageFont.FreeTypeFont":
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, fontsize)
        except Exception:
            continue
    return ImageFont.load_default()


@dataclass
class PageCandidate:
    page_index: int
    tm: TimeMatch
    rects: List["fitz.Rect"]
    context: str
    is_scanned: bool


def is_scanned_pdf(doc: "fitz.Document") -> bool:
    """A PDF is considered 'scanned' if ANY page is image-only.

    The original heuristic looked at the whole document total — a single
    text-heavy cover page could mask scanned BOL pages. Now we treat the
    document as scanned if at least one page has <20 chars of real text.
    """
    if doc.page_count == 0:
        return True
    for page in doc:
        if len(page.get_text("text").strip()) < 20:
            return True
    return False


def _get_context(full_text: str, start: int, end: int, radius: int = 30) -> str:
    s = max(0, start - radius)
    e = min(len(full_text), end + radius)
    return full_text[s:e].replace("\n", " ").strip()


# ---------------------------------------------------------------------------
# TEXT-PDF mode
# ---------------------------------------------------------------------------

def extract_text_candidates(doc: "fitz.Document") -> List[PageCandidate]:
    """Find date/time candidates across ALL pages of a text-PDF."""
    results: List[PageCandidate] = []
    for page_idx, page in enumerate(doc):
        full_text = page.get_text("text")
        for tm in find_datetime_candidates(full_text):
            all_rects = page.search_for(tm.raw_text)
            if not all_rects:
                continue
            # ``search_for`` returns EVERY occurrence of this exact string
            # on the page, in the same top-to-bottom/left-to-right order
            # the text scan encounters them. When the same date/time text
            # is printed under two different labels (e.g. a "Ship Date"
            # that happens to match a "Signature Date"), we must pick only
            # the rect for THIS occurrence — otherwise every occurrence on
            # the page gets overwritten with the new value.
            occurrence_index = full_text.count(tm.raw_text, 0, tm.start)
            occurrence_index = min(occurrence_index, len(all_rects) - 1)
            rects = [all_rects[occurrence_index]]
            ctx = _get_context(full_text, tm.start, tm.end)
            results.append(PageCandidate(
                page_index=page_idx, tm=tm, rects=rects, context=ctx, is_scanned=False
            ))
    return results


def _measure_fontsize(rect: "fitz.Rect") -> float:
    """Snap rect-height-derived size to common BOL font sizes."""
    raw = rect.height * 0.72
    for canonical in (8.0, 9.0, 10.0, 11.0, 12.0, 14.0):
        if abs(raw - canonical) < 0.6:
            return canonical
    return max(6.0, min(14.0, raw))


def replace_text_in_pdf(
    doc: "fitz.Document", candidate: PageCandidate, new_text: str
) -> None:
    page = doc[candidate.page_index]
    rect_list = list(candidate.rects)
    for rect in rect_list:
        page.add_redact_annot(rect, fill=(1, 1, 1))
    page.apply_redactions()
    for rect in rect_list:
        fontsize = _measure_fontsize(rect)
        page.insert_text(
            (rect.x0, rect.y1 - rect.height * 0.22),
            new_text,
            fontsize=fontsize,
            fontname="helv",
            color=(0, 0, 0),
        )


# ---------------------------------------------------------------------------
# Scanned-PDF mode (OCR)
# ---------------------------------------------------------------------------

def page_to_image(page: "fitz.Page", zoom: float = 3.0) -> Image.Image:
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def extract_ocr_candidates(
    doc: "fitz.Document",
) -> Tuple[List[PageCandidate], List[Image.Image]]:
    settings = get_settings()
    results: List[PageCandidate] = []
    page_images: List[Image.Image] = []

    for page_idx, page in enumerate(doc):
        img = page_to_image(page, zoom=3.0)
        page_images.append(img)
        preprocessed = preprocess_for_ocr(img)

        ocr_data = pytesseract.image_to_data(
            preprocessed,
            output_type=pytesseract.Output.DICT,
            lang=settings.tesseract_lang,
            config="--oem 3 --psm 6",
        )
        words = ocr_data["text"]
        full_text = " ".join(w for w in words if w.strip())
        candidates = find_datetime_candidates(full_text)
        if not candidates:
            continue

        n = len(words)
        word_boxes = [
            (words[i], ocr_data["left"][i], ocr_data["top"][i],
             ocr_data["width"][i], ocr_data["height"][i])
            for i in range(n) if words[i].strip()
        ]
        clean_words = [w[0] for w in word_boxes]

        # Map each word's index to its character offset in ``full_text`` so
        # that a candidate's ``tm.start`` can be matched to the OCR word it
        # actually came from. Without this, a raw_text that repeats
        # elsewhere on the page (e.g. the same date/time printed in two
        # fields) would always resolve to the FIRST occurrence, silently
        # overwriting the wrong field.
        word_char_starts = []
        pos = 0
        for w in clean_words:
            word_char_starts.append(pos)
            pos += len(w) + 1

        for tm in candidates:
            target_words = tm.raw_text.split()
            expected_index = _word_index_for_char_offset(word_char_starts, tm.start)
            match_start = _find_word_sequence(clean_words, target_words, expected_index)
            if match_start is None:
                continue
            boxes = word_boxes[match_start : match_start + len(target_words)]
            rects = [
                fitz.Rect(left, top, left + width, top + height)
                for (_, left, top, width, height) in boxes
            ]
            ctx = _get_context(full_text, tm.start, tm.end)
            results.append(PageCandidate(
                page_index=page_idx, tm=tm, rects=rects, context=ctx, is_scanned=True
            ))

    return results, page_images


def _word_index_for_char_offset(word_char_starts: List[int], char_offset: int) -> int:
    """Return the index of the OCR word that contains ``char_offset``.

    ``word_char_starts[i]`` is where word ``i`` begins in the joined
    ``full_text`` string. Finds the last word starting at or before the
    offset.
    """
    lo, hi = 0, len(word_char_starts) - 1
    best = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        if word_char_starts[mid] <= char_offset:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _find_word_sequence(
    haystack: List[str], needle: List[str], expected_index: Optional[int] = None
) -> Optional[int]:
    """Find where ``needle`` occurs in ``haystack``.

    ``needle`` (the matched raw_text) can occur more than once on a page —
    e.g. the same date/time printed under two different labels. When that
    happens, pick the occurrence closest to ``expected_index`` (the word
    position the candidate was actually detected at) instead of always the
    first one, otherwise the wrong field gets overwritten.
    """
    def norm(w: str) -> str:
        return w.strip().strip(",.").lower()
    needle_n = [norm(w) for w in needle]
    hl, nl = len(haystack), len(needle_n)
    matches = [
        i for i in range(hl - nl + 1)
        if [norm(haystack[i + j]) for j in range(nl)] == needle_n
    ]
    if not matches:
        return None
    if expected_index is None:
        return matches[0]
    return min(matches, key=lambda i: abs(i - expected_index))


def replace_text_in_scanned_pdf(
    page_images: List[Image.Image],
    candidate: PageCandidate,
    new_text: str,
) -> None:
    from PIL import ImageDraw

    img = page_images[candidate.page_index]
    draw = ImageDraw.Draw(img)
    if not candidate.rects:
        return
    x0 = min(r.x0 for r in candidate.rects)
    y0 = min(r.y0 for r in candidate.rects)
    x1 = max(r.x1 for r in candidate.rects)
    y1 = max(r.y1 for r in candidate.rects)
    draw.rectangle([x0 - 2, y0 - 2, x1 + 2, y1 + 2], fill="white")
    height = y1 - y0
    fontsize = max(10, int(height * 0.85))
    font = _load_bol_font(fontsize)
    draw.text((x0, y0), new_text, fill="black", font=font)


def images_to_pdf_bytes(page_images: List[Image.Image]) -> bytes:
    buf = io.BytesIO()
    if not page_images:
        return b""
    page_images[0].save(
        buf, format="PDF", save_all=True, append_images=page_images[1:]
    )
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Vision overlay (numbered red boxes on top of the page image)
# ---------------------------------------------------------------------------

def draw_numbered_overlay(img: Image.Image, vision_candidates: list) -> Image.Image:
    from PIL import ImageDraw

    from bol_bot.core.vision_engine import candidate_to_pixel_rect

    out = img.copy().convert("RGB")
    draw = ImageDraw.Draw(out)
    w, h = out.size
    font = _load_bol_font(max(18, h // 80))

    for idx, cand in enumerate(vision_candidates, start=1):
        x0, y0, x1, y1 = candidate_to_pixel_rect(cand, w, h)
        draw.rectangle([x0, y0, x1, y1], outline="red", width=3)
        label = str(idx)
        bbox = draw.textbbox((0, 0), label, font=font)
        label_w = bbox[2] - bbox[0]
        label_h = bbox[3] - bbox[1]
        badge_size = max(label_w, label_h) + 14
        bx0 = max(0, x0 - badge_size - 2)
        by0 = max(0, y0)
        bx1 = bx0 + badge_size
        by1 = by0 + badge_size
        draw.ellipse([bx0, by0, bx1, by1], fill="red", outline="white", width=2)
        tx = bx0 + (badge_size - label_w) / 2 - bbox[0]
        ty = by0 + (badge_size - label_h) / 2 - bbox[1]
        draw.text((tx, ty), label, fill="white", font=font)
    return out


def replace_vision_candidate_in_image(
    img: Image.Image, vision_candidate, new_text: str
) -> None:
    from PIL import ImageDraw

    from bol_bot.core.vision_engine import candidate_to_pixel_rect

    draw = ImageDraw.Draw(img)
    w, h = img.size
    x0, y0, x1, y1 = candidate_to_pixel_rect(vision_candidate, w, h)
    draw.rectangle([x0, y0, x1, y1], fill="white")
    box_height = y1 - y0
    fontsize = max(10, int(box_height * 0.78))
    font = _load_bol_font(fontsize)
    draw.text((x0 + 2, y0 + (box_height * 0.08)), new_text, fill="black", font=font)
