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

# Font preference: Liberation Sans is metric-compatible with Arial/Helvetica.
_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/Arial.ttf",
)

# Many BOL/ticket forms (older dot-matrix printers, POS/route tickets like
# USPS PS Form 5398-A) use a monospaced typewriter-style font instead of a
# proportional one. Liberation Mono is metric-compatible with Courier New.
_MONO_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "C:/Windows/Fonts/consola.ttf",
    "C:/Windows/Fonts/cour.ttf",
)

_SANS_BOLD_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
)
_MONO_BOLD_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "C:/Windows/Fonts/consolab.ttf",
    "C:/Windows/Fonts/courbd.ttf",
)


def _load_font_family(paths: Tuple[str, ...], fontsize: int) -> "ImageFont.FreeTypeFont":
    for path in paths:
        try:
            return ImageFont.truetype(path, fontsize)
        except Exception:
            continue
    return ImageFont.load_default()


def _load_bol_font(fontsize: int) -> "ImageFont.FreeTypeFont":
    return _load_font_family(_FONT_CANDIDATES, fontsize)


def _text_width(font: "ImageFont.FreeTypeFont", text: str) -> float:
    try:
        return font.getlength(text)
    except AttributeError:  # pragma: no cover - old Pillow fallback
        bbox = font.getbbox(text)
        return bbox[2] - bbox[0]


def _fit_font_to_box(
    paths: Tuple[str, ...], text: str, box_width: float, box_height: float
) -> "ImageFont.FreeTypeFont":
    """Load the first available font from ``paths`` at the point size whose
    RENDERED glyph height fills ``box_height``.

    A TrueType nominal point size includes ascender/descender headroom, so
    text drawn at ``fontsize == box_height`` comes out visibly smaller than
    the original ink it replaces. Measure the actual glyph bbox at a
    reference size and scale, capping so the string can't overflow the
    table cell horizontally by more than ~15%.
    """
    ref = 100
    font = _load_font_family(paths, ref)
    if not text or not hasattr(font, "getbbox"):
        return font
    bbox = font.getbbox(text)
    glyph_h = bbox[3] - bbox[1]
    glyph_w = bbox[2] - bbox[0]
    if glyph_h <= 0 or glyph_w <= 0:
        return font
    size = ref * box_height / glyph_h
    if box_width > 0:
        size = min(size, ref * (box_width * 1.15) / glyph_w)
    return _load_font_family(paths, max(8, int(round(size))))


def _ink_ratio(gray: Image.Image) -> float:
    """Fraction of dark (< 128) pixels — a proxy for stroke weight."""
    hist = gray.histogram()
    total = sum(hist)
    return sum(hist[:128]) / total if total else 0.0


def _rendered_ink_ratio(font: "ImageFont.FreeTypeFont", text: str) -> float:
    bbox = font.getbbox(text)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    if w <= 0 or h <= 0:
        return 0.0
    from PIL import ImageDraw

    canvas = Image.new("L", (w, h), 255)
    ImageDraw.Draw(canvas).text((-bbox[0], -bbox[1]), text, fill=0, font=font)
    return _ink_ratio(canvas)


