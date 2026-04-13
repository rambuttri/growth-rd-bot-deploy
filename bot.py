#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Growth R&D Assistant - Telegram bot for two-way communication."""

import os
import logging
import json
from datetime import datetime
from threading import Thread

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from flask import Flask, request, jsonify

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "pavel_feklov")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "0"))
API_SECRET = os.environ.get("API_SECRET", "growth-rd-2026")
PORT = int(os.environ.get("PORT", "10000"))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

messages = []
MAX_MESSAGES = 100
tg_app = None


def is_admin(update: Update) -> bool:
    user = update.effective_user
    if ADMIN_CHAT_ID and user.id == ADMIN_CHAT_ID:
        return True
    if user.username and user.username.lower() == ADMIN_USERNAME.lower():
        return True
    return False


def store_message(direction, text, msg_type="text"):
    messages.append({
        "direction": direction,
        "text": text,
        "type": msg_type,
        "timestamp": datetime.utcnow().isoformat(),
    })
    if len(messages) > MAX_MESSAGES:
        messages.pop(0)


async def start(update: Update, context):
    if not is_admin(update):
        await update.message.reply_text("Access denied.")
        return
    global ADMIN_CHAT_ID
    ADMIN_CHAT_ID = update.effective_user.id
    logger.info(f"Admin chat_id registered: {ADMIN_CHAT_ID}")
    keyboard = [
        [InlineKeyboardButton("Approve", callback_data="approve"),
         InlineKeyboardButton("Reject", callback_data="reject")],
        [InlineKeyboardButton("Status", callback_data="status"),
         InlineKeyboardButton("Files ready", callback_data="files_ready")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Growth R&D Assistant\n\n"
        "Bot for project communication.\n"
        "Send text, files, photos, voice\n"
        "/approve /reject /status /history\n\n"
        f"Your chat_id: \`{update.effective_user.id}\`",
        parse_mode="Markdown",
        reply_markup=reply_markup,
    )


async def handle_text(update: Update, context):
    if not is_admin(update):
        return
    text = update.message.text
    store_message("in", text, "text")
    logger.info(f"Message from Pasha: {text[:50]}...")
    await update.message.reply_text(
        f"Received. Message saved.\nTotal in queue: {len([m for m in messages if m['direction'] == 'in'])} incoming",
    )


async def handle_file(update: Update, context):
    if not is_admin(update):
        return
    doc = update.message.document
    caption = update.message.caption or ""
    store_message("in", f"[FILE: {doc.file_name}, {doc.file_size} bytes] {caption}", "file")
    await update.message.reply_text(f"File received: {doc.file_name}\nSize: {doc.file_size / 1024:.1f} KB")


async def handle_photo(update: Update, context):
    if not is_admin(update):
        return
    caption = update.message.caption or ""
    store_message("in", f"[PHOTO] {caption}", "photo")
    await update.message.reply_text("Photo received and saved.")


async def handle_voice(update: Update, context):
    if not is_admin(update):
        return
    duration = update.message.voice.duration
    store_message("in", f"[VOICE: {duration}s]", "voice")
    await update.message.reply_text(f"Voice message received ({duration}s).\nTranscription unavailable.")


async def handle_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    action = query.data
    store_message("in", f"[ACTION: {action}]", "action")
    responses = {
        "approve": "Approved! Recorded.",
        "reject": "Rejected! Recorded.",
        "status": f"Messages: {len(messages)}\nIn: {len([m for m in messages if m['direction'] == 'in'])}\nOut: {len([m for m in messages if m['direction'] == 'out'])}",
        "files_ready": "File request recorded.",
    }
    await query.edit_message_text(text=responses.get(action, f"Action: {action}"))


async def cmd_approve(update: Update, context):
    if not is_admin(update):
        return
    text = " ".join(context.args) if context.args else "general approval"
    store_message("in", f"[APPROVE: {text}]", "action")
    await update.message.reply_text(f"Approved: {text}")


async def cmd_reject(update: Update, context):
    if not is_admin(update):
        return
    text = " ".join(context.args) if context.args else "general rejection"
    store_message("in", f"[REJECT: {text}]", "action")
    await update.message.reply_text(f"Rejected: {text}")


async def cmd_status(update: Update, context):
    if not is_admin(update):
        return
    incoming = [m for m in messages if m["direction"] == "in"]
    outgoing = [m for m in messages if m["direction"] == "out"]
    await update.message.reply_text(
        f"*Status*\nIncoming: {len(incoming)}\nOutgoing: {len(outgoing)}\nTotal: {len(messages)}",
        parse_mode="Markdown",
    )


async def cmd_history(update: Update, context):
    if not is_admin(update):
        return
    recent = messages[-10:]
    if not recent:
        await update.message.reply_text("History is empty.")
        return
    lines = []
    for m in recent:
        direction = "->" if m["direction"] == "in" else "<-"
        ts = m["timestamp"][11:16]
        lines.append(f"{direction} [{ts}] {m['text'][:80]}")
    await update.message.reply_text("*Last 10 messages:*\n\n" + "\n".join(lines), parse_mode="Markdown")


flask_app = Flask(__name__)


@flask_app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "messages_count": len(messages)})


@flask_app.route("/messages", methods=["GET"])
def get_messages():
    secret = request.args.get("secret", "")
    if secret != API_SECRET:
        return jsonify({"error": "unauthorized"}), 401
    direction = request.args.get("direction", "")
    since = request.args.get("since", "")
    filtered = messages
    if direction:
        filtered = [m for m in filtered if m["direction"] == direction]
    if since:
        filtered = [m for m in filtered if m["timestamp"] > since]
    return jsonify({"messages": filtered, "count": len(filtered)})


@flask_app.route("/send", methods=["POST"])
def send_message():
    data = request.json or {}
    secret = data.get("secret", "")
    if secret != API_SECRET:
        return jsonify({"error": "unauthorized"}), 401
    text = data.get("text", "")
    if not text:
        return jsonify({"error": "no text"}), 400
    store_message("out", text, "text")
    import asyncio
    async def _send():
        if tg_app and ADMIN_CHAT_ID:
            await tg_app.bot.send_message(chat_id=ADMIN_CHAT_ID, text=text, parse_mode="Markdown")
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(_send())
        else:
            loop.run_until_complete(_send())
    except RuntimeError:
        asyncio.run(_send())
    return jsonify({"status": "sent", "text": text[:50]})


def run_flask():
    flask_app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)


def main():
    global tg_app
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set!")
        return
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info(f"Flask API started on port {PORT}")
    tg_app = Application.builder().token(BOT_TOKEN).build()
    tg_app.add_handler(CommandHandler("start", start))
    tg_app.add_handler(CommandHandler("approve", cmd_approve))
    tg_app.add_handler(CommandHandler("reject", cmd_reject))
    tg_app.add_handler(CommandHandler("status", cmd_status))
    tg_app.add_handler(CommandHandler("history", cmd_history))
    tg_app.add_handler(CallbackQueryHandler(handle_callback))
    tg_app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    tg_app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    tg_app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    logger.info("Bot starting... polling mode")
    tg_app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
