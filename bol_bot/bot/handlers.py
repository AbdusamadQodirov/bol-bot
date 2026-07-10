"""Telegram conversation handlers — the user-facing flow.

State machine (same as v1, with two additions):
  WAITING_FILE → [CHOOSING_PAGE] → CHOOSING_FIELD → CHOOSING_TIMEZONE
    → CHOOSING_MONTH → CHOOSING_YEAR → WAITING_NEW_TIME → CONFIRMING
    → [back to CHOOSING_FIELD for multi-edit]
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta
from io import BytesIO
from typing import Optional

import fitz
from PIL import Image
from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update,
)
from telegram.ext import ContextTypes, ConversationHandler

from bol_bot.bot.access import check_access
from bol_bot.bot.format_vision import (
    format_like_vision_text, quick_parse_full_datetime, quick_parse_time_text,
)
from bol_bot.config import get_settings
from bol_bot.core.pdf_engine import (
    draw_numbered_overlay, extract_ocr_candidates, extract_text_candidates,
    images_to_pdf_bytes, is_scanned_pdf, page_to_image,
    replace_text_in_pdf, replace_text_in_scanned_pdf,
    replace_vision_candidate_in_image,
)
from bol_bot.core.vision_engine import find_vision_candidates
from bol_bot.locales import t
from bol_bot.storage import log_edit
from bol_bot.utils.datetime_utils import (
    format_like_original, looks_like_pickup_group_label,
    looks_like_time_in_label, looks_like_time_out_label,
    matches_datetime_value,
)
from bol_bot.utils.document_scanner import auto_crop_document, auto_rotate_document
from bol_bot.utils.timezone_utils import (
    convert_between_timezones, guess_state_code_from_text, iana_to_abbr,
    state_code_to_iana,
)

logger = logging.getLogger(__name__)

(
    WAITING_FILE, CHOOSING_PAGE, CHOOSING_FIELD, CHOOSING_TIMEZONE,
    CHOOSING_MONTH, CHOOSING_YEAR, WAITING_NEW_TIME, CONFIRMING,
) = range(8)

_TIMEZONE_OPTIONS = ["EDT", "CDT", "MDT", "PDT"]
_MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

_ACTIVE_KB = ReplyKeyboardMarkup([["⏹ Stop"]], resize_keyboard=True)
_INACTIVE_KB = ReplyKeyboardMarkup([["▶️ Start"]], resize_keyboard=True)


def _lang(ctx: ContextTypes.DEFAULT_TYPE) -> str:
    return ctx.user_data.get("lang") or get_settings().default_language


def _set_lang(ctx: ContextTypes.DEFAULT_TYPE, code: str) -> None:
    ctx.user_data["lang"] = code


# ---------------------------------------------------------------------------
# Entry / exit
# ---------------------------------------------------------------------------

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, ctx):
        return ConversationHandler.END
    lang = ctx.user_data.get("lang")
    ctx.user_data.clear()
    if lang:
        ctx.user_data["lang"] = lang
    ctx.user_data["bot_active"] = True
    await update.message.reply_text(t(_lang(ctx), "start"), reply_markup=_ACTIVE_KB)
    return WAITING_FILE


async def stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    ctx.user_data["bot_active"] = False
    await update.message.reply_text(t(_lang(ctx), "stopped"), reply_markup=_INACTIVE_KB)
    return ConversationHandler.END


async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(t(_lang(ctx), "cancelled"))
    ctx.user_data.clear()
    return ConversationHandler.END


async def set_language(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handler for /lang uz|en|ru."""
    args = ctx.args if hasattr(ctx, "args") else []
    code = (args[0].lower() if args else "").strip()
    if code not in ("uz", "en", "ru"):
        await update.message.reply_text("/lang uz | /lang en | /lang ru")
        return
    _set_lang(ctx, code)
    await update.message.reply_text(t(code, "lang_set", lang=code))


# ---------------------------------------------------------------------------
# File reception
# ---------------------------------------------------------------------------

def _pil_from_bytes(data: bytes) -> Image.Image:
    return Image.open(BytesIO(data)).convert("RGB")


