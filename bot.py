"""
Telegram Support Bot
---------------------
- Regular users can send text messages or files (photo, video, document, voice note, etc.)
- Every message from a user is forwarded to the ADMIN_ID.
- When the admin REPLIES to a forwarded message, the reply is sent back to that original user.
- Telegram bots cannot receive/make voice or video calls at all (not supported by the
  Bot API), so no extra blocking is needed for that.

Setup:
1. pip install python-telegram-bot --upgrade
2. Run: python support_bot.py
"""

import json
import logging
import os
from datetime import datetime

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "1586853120"))

if not BOT_TOKEN:
    raise SystemExit(
        "BOT_TOKEN environment variable set kora hoy nai! "
        "Deployment platform-e BOT_TOKEN variable set korun."
    )

# Persist the mapping {admin_forwarded_message_id: original_user_chat_id}
# so admin replies can be routed back correctly even after a restart.
MAP_FILE = "message_map.json"

# Persist known users: {chat_id: {"name":..., "username":..., "last_message": ...}}
USERS_FILE = "users.json"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def load_json(path: str) -> dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


message_map = {int(k): v for k, v in load_json(MAP_FILE).items()}
users = load_json(USERS_FILE)


def remember_user(user, chat_id: int) -> None:
    users[str(chat_id)] = {
        "name": user.full_name,
        "username": user.username or "",
        "last_message": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_json(USERS_FILE, users)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Assalamu alaikum! Apnar kono issue thakle text likhun ba file/photo/document pathan. "
        "Amader support team shighroi reply dibe."
    )


async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Any message from a normal user (not the admin) gets copied to the admin,
    clearly labeled so multiple users never get mixed up."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    msg = update.effective_message

    remember_user(user, chat_id)

    # Clear header BEFORE the actual content, so admin instantly knows who it's from
    header = (
        f"📩 <b>{user.full_name}</b>"
        f"{' (@' + user.username + ')' if user.username else ''}\n"
        f"🆔 <code>{chat_id}</code>"
    )
    await context.bot.send_message(chat_id=ADMIN_ID, text=header, parse_mode="HTML")

    # Copy the actual content (text/photo/video/document/voice/etc.)
    sent = await context.bot.copy_message(
        chat_id=ADMIN_ID,
        from_chat_id=chat_id,
        message_id=msg.message_id,
    )

    # Remember: this copied message in admin's chat maps back to this user
    message_map[sent.message_id] = chat_id
    save_json(MAP_FILE, message_map)


async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """When admin replies to a forwarded message, send it back to the original user."""
    msg = update.effective_message

    if not msg.reply_to_message:
        await msg.reply_text(
            "Reply dite hole, user er forward kora message-e reply diye likhun."
        )
        return

    replied_id = msg.reply_to_message.message_id
    target_chat_id = message_map.get(replied_id)

    if target_chat_id is None:
        await msg.reply_text("Sorry, ei message er original user khuje pai nai.")
        return

    await context.bot.copy_message(
        chat_id=target_chat_id,
        from_chat_id=ADMIN_ID,
        message_id=msg.message_id,
    )
    await msg.reply_text("✅ User ke pathano hoyeche.")


async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin-only: /users -> shows everyone who has messaged the bot so far."""
    if update.effective_user.id != ADMIN_ID:
        return

    if not users:
        await update.message.reply_text("Ekhono kono user message pathay ni.")
        return

    lines = ["👥 <b>Active users:</b>\n"]
    for chat_id, info in users.items():
        uname = f"@{info['username']}" if info["username"] else "no-username"
        lines.append(
            f"• {info['name']} ({uname}) — id: <code>{chat_id}</code>\n"
            f"   last msg: {info['last_message']}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def reply_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin-only: /reply <user_id> <message> -> sends text directly to that user
    without needing to reply-to a forwarded message."""
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Format: /reply <user_id> <message>")
        return

    try:
        target_chat_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("user_id ta shothik number hote hobe.")
        return

    text = " ".join(context.args[1:])

    if str(target_chat_id) not in users:
        await update.message.reply_text("Ei id-r kono user pawa jay ni (/users diye check korun).")
        return

    await context.bot.send_message(chat_id=target_chat_id, text=text)
    await update.message.reply_text("✅ Pathano hoyeche.")


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("users", list_users))
    app.add_handler(CommandHandler("reply", reply_command))

    # Admin's messages -> treated as replies to route back to users
    app.add_handler(
        MessageHandler(filters.User(user_id=ADMIN_ID) & ~filters.COMMAND, handle_admin_reply)
    )

    # Everyone else's messages (text, photo, video, document, voice, etc.) -> forward to admin
    app.add_handler(
        MessageHandler(
            ~filters.User(user_id=ADMIN_ID) & ~filters.COMMAND,
            handle_user_message,
        )
    )

    logger.info("Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