def _pick_replacement_font(
    img: Image.Image,
    box: Tuple[int, int, int, int],
    new_text: str,
    old_text: str = "",
    mono_hint: Optional[bool] = None,
) -> "ImageFont.FreeTypeFont":
    """Choose the font that best matches the ORIGINAL ink inside ``box``.

    Family (mono vs. proportional): ``mono_hint`` (Claude's judgement of
    the print style) wins when available, because the width heuristic
    flip-flops with a few pixels of bbox noise and then the same value
    gets two different fonts in one document. Without a hint, pick the
    family that renders ``old_text`` (the string actually occupying the
    box) at a width closest to the box. Weight (regular vs. bold) is
    picked by which one's rendered ink density is closest to the original
    crop's — dot-matrix/typewriter BOL forms print heavy strokes that a
    regular font visibly fails to match.
    """
    x0, y0, x1, y1 = box
    box_w, box_h = x1 - x0, y1 - y0
    # Detected boxes carry a little padding around the glyphs.
    target_h = box_h * 0.88

    regular = (_FONT_CANDIDATES, _MONO_FONT_CANDIDATES)
    bold = (_SANS_BOLD_FONT_CANDIDATES, _MONO_BOLD_FONT_CANDIDATES)
    if mono_hint is not None:
        fam = 1 if mono_hint else 0
    else:
        ref_text = old_text or new_text
        fitted = [_fit_font_to_box(p, ref_text, box_w, target_h) for p in regular]
        diffs = [abs(_text_width(f, ref_text) - box_w) for f in fitted]
        # Prefer mono on a near-tie: these forms are usually typewriter print.
        fam = 1 if diffs[1] <= diffs[0] * 1.15 else 0

    orig_ink = _ink_ratio(img.crop((x0, y0, x1, y1)).convert("L"))
    candidates = [
        _fit_font_to_box(regular[fam], new_text, box_w, target_h),
        _fit_font_to_box(bold[fam], new_text, box_w, target_h),
    ]
    return min(
        candidates,
        key=lambda f: abs(_rendered_ink_ratio(f, new_text) - orig_ink),
    )


