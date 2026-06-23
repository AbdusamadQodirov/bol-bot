"""Admin & utility commands: /stats, /history, /lang."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bol_bot.bot.access import is_admin
from bol_bot.config import get_settings
from bol_bot.locales import t
from bol_bot.storage import global_stats, recent_edits


def _lang(ctx) -> str:
    return ctx.user_data.get("lang") or get_settings().default_language


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not is_admin(user.id):
        return
    total, users, last = global_stats()
    await update.message.reply_text(
        t(_lang(ctx), "stats", total=total, users=users, last=last)
    )


async def cmd_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    rows = recent_edits(user.id, limit=10)
    if not rows:
        await update.message.reply_text(t(_lang(ctx), "history_empty"))
        return
    lines = [t(_lang(ctx), "history_header", n=len(rows))]
    for r in rows:
        lines.append(
            f"• {r['ts'][:19]} | {r['field_context'][:25]} | "
            f"{r['old_value']} → {r['new_value']}"
        )
    await update.message.reply_text("\n".join(lines)[:4000])


async def cmd_lang(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args or []
    code = (args[0].lower() if args else "").strip()
    if code not in ("uz", "en", "ru"):
        await update.message.reply_text("Usage: /lang uz|en|ru")
        return
    ctx.user_data["lang"] = code
    await update.message.reply_text(t(code, "lang_set", lang=code))
