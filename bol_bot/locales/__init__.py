"""Minimal i18n: language-keyed message dictionaries.

Supports: uz (default), en, ru. Falls back to uz if a key is missing.
"""
from __future__ import annotations

from bol_bot.config import get_settings

MESSAGES: dict[str, dict[str, str]] = {
    "uz": {
        "start": (
            "Salom! Men BOL (Bill of Lading) hujjatidagi pickup vaqtini "
            "ELD ma'lumotiga moslab to'g'irlashga yordam beraman.\n\n"
            "BOL faylini yuboring — PDF yoki rasm (foto).\n\n"
            "Pastdagi \"⏹ Stop\" tugmasi (yoki /stop) bilan botni to'xtatasiz."
        ),
        "stopped": (
            "Bot to'xtatildi. Qaytadan ishlatish uchun \"▶️ Start\" tugmasi "
            "yoki /start bosing."
        ),
        "analyzing": "Faylni tahlil qilyapman, biroz kuting...",
        "wrong_file": "Iltimos, PDF yoki rasm (jpg/png) fayl yuboring.",
        "too_large": "Fayl juda katta. Maksimal: {mb} MB.",
        "no_candidates": "Hujjatdan sana/vaqt yozuvlarini topa olmadim. Boshqa fayl yuboring.",
        "candidates_header": "Quyidagi sana/vaqt yozuvlari topildi. Qaysi birini tahrirlash kerak?",
        "vision_caption": "Rasmda topilgan sana/vaqt yozuvlari (raqamlar bo'yicha):\n\n{lines}\n\nQaysi raqamni tahrirlash kerak?",
        "selected": "Tanlandi: {old}  ({ctx})\n\nAvval company time zone'ini tanlang:",
        "tz_auto_found": "Pickup joyi: {state} ({abbr})\nVaqt {company} → {abbr} avtomatik konvertatsiya qilinadi.",
        "tz_auto_missing": "Pickup time zone'i avtomatik aniqlanmadi — vaqt konvertatsiyasiz yoziladi.",
        "ask_month": "Time zone: {tz}\n{note}\n\nOyni tanlang:",
        "ask_year": "Time zone: {tz}\nOy: {month}\n\nYilni tanlang:",
        "ask_day_time": (
            "Time zone: {tz}\nOy: {month}\nYil: {year}\n\n"
            "ELD logbook'dagi HAQIQIY kun va vaqtni kiriting.\n"
            "Masalan: 13 1:34:45 PM  yoki  13 13:34:45  yoki  13 13:34"
        ),
        "bad_input": (
            "Kun va vaqtni tushuna olmadim. Iltimos shu uslubda kiriting:\n"
            "13 1:34:45 PM   yoki   13 13:34:45   yoki   13 13:34"
        ),
        "confirm": (
            "Eski qiymat: {old}\nYangi qiymat: {new}{conv}{extra}\n\n"
            "Shu o'zgarishni hujjatga kiritaymi?"
        ),
        "btn_confirm": "✅ Tasdiqlash",
        "btn_cancel": "❌ Bekor qilish",
        "btn_confirm_delta": "✅ Tasdiqlash + Time In'ni ham mos sur",
        "btn_confirm_group": "✅ Tasdiqlash + {n} ta bog'liq maydonni ham yangila",
        "btn_undo": "↶ Bekor qil",
        "btn_more": "✏️ Yana boshqa maydon",
        "btn_done": "✅ Tugatish",
        "cancelled": "Bekor qilindi. Qaytadan boshlash uchun /start bosing.",
        "preparing": "Hujjatni tayyorlayapman...",
        "done": (
            "Tayyor! Yana boshqa yozuvni tahrirlash uchun \"✏️ Yana boshqa maydon\" "
            "tugmasini bosing yoki yangi fayl uchun /start."
        ),
        "vision_error": "Avtomatik aniqlashda xatolik: {err}\nANTHROPIC_API_KEY sozlanmagan bo'lishi mumkin.",
        "rate_limited": "Iltimos, biroz kuting. ({reason})",
        "not_authorised": "Sizda bu botdan foydalanish ruxsati yo'q. Admin bilan bog'laning.",
        "page_select": "Hujjatda {n} ta sahifa bor. Qaysi sahifani tahrirlaysiz?",
        "page_btn": "Sahifa {n}",
        "lang_set": "Til o'zgartirildi: {lang}",
        "stats": "📊 Statistika:\n• Jami tahrir: {total}\n• Foydalanuvchilar: {users}\n• Oxirgi 24 soat: {last}",
        "history_empty": "Sizda hali tahrir tarixi yo'q.",
        "history_header": "Oxirgi {n} ta tahrir:",
    },
    "en": {
        "start": (
            "Hi! I help correct pickup times on BOL (Bill of Lading) documents "
            "to match your ELD log.\n\nSend the BOL — PDF or photo.\n\n"
            "Use \"⏹ Stop\" (or /stop) to stop the bot."
        ),
        "stopped": "Bot stopped. Press \"▶️ Start\" or /start to begin again.",
        "analyzing": "Analyzing your file, please wait...",
        "wrong_file": "Please send a PDF or image (jpg/png).",
        "too_large": "File too large. Max: {mb} MB.",
        "no_candidates": "I couldn't find any date/time fields. Try another file.",
        "candidates_header": "Found these date/time fields. Which one to edit?",
        "vision_caption": "Detected date/time fields (numbered):\n\n{lines}\n\nWhich number to edit?",
        "selected": "Selected: {old}  ({ctx})\n\nFirst, pick your company time zone:",
        "tz_auto_found": "Pickup location: {state} ({abbr})\nTime will auto-convert from {company} → {abbr}.",
        "tz_auto_missing": "Pickup time zone not auto-detected — time will be written without conversion.",
        "ask_month": "Time zone: {tz}\n{note}\n\nPick the month:",
        "ask_year": "Time zone: {tz}\nMonth: {month}\n\nPick the year:",
        "ask_day_time": (
            "Time zone: {tz}\nMonth: {month}\nYear: {year}\n\n"
            "Enter the REAL day & time from your ELD logbook.\n"
            "Example: 13 1:34:45 PM  or  13 13:34:45  or  13 13:34"
        ),
        "bad_input": "Couldn't parse. Try: 13 1:34:45 PM   or   13 13:34:45   or   13 13:34",
        "confirm": "Old: {old}\nNew: {new}{conv}{extra}\n\nApply this change?",
        "btn_confirm": "✅ Apply",
        "btn_cancel": "❌ Cancel",
        "btn_confirm_delta": "✅ Apply + shift Time In by same delta",
        "btn_confirm_group": "✅ Apply + update {n} related fields",
        "btn_undo": "↶ Undo",
        "btn_more": "✏️ Edit another field",
        "btn_done": "✅ Done",
        "cancelled": "Cancelled. /start to begin again.",
        "preparing": "Preparing the document...",
        "done": "Done! Press \"✏️ Edit another field\" to continue or /start for a new file.",
        "vision_error": "Auto-detection error: {err}\nANTHROPIC_API_KEY may be missing.",
        "rate_limited": "Please wait. ({reason})",
        "not_authorised": "You don't have access to this bot. Contact the admin.",
        "page_select": "Document has {n} pages. Which page to edit?",
        "page_btn": "Page {n}",
        "lang_set": "Language set: {lang}",
        "stats": "📊 Stats:\n• Total edits: {total}\n• Users: {users}\n• Last 24h: {last}",
        "history_empty": "No edit history yet.",
        "history_header": "Last {n} edits:",
    },
    "ru": {
        "start": (
            "Привет! Помогу скорректировать pickup time на BOL "
            "(Bill of Lading) под данные ELD.\n\nПришлите BOL — PDF или фото.\n\n"
            "\"⏹ Stop\" (или /stop) — остановить бота."
        ),
        "stopped": "Бот остановлен. \"▶️ Start\" или /start — начать заново.",
        "analyzing": "Анализирую файл, подождите...",
        "wrong_file": "Пришлите PDF или картинку (jpg/png).",
        "too_large": "Файл слишком большой. Макс: {mb} МБ.",
        "no_candidates": "Не нашёл дат/времени. Попробуйте другой файл.",
        "candidates_header": "Найденные даты/время. Что редактировать?",
        "vision_caption": "Найденные поля (по номерам):\n\n{lines}\n\nКакой номер редактируем?",
        "selected": "Выбрано: {old}  ({ctx})\n\nВыберите тайм-зону компании:",
        "tz_auto_found": "Pickup: {state} ({abbr})\nКонвертация {company} → {abbr} автоматически.",
        "tz_auto_missing": "Pickup тайм-зону не определил — время запишется без конвертации.",
        "ask_month": "Тайм-зона: {tz}\n{note}\n\nВыберите месяц:",
        "ask_year": "Тайм-зона: {tz}\nМесяц: {month}\n\nВыберите год:",
        "ask_day_time": (
            "ТЗ: {tz}\nМесяц: {month}\nГод: {year}\n\n"
            "Введите день и время из ELD.\n"
            "Например: 13 1:34:45 PM  или  13 13:34:45  или  13 13:34"
        ),
        "bad_input": "Не понял. Попробуйте: 13 1:34:45 PM   или   13 13:34",
        "confirm": "Старое: {old}\nНовое: {new}{conv}{extra}\n\nПрименить?",
        "btn_confirm": "✅ Применить",
        "btn_cancel": "❌ Отмена",
        "btn_confirm_delta": "✅ Применить + сдвинуть Time In",
        "btn_confirm_group": "✅ Применить + обновить {n} связанных",
        "btn_undo": "↶ Отменить",
        "btn_more": "✏️ Ещё одно поле",
        "btn_done": "✅ Готово",
        "cancelled": "Отменено. /start — заново.",
        "preparing": "Готовлю документ...",
        "done": "Готово! \"✏️ Ещё одно поле\" — продолжить, /start — новый файл.",
        "vision_error": "Ошибка детекции: {err}\nВозможно, не задан ANTHROPIC_API_KEY.",
        "rate_limited": "Подождите. ({reason})",
        "not_authorised": "Нет доступа. Обратитесь к админу.",
        "page_select": "В документе {n} страниц. Какую редактируем?",
        "page_btn": "Стр. {n}",
        "lang_set": "Язык: {lang}",
        "stats": "📊 Статистика:\n• Всего: {total}\n• Юзеров: {users}\n• 24ч: {last}",
        "history_empty": "История пуста.",
        "history_header": "Последние {n} правок:",
    },
}


def t(lang: str | None, key: str, **kwargs) -> str:
    """Translate ``key`` to ``lang``, fall back to default language, then 'uz'."""
    default = get_settings().default_language
    for code in (lang, default, "uz"):
        if not code:
            continue
        msgs = MESSAGES.get(code)
        if msgs and key in msgs:
            try:
                return msgs[key].format(**kwargs)
            except (KeyError, IndexError):
                return msgs[key]
    return key
