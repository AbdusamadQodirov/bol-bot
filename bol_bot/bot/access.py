"""Access control & rate-limit gate (used as a guard at handler entry)."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bol_bot.config import get_settings
from bol_bot.locales import t
from bol_bot.storage import is_rate_limited, record_request


def _lang(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.user_data.get("lang") or get_settings().default_language


async def check_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Return True if the user may proceed; otherwise reply and return False."""
    if not update.effective_user:
        return False
    uid = update.effective_user.id
    s = get_settings()

    # Whitelist gate
    if s.whitelist_mode:
        allowed = set(s.allowed_user_ids) | set(s.admin_ids)
        if uid not in allowed:
            await update.effective_message.reply_text(t(_lang(context), "not_authorised"))
            return False

    # Rate limit
    limited, reason = is_rate_limited(uid)
    if limited:
        await update.effective_message.reply_text(
            t(_lang(context), "rate_limited", reason=reason)
        )
        return False

    record_request(uid)
    return True


def is_admin(user_id: int) -> bool:
    return user_id in get_settings().admin_ids