async def receive_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.user_data.get("bot_active", True):
        return ConversationHandler.END
    if not await check_access(update, ctx):
        return ConversationHandler.END

    settings = get_settings()
    document = update.message.document
    photo = update.message.photo
    file_bytes: Optional[bytes] = None
    is_pdf = False

    if document:
        if document.file_size and document.file_size > settings.max_file_size_mb * 1024 * 1024:
            await update.message.reply_text(
                t(_lang(ctx), "too_large", mb=settings.max_file_size_mb)
            )
            return WAITING_FILE
        name = (document.file_name or "").lower()
        tg_file = await document.get_file()
        file_bytes = bytes(await tg_file.download_as_bytearray())
        is_pdf = name.endswith(".pdf")
        if not is_pdf and not any(name.endswith(x) for x in (".jpg", ".jpeg", ".png")):
            await update.message.reply_text(t(_lang(ctx), "wrong_file"))
            return WAITING_FILE
    elif photo:
        tg_file = await photo[-1].get_file()
        file_bytes = bytes(await tg_file.download_as_bytearray())
        is_pdf = False
    else:
        await update.message.reply_text(t(_lang(ctx), "wrong_file"))
        return WAITING_FILE

    await update.message.reply_text(t(_lang(ctx), "analyzing"))
    ctx.user_data["file_hash"] = hashlib.sha256(file_bytes).hexdigest()[:16]

    if is_pdf:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        scanned = is_scanned_pdf(doc)
    else:
        pil = _pil_from_bytes(file_bytes)
        pil = auto_crop_document(pil)
        pil = auto_rotate_document(pil)
        buf = BytesIO()
        pil.save(buf, format="PDF")
        doc = fitz.open(stream=buf.getvalue(), filetype="pdf")
        scanned = True

    ctx.user_data["is_scanned"] = scanned
    ctx.user_data["original_pdf_bytes"] = doc.tobytes() if not scanned else None

    if not scanned:
        return await _process_text_pdf(update, ctx, doc)
    return await _process_scanned_pdf(update, ctx, doc)


async def _process_text_pdf(update: Update, ctx, doc):
    candidates = extract_text_candidates(doc)
    ctx.user_data["mode"] = "text"
    ctx.user_data["candidates"] = candidates

    full_text = "\n".join(p.get_text("text") for p in doc)
    ctx.user_data["full_doc_text"] = full_text

    if not candidates:
        await update.message.reply_text(t(_lang(ctx), "no_candidates"))
        return WAITING_FILE
    return await _present_candidates(update, ctx)


async def _process_scanned_pdf(update: Update, ctx, doc):
    ocr_candidates, page_images = extract_ocr_candidates(doc)
    ctx.user_data["page_images"] = page_images

    try:
        import pytesseract
        ctx.user_data["full_doc_text"] = "\n".join(
            pytesseract.image_to_string(img) for img in page_images
        )
    except Exception:
        ctx.user_data["full_doc_text"] = ""

    settings = get_settings()
    vision_candidates = []
    # Claude vision reads photographed forms far more reliably than
    # Tesseract (which garbles dot-matrix type and misses whole fields), so
    # on single-page documents it is tried FIRST; OCR candidates are the
    # fallback. Multi-page documents keep OCR-first because vision only
    # sees page 1.
    if settings.enable_vision and (len(page_images) == 1 or not ocr_candidates):
        try:
            vision_candidates = find_vision_candidates(page_images[0])
        except RuntimeError as e:
            if not ocr_candidates:
                await update.message.reply_text(
                    t(_lang(ctx), "vision_error", err=str(e))
                )

    if vision_candidates:
        ctx.user_data["mode"] = "vision"
        ctx.user_data["page_image"] = page_images[0]
        ctx.user_data["vision_candidates"] = vision_candidates
        return await _present_vision(update, ctx)

    if ocr_candidates:
        ctx.user_data["mode"] = "ocr"
        ctx.user_data["candidates"] = ocr_candidates
        return await _present_candidates(update, ctx)

    await update.message.reply_text(t(_lang(ctx), "no_candidates"))
    return WAITING_FILE


# ---------------------------------------------------------------------------
# Candidate presentation
# ---------------------------------------------------------------------------

