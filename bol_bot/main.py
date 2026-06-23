"""Entry point: wire handlers, init DB, run polling."""
from __future__ import annotations

import logging
import sys

from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ConversationHandler,
    MessageHandler, filters,
)

from bol_bot.bot.admin import cmd_history, cmd_lang, cmd_stats
from bol_bot.bot.handlers import (
    CHOOSING_FIELD, CHOOSING_MONTH, CHOOSING_TIMEZONE, CHOOSING_YEAR,
    CONFIRMING, WAITING_FILE, WAITING_NEW_TIME,
    cancel, choose_field, choose_month, choose_timezone, choose_year,
    confirm, more_or_done, receive_file, receive_new_time, start, stop,
)
from bol_bot.config import get_settings
from bol_bot.logging_setup import setup_logging
from bol_bot.storage import init_db

logger = logging.getLogger(__name__)


def build_app() -> Application:
    s = get_settings()
    if not s.bol_bot_token:
        sys.stderr.write(
            "ERROR: BOL_BOT_TOKEN is not set. Copy .env.example to .env and fill it in.\n"
        )
        sys.exit(1)

    init_db()

    app = Application.builder().token(s.bol_bot_token).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex(r"^▶️ Start$"), start),
        ],
        states={
            WAITING_FILE: [
                MessageHandler(filters.Document.ALL | filters.PHOTO, receive_file),
            ],
            CHOOSING_FIELD: [
                CallbackQueryHandler(choose_field, pattern=r"^(pick|vpick)_\d+$"),
            ],
            CHOOSING_TIMEZONE: [
                CallbackQueryHandler(
                    choose_timezone, pattern=r"^tz_(EDT|CDT|MDT|PDT)$"
                ),
            ],
            CHOOSING_MONTH: [
                CallbackQueryHandler(choose_month, pattern=r"^month_\d+$"),
            ],
            CHOOSING_YEAR: [
                CallbackQueryHandler(choose_year, pattern=r"^year_\d+$"),
            ],
            WAITING_NEW_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_new_time),
            ],
            CONFIRMING: [
                CallbackQueryHandler(
                    confirm, pattern=r"^confirm_(yes|yes_delta|yes_group|no)$"
                ),
                CallbackQueryHandler(more_or_done, pattern=r"^(more|done)$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("stop", stop),
            MessageHandler(filters.Regex(r"^⏹ Stop$"), stop),
        ],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(MessageHandler(filters.Regex(r"^⏹ Stop$"), stop))
    app.add_handler(MessageHandler(filters.Regex(r"^▶️ Start$"), start))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("lang", cmd_lang))

    return app


def main() -> None:
    s = get_settings()
    setup_logging(level=s.log_level, log_file=s.log_file)
    logger.info("bot.starting", extra={"version": "2.0.0"})
    app = build_app()
    logger.info("bot.ready")
    app.run_polling(allowed_updates=None)


if __name__ == "__main__":
    main()
