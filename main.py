import os
import secrets
import logging
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from pymongo import AsyncMongoClient

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("video-bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
MONGO_URI = os.getenv("MONGO_URI", "").strip()
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
DB_NAME = os.getenv("DB_NAME", "saif_video_bot")

if not BOT_TOKEN or not MONGO_URI or not OWNER_ID:
    raise RuntimeError("Set BOT_TOKEN, MONGO_URI and OWNER_ID")

mongo = AsyncMongoClient(MONGO_URI)
db = mongo[DB_NAME]

admins_col = db["admins"]
videos_col = db["videos"]
channels_col = db["channels"]

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

pending_uploads = set()


def is_owner(user_id):
    return user_id == OWNER_ID


async def is_admin(user_id):
    return (
        is_owner(user_id)
        or await admins_col.find_one({"user_id": user_id}) is not None
    )


async def admin_required(message):
    if not await is_admin(message.from_user.id):
        await message.answer("⛔ Only admins can use this command.")
        return False
    return True


async def owner_required(message):
    if not is_owner(message.from_user.id):
        await message.answer("⛔ Only owner can use this command.")
        return False
    return True


async def channel_keyboard():
    rows = []

    async for ch in channels_col.find({}):
        rows.append([
            InlineKeyboardButton(
                text=f"Join {ch['title']}",
                url=ch["invite_link"]
            )
        ])

    rows.append([
        InlineKeyboardButton(
            text="✅ Verify",
            callback_data="verify"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


async def membership_ok(user_id):
    async for ch in channels_col.find({}):
        try:
            member = await bot.get_chat_member(
                ch["chat_id"], user_id
            )

            if member.status in ("left", "kicked"):
                return False

        except (TelegramBadRequest, TelegramForbiddenError):
            log.exception("Membership verification failed")
            return False

    return True


async def send_video_link(message, video):
    me = await bot.get_me()

    link = (
        f"https://t.me/{me.username}"
        f"?start=vid_{video['code']}"
    )

    await message.answer(
        f"🎬 <b>{video['title']}</b>\n"
        f"🆔 ID: <code>{video['code']}</code>\n\n"
        f"🔗 Link:\n{link}",
        parse_mode="HTML",
        disable_web_page_preview=True
    )


async def deliver_video(message, video):
    caption = video.get("caption") or video["title"]

    try:
        if video["media_type"] == "document":
            await message.answer_document(
                video["file_id"],
                caption=caption
            )
        else:
            await message.answer_video(
                video["file_id"],
                caption=caption
            )

    except TelegramBadRequest:
        await message.answer("❌ Video send nahi ho payi.")


@dp.message(CommandStart())
async def start_handler(message, command):

    payload = (command.args or "").strip()

    if payload.startswith("vid_"):

        code = payload[4:]

        video = await videos_col.find_one({
            "code": code
        })

        if not video:
            await message.answer(
                "❌ Invalid ya deleted video link."
            )
            return

        if not await membership_ok(message.from_user.id):

            await message.answer(
                "📢 Video access karne ke liye "
                "pehle required channels join karo.",
                reply_markup=await channel_keyboard()
            )
            return

        await deliver_video(message, video)
        return

    await message.answer(
        "👋 <b>Welcome to Anime Video Bot!</b>\n\n"
        "Video download karne ke liye uska special link open karo.\n\n"
        "📌 Admins: /help",
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "verify")
async def verify_handler(callback):

    if await membership_ok(callback.from_user.id):

        await callback.answer(
            "✅ Membership verified! "
            "Original video link dobara open karo.",
            show_alert=True
        )

        await callback.message.edit_text(
            "✅ Membership verified!\n"
            "Ab original video link dobara open karo."
        )

    else:
        await callback.answer(
            "❌ Pehle saare channels join karo.",
            show_alert=True
        )


@dp.message(Command("help"))
async def help_handler(message):

    if not await admin_required(message):
        return

    await message.answer(
        "<b>ADMIN COMMANDS</b>\n\n"
        "/addvideo - Add video\n"
        "/videos - My videos\n"
        "/delvideo CODE - Delete video\n"
        "/addadmin ID - Add admin\n"
        "/removeadmin ID - Remove admin\n"
        "/admins - Admin list\n"
        "/addchannel @username - Add channel\n"
        "/removechannel @username - Remove channel\n"
        "/channels - Channel list\n"
        "/cancel - Cancel upload",
        parse_mode="HTML"
    )


@dp.message(Command("addvideo"))
async def addvideo_handler(message):

    if not await admin_required(message):
        return