async def _present_candidates(update: Update, ctx):
    candidates = ctx.user_data["candidates"]
    buttons = []
    for idx, c in enumerate(candidates):
        page_tag = f"p{c.page_index + 1} " if c.page_index > 0 else ""
        label = f"{idx+1}. {page_tag}{c.tm.raw_text}  ({c.context[-30:]})"
        if len(label) > 60:
            label = label[:57] + "..."
        buttons.append([InlineKeyboardButton(label, callback_data=f"pick_{idx}")])
    await update.message.reply_text(
        t(_lang(ctx), "candidates_header"),
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return CHOOSING_FIELD


async def _present_vision(update: Update, ctx):
    cands = ctx.user_data["vision_candidates"]
    overlay = draw_numbered_overlay(ctx.user_data["page_image"], cands)
    buf = BytesIO()
    overlay.save(buf, format="PNG")
    buf.seek(0)

    lines = []
    for idx, c in enumerate(cands, start=1):
        tag = "✍️" if c.is_handwritten else "🖨️"
        lines.append(f"{idx}. {c.raw_text}  —  {c.context}  ({tag})")
    buttons = [
        [InlineKeyboardButton(str(i), callback_data=f"vpick_{i-1}")]
        for i in range(1, len(cands) + 1)
    ]
    await update.message.reply_photo(
        photo=buf,
        caption=t(_lang(ctx), "vision_caption", lines="\n".join(lines)),
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return CHOOSING_FIELD


# ---------------------------------------------------------------------------
# Field → timezone → month → year → free-text time
# ---------------------------------------------------------------------------

async def choose_field(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    idx = int(q.data.split("_")[1])
    ctx.user_data["chosen_idx"] = idx

    if q.data.startswith("vpick_"):
        c = ctx.user_data["vision_candidates"][idx]
        old, ctx_label = c.raw_text, c.context
    else:
        c = ctx.user_data["candidates"][idx]
        old, ctx_label = c.tm.raw_text, c.context

    tz_buttons = [
        [InlineKeyboardButton(tz, callback_data=f"tz_{tz}") for tz in _TIMEZONE_OPTIONS]
    ]
    await q.message.reply_text(
        t(_lang(ctx), "selected", old=old, ctx=ctx_label),
        reply_markup=InlineKeyboardMarkup(tz_buttons),
    )
    return CHOOSING_TIMEZONE


async def choose_timezone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    tz = q.data.split("_", 1)[1]
    ctx.user_data["company_timezone"] = tz

    full_text = ctx.user_data.get("full_doc_text", "") or ""
    state_code = guess_state_code_from_text(full_text)
    pickup_iana = state_code_to_iana(state_code) if state_code else None

    if pickup_iana:
        abbr = iana_to_abbr(pickup_iana)
        ctx.user_data["pickup_iana"] = pickup_iana
        ctx.user_data["pickup_abbr"] = abbr
        note = t(_lang(ctx), "tz_auto_found", state=state_code, abbr=abbr, company=tz)
    else:
        ctx.user_data["pickup_iana"] = None
        ctx.user_data["pickup_abbr"] = None
        note = t(_lang(ctx), "tz_auto_missing")

    rows, row = [], []
    for i, m_name in enumerate(_MONTH_NAMES, start=1):
        row.append(InlineKeyboardButton(m_name[:3], callback_data=f"month_{i}"))
        if len(row) == 4:
            rows.append(row); row = []
    if row:
        rows.append(row)
    await q.edit_message_text(
        t(_lang(ctx), "ask_month", tz=tz, note=note),
        reply_markup=InlineKeyboardMarkup(rows),
    )
    return CHOOSING_MONTH


async def choose_month(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    month_num = int(q.data.split("_", 1)[1])
    ctx.user_data["chosen_month"] = month_num
    year = datetime.now().year
    years = [year - 1, year, year + 1]
    btns = [[InlineKeyboardButton(str(y), callback_data=f"year_{y}") for y in years]]
    await q.edit_message_text(
        t(_lang(ctx), "ask_year",
          tz=ctx.user_data["company_timezone"], month=_MONTH_NAMES[month_num - 1]),
        reply_markup=InlineKeyboardMarkup(btns),
    )
    return CHOOSING_YEAR


async def choose_year(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    year = int(q.data.split("_", 1)[1])
    ctx.user_data["chosen_year"] = year
    await q.edit_message_text(
        t(_lang(ctx), "ask_day_time",
          tz=ctx.user_data["company_timezone"],
          month=_MONTH_NAMES[ctx.user_data["chosen_month"] - 1], year=year),
    )
    return WAITING_NEW_TIME


def _parse_day_time(text: str, month: int, year: int) -> Optional[datetime]:
    import re
    m = re.match(
        r'^(?P<day>\d{1,2})\s+(?P<hour>\d{1,2}):(?P<minute>\d{2})'
        r'(:(?P<second>\d{2}))?\s*(?P<ampm>[AaPp]\.?[Mm]\.?)?$',
        text.strip(),
    )
    if not m:
        return None
    day = int(m.group("day"))
    hour = int(m.group("hour"))
    minute = int(m.group("minute"))
    second = int(m.group("second") or 0)
    ampm = (m.group("ampm") or "").lower().replace(".", "")
    if ampm == "pm" and hour != 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    try:
        return datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None


async def receive_new_time(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    mode = ctx.user_data["mode"]
    idx = ctx.user_data["chosen_idx"]

    if mode == "vision":
        cand = ctx.user_data["vision_candidates"][idx]
        old_raw = cand.raw_text
    else:
        cand = ctx.user_data["candidates"][idx]
        old_raw = cand.tm.raw_text

    month = ctx.user_data.get("chosen_month")
    year = ctx.user_data.get("chosen_year")
    new_dt = _parse_day_time(text, month, year) if (month and year) else None
    if new_dt is None:
        await update.message.reply_text(t(_lang(ctx), "bad_input"))
        return WAITING_NEW_TIME

    ctx.user_data["new_dt_company_tz"] = new_dt
    company_tz = ctx.user_data["company_timezone"]
    pickup_iana = ctx.user_data.get("pickup_iana")
    conv_note = ""
    if pickup_iana:
        try:
            converted = convert_between_timezones(new_dt, company_tz, pickup_iana)
            abbr = ctx.user_data.get("pickup_abbr") or iana_to_abbr(pickup_iana, new_dt)
            if converted != new_dt:
                conv_note = (
                    f"\n\n🕒 {company_tz} {new_dt:%Y-%m-%d %H:%M:%S} "
                    f"→ {abbr} {converted:%Y-%m-%d %H:%M:%S}"
                )
            new_dt = converted
        except ValueError:
            pass
    ctx.user_data["new_dt"] = new_dt

    if mode == "vision":
        new_text = format_like_vision_text(old_raw, new_dt)
    else:
        new_text = format_like_original(new_dt, cand.tm)
    ctx.user_data["new_text"] = new_text

    rows = [
        [InlineKeyboardButton(t(_lang(ctx), "btn_confirm"), callback_data="confirm_yes")],
        [InlineKeyboardButton(t(_lang(ctx), "btn_cancel"), callback_data="confirm_no")],
    ]
    delta = _find_paired_in_candidate(ctx)
    if delta is not None:
        ctx.user_data["delta_pair"] = delta
        rows.insert(0, [InlineKeyboardButton(
            t(_lang(ctx), "btn_confirm_delta"), callback_data="confirm_yes_delta",
        )])

    group = _find_same_value_group(ctx)
    seen = {j for j, _, _ in group}
    group += [g for g in _find_pickup_group(ctx) if g[0] not in seen]
    extra_note = ""
    if group:
        ctx.user_data["pickup_group"] = group
        rows.insert(0, [InlineKeyboardButton(
            t(_lang(ctx), "btn_confirm_group", n=len(group)),
            callback_data="confirm_yes_group",
        )])
        names = []
        for i, _, raw in group:
            if mode == "vision":
                names.append(f"  • {ctx.user_data['vision_candidates'][i].context}: {raw}")
            else:
                names.append(f"  • {ctx.user_data['candidates'][i].context}: {raw}")
        extra_note = "\n\n" + "\n".join(names)

    await update.message.reply_text(
        t(_lang(ctx), "confirm",
          old=old_raw, new=new_text, conv=conv_note, extra=extra_note),
        reply_markup=InlineKeyboardMarkup(rows),
    )
    return CONFIRMING


# ---------------------------------------------------------------------------
# Delta-pair & pickup-group helpers
# ---------------------------------------------------------------------------

def _all_candidates(ctx) -> list:
    if ctx.user_data["mode"] == "vision":
        return ctx.user_data["vision_candidates"]
    return ctx.user_data["candidates"]


def _candidate_raw(c, mode: str) -> str:
    return c.raw_text if mode == "vision" else c.tm.raw_text


def _candidate_ctx(c, mode: str) -> str:
    return c.context or ""


def _find_paired_in_candidate(ctx):
    mode = ctx.user_data["mode"]
    idx = ctx.user_data["chosen_idx"]
    all_ = _all_candidates(ctx)
    chosen = all_[idx]
    chosen_ctx = _candidate_ctx(chosen, mode)
    if not looks_like_time_out_label(chosen_ctx):
        return None
    old_out = quick_parse_time_text(_candidate_raw(chosen, mode))
    if not old_out:
        return None
    for j, other in enumerate(all_):
        if j == idx:
            continue
        if not looks_like_time_in_label(_candidate_ctx(other, mode)):
            continue
        old_in_raw = _candidate_raw(other, mode)
        old_in = quick_parse_time_text(old_in_raw)
        if old_in:
            return (j, old_out - old_in, old_in_raw)
    return None


def _find_same_value_group(ctx):
    """Other candidates carrying the SAME moment as the chosen one.

    BOL forms print one event under several labels (Dep. / Time Sealed /
    Date all showing "06/24 19:39"); leaving the twins untouched while one
    changes makes the document contradict itself. Entries use delta=0 so
    the confirm-group path rewrites each twin to the same new datetime,
    format-preserved per field (a twin with a year keeps its year).
    """
    mode = ctx.user_data["mode"]
    idx = ctx.user_data["chosen_idx"]
    all_ = _all_candidates(ctx)
    chosen_raw = _candidate_raw(all_[idx], mode)
    out = []
    for j, other in enumerate(all_):
        if j == idx:
            continue
        other_raw = _candidate_raw(other, mode)
        if matches_datetime_value(chosen_raw, other_raw):
            out.append((j, timedelta(0), other_raw))
    return out


def _find_pickup_group(ctx):
    mode = ctx.user_data["mode"]
    idx = ctx.user_data["chosen_idx"]
    all_ = _all_candidates(ctx)
    chosen = all_[idx]
    if not looks_like_pickup_group_label(_candidate_ctx(chosen, mode)):
        return []
    fallback_year = datetime.now().year
    import re
    raw = _candidate_raw(chosen, mode)
    ym = re.search(r'(20\d{2})', raw)
    if ym:
        fallback_year = int(ym.group(1))
    chosen_dt = quick_parse_full_datetime(raw, fallback_year)
    if not chosen_dt:
        return []
    out = []
    for j, other in enumerate(all_):
        if j == idx:
            continue
        if not looks_like_pickup_group_label(_candidate_ctx(other, mode)):
            continue
        other_raw = _candidate_raw(other, mode)
        other_dt = quick_parse_full_datetime(other_raw, fallback_year)
        if not other_dt:
            continue
        out.append((j, other_dt - chosen_dt, other_raw))
    return out


# ---------------------------------------------------------------------------
# Confirmation → produce edited PDF
# ---------------------------------------------------------------------------

async def confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "confirm_no":
        msg = t(_lang(ctx), "cancelled")
        if q.message.caption:
            await q.edit_message_caption(caption=msg)
        else:
            await q.edit_message_text(msg)
        return ConversationHandler.END

    apply_delta = q.data == "confirm_yes_delta"
    apply_group = q.data == "confirm_yes_group"
    await q.message.reply_text(t(_lang(ctx), "preparing"))

    mode = ctx.user_data["mode"]
    idx = ctx.user_data["chosen_idx"]
    new_text = ctx.user_data["new_text"]
    new_dt = ctx.user_data["new_dt"]

    try:
        if mode == "text":
            cand = ctx.user_data["candidates"][idx]
            doc = fitz.open(stream=ctx.user_data["original_pdf_bytes"], filetype="pdf")
            replace_text_in_pdf(doc, cand, new_text)
            if apply_group and "pickup_group" in ctx.user_data:
                for j, delta, _ in ctx.user_data["pickup_group"]:
                    other = ctx.user_data["candidates"][j]
                    other_text = format_like_original(new_dt + delta, other.tm)
                    replace_text_in_pdf(doc, other, other_text)
            out = doc.tobytes()
            doc.close()
        elif mode == "ocr":
            cand = ctx.user_data["candidates"][idx]
            imgs = ctx.user_data["page_images"]
            replace_text_in_scanned_pdf(imgs, cand, new_text)
            if apply_group and "pickup_group" in ctx.user_data:
                for j, delta, _ in ctx.user_data["pickup_group"]:
                    other = ctx.user_data["candidates"][j]
                    other_text = format_like_original(new_dt + delta, other.tm)
                    replace_text_in_scanned_pdf(imgs, other, other_text)
            out = images_to_pdf_bytes(imgs)
        else:  # vision
            page_img = ctx.user_data["page_image"]
            cand = ctx.user_data["vision_candidates"][idx]
            replace_vision_candidate_in_image(page_img, cand, new_text)
            if apply_delta and "delta_pair" in ctx.user_data:
                j, delta, old_in_raw = ctx.user_data["delta_pair"]
                new_in_dt = new_dt - delta
                other = ctx.user_data["vision_candidates"][j]
                replace_vision_candidate_in_image(
                    page_img, other, format_like_vision_text(old_in_raw, new_in_dt)
                )
            if apply_group and "pickup_group" in ctx.user_data:
                for j, delta, old_raw in ctx.user_data["pickup_group"]:
                    other = ctx.user_data["vision_candidates"][j]
                    new_other = format_like_vision_text(old_raw, new_dt + delta)
                    replace_vision_candidate_in_image(page_img, other, new_other)
            # page_img IS page_images[0] (mutated in place) — emit every
            # page so multi-page documents don't lose their tail pages.
            out = images_to_pdf_bytes(ctx.user_data.get("page_images") or [page_img])
    except Exception as e:
        logger.exception("edit_failed")
        await q.message.reply_text(f"Xatolik: {e}")
        return ConversationHandler.END

    # Audit log
    user = update.effective_user
    chosen = _all_candidates(ctx)[idx]
    log_edit(
        user_id=user.id,
        username=user.username,
        file_hash=ctx.user_data.get("file_hash"),
        page_index=getattr(chosen, "page_index", 0),
        mode=mode,
        field_context=_candidate_ctx(chosen, mode),
        old_value=_candidate_raw(chosen, mode),
        new_value=new_text,
        tz_from=ctx.user_data.get("company_timezone"),
        tz_to=ctx.user_data.get("pickup_abbr"),
        success=True,
    )

    bio = BytesIO(out)
    bio.name = "BOL_edited.pdf"
    await q.message.reply_document(document=bio, filename="BOL_edited.pdf")

    more_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(t(_lang(ctx), "btn_more"), callback_data="more"),
        InlineKeyboardButton(t(_lang(ctx), "btn_done"), callback_data="done"),
    ]])
    await q.message.reply_text(t(_lang(ctx), "done"), reply_markup=more_kb)
    return CONFIRMING  # stay so the more/done buttons work


async def more_or_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "done":
        ctx.user_data.clear()
        return ConversationHandler.END
    # "more" — re-present the candidate list (state still hot in memory)
    # NB: for text-PDF mode we'd ideally re-extract from the freshly-edited
    # PDF, but for v2 we just re-show the original list so the user can pick
    # a different field. Edits stack on the original.
    mode = ctx.user_data.get("mode")
    if not mode:
        await q.message.reply_text(t(_lang(ctx), "cancelled"))
        return ConversationHandler.END
    fake_update = Update(update.update_id, message=q.message)
    # Easier: re-invoke the presenter
    if mode == "vision":
        await _present_vision(fake_update, ctx)
    else:
        await _present_candidates(fake_update, ctx)
    return CHOOSING_FIELD