def _grow_whiteout_x(
    img: Image.Image, x0: int, y0: int, x1: int, y1: int
) -> Tuple[int, int]:
    """Stretch the white-out sideways over glyph fragments of the ORIGINAL
    value that stick out past the detected box (bbox noise), so no stray
    half-digits survive the edit. Growth stops at table borders (columns
    dark across nearly the full band height), across gaps wider than a
    character space, and after 20% of the box width on each side.
    """
    band_h = y1 - y0
    if band_h <= 0:
        return x0, x1
    max_grow = max(4, (x1 - x0) // 5)
    max_gap = max(3, int(band_h * 0.6))

    def dark_frac(x: int) -> float:
        col = img.crop((x, y0, x + 1, y1)).convert("L")
        return sum(col.histogram()[:128]) / band_h

    def grow(start: int, step: int) -> int:
        grown, gap, cur = start, 0, start
        for _ in range(max_grow):
            nxt = cur + step
            if nxt < 0 or nxt >= img.width:
                break
            frac = dark_frac(nxt)
            if frac > 0.9:  # table border — never erase it
                break
            if frac >= 0.05:
                grown, gap = nxt, 0
            else:
                gap += 1
                if gap > max_gap:
                    break
            cur = nxt
        return grown

    return grow(x0, -1), grow(x1 - 1, +1) + 1


def _draw_replacement(
    img: Image.Image,
    box: Tuple[int, int, int, int],
    new_text: str,
    old_text: str = "",
    mono_hint: Optional[bool] = None,
) -> None:
    """White-out ``box`` and draw ``new_text`` sized, weighted and aligned
    to match the original ink as closely as possible."""
    from PIL import ImageDraw

    x0, y0, x1, y1 = box
    font = _pick_replacement_font(img, box, new_text, old_text, mono_hint)
    wx0, wx1 = _grow_whiteout_x(img, x0, y0, x1, y1)
    draw = ImageDraw.Draw(img)
    draw.rectangle([wx0 - 2, y0 - 2, wx1 + 2, y1 + 2], fill="white")
    bbox = font.getbbox(new_text)
    glyph_h = bbox[3] - bbox[1]
    tx = x0 - bbox[0]
    ty = y0 + ((y1 - y0) - glyph_h) / 2 - bbox[1]
    draw.text((tx, ty), new_text, fill="black", font=font)


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


def _best_matching_fontname(text: str, fontsize: float, target_width: float) -> str:
    """Pick "helv" (proportional) vs "cour" (monospace) — both built into
    PyMuPDF, no font file needed — whichever renders ``text`` closest to
    ``target_width``. Same width-matching idea as ``_best_matching_font``,
    for the vector text-PDF path.
    """
    if not text or target_width <= 0:
        return "helv"
    best_name, best_diff = "helv", None
    for name in ("helv", "cour"):
        w = fitz.get_text_length(text, fontname=name, fontsize=fontsize)
        diff = abs(w - target_width)
        if best_diff is None or diff < best_diff:
            best_name, best_diff = name, diff
    return best_name


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
        fontname = _best_matching_fontname(new_text, fontsize, rect.width)
        page.insert_text(
            (rect.x0, rect.y1 - rect.height * 0.22),
            new_text,
            fontsize=fontsize,
            fontname=fontname,
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
        n = len(words)
        word_boxes = [
            (words[i], ocr_data["left"][i], ocr_data["top"][i],
             ocr_data["width"][i], ocr_data["height"][i])
            for i in range(n) if words[i].strip()
        ]

        # Tesseract's own block/paragraph/line grouping under --psm 6
        # assumes a single uniform block of text. On dense multi-column
        # BOL/ticket forms (label table on the left, another table on the
        # right at the same row height) this routinely bleeds across
        # columns and produces a scrambled reading order — words from
        # unrelated, far-apart fields end up adjacent in ``full_text``.
        # Re-derive top-to-bottom / left-to-right order directly from each
        # word's own pixel position instead of trusting that order.
        word_boxes = _sort_words_reading_order(word_boxes)
        clean_words = [w[0] for w in word_boxes]
        full_text = " ".join(clean_words)

        candidates = find_datetime_candidates(full_text)
        if not candidates:
            continue

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


def _sort_words_reading_order(
    word_boxes: List[Tuple[str, int, int, int, int]],
) -> List[Tuple[str, int, int, int, int]]:
    """Re-order OCR word boxes into true top-to-bottom, left-to-right order.

    Each box is ``(text, left, top, width, height)``. Words are clustered
    into rows by vertical-center proximity (not by Tesseract's block/line
    numbers, which can be wrong on multi-column layouts), then each row is
    sorted left-to-right and rows are sorted top-to-bottom.
    """
    if not word_boxes:
        return []

    rows: List[dict] = []
    for wb in sorted(word_boxes, key=lambda b: b[2]):  # by top, coarse pass
        _, _left, top, _width, height = wb
        cy = top + height / 2
        best_row = None
        for row in rows:
            if abs(cy - row["cy"]) <= max(height, row["height"]) * 0.6:
                best_row = row
                break
        if best_row is None:
            rows.append({"boxes": [wb], "cy": cy, "height": height})
        else:
            best_row["boxes"].append(wb)
            cnt = len(best_row["boxes"])
            best_row["cy"] = (best_row["cy"] * (cnt - 1) + cy) / cnt
            best_row["height"] = max(best_row["height"], height)

    rows.sort(key=lambda r: r["cy"])
    out: List[Tuple[str, int, int, int, int]] = []
    for row in rows:
        out.extend(sorted(row["boxes"], key=lambda b: b[1]))
    return out


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
    img = page_images[candidate.page_index]
    if not candidate.rects:
        return
    x0 = min(r.x0 for r in candidate.rects)
    y0 = min(r.y0 for r in candidate.rects)
    x1 = max(r.x1 for r in candidate.rects)
    y1 = max(r.y1 for r in candidate.rects)
    _draw_replacement(
        img, (int(x0), int(y0), int(x1), int(y1)), new_text,
        old_text=candidate.tm.raw_text,
    )


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
    from bol_bot.core.vision_engine import candidate_to_pixel_rect

    w, h = img.size
    box = candidate_to_pixel_rect(vision_candidate, w, h)
    _draw_replacement(
        img, box, new_text,
        old_text=vision_candidate.raw_text,
        mono_hint=getattr(vision_candidate, "is_monospace", None),
    )
