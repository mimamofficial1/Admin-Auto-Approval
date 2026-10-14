from pyrogram.errors import InputUserDeactivated, FloodWait, UserIsBlocked, PeerIdInvalid
from pyrogram import enums
from plugins.database import db
from plugins import ui
from plugins.ui import note, screen, kv, quote
import asyncio
import datetime
import time
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

HTML = enums.ParseMode.HTML


async def broadcast_messages(user_id, message):
    try:
        await message.copy(chat_id=user_id)
        return "Success"
    except FloodWait as e:
        await asyncio.sleep(e.value)
        return await broadcast_messages(user_id, message)
    except InputUserDeactivated:
        return "Deleted"
    except UserIsBlocked:
        return "Blocked"
    except PeerIdInvalid:
        return "Error"
    except Exception as e:
        logger.error(f"Error sending to {user_id}: {e}")
        return "Error"


def _progress(done, total, success, blocked, deleted, failed) -> str:
    return screen(
        "📢", "Broadcast in progress",
        quote("\n".join([
            kv("Users", total), kv("Done", f"{done}/{total}"),
            kv("Success", success), kv("Blocked", blocked),
            kv("Deleted", deleted), kv("Failed", failed),
        ])),
    )


async def run_broadcast(bot, admin_message, b_msg):
    """Core broadcast loop - takes the message to copy out (b_msg) and
    reports progress into admin_message. Called from the button-menu
    handler in commands.py (button ke through 'send me the message to
    broadcast' poochh ke yeh function call hota hai)."""
    users = await db.get_all_users()
    total_users = await db.total_users_count()

    if total_users == 0:
        return await admin_message.reply_text(ui.finish(note("err", "No users in the database")), parse_mode=HTML)

    sts = await admin_message.reply_text(ui.finish(note("ok", "Broadcast started")), parse_mode=HTML)
    start_time = time.time()

    done = success = blocked = deleted = failed = 0

    async for user in users:
        user_id = user.get("id")
        if not user_id:
            failed += 1
            done += 1
            continue

        result = await broadcast_messages(int(user_id), b_msg)

        if result == "Success":
            success += 1
        elif result == "Blocked":
            blocked += 1
        elif result == "Deleted":
            deleted += 1
        else:
            failed += 1

        done += 1
        await asyncio.sleep(0.05)

        if done % 25 == 0:
            await sts.edit(ui.finish(_progress(done, total_users, success, blocked, deleted, failed)), parse_mode=HTML)

    time_taken = datetime.timedelta(seconds=int(time.time() - start_time))
    await sts.edit(
        ui.finish(screen(
            "✅", "Broadcast complete",
            quote("\n".join([
                kv("Time taken", str(time_taken)), kv("Users", total_users),
                kv("Success", success), kv("Blocked", blocked),
                kv("Deleted", deleted), kv("Failed", failed),
            ])),
        )),
        parse_mode=HTML,
    )


async def run_clean(bot, admin_message):
    """Core DB-cleanup loop, called from the button-menu handler."""
    users = await db.get_all_users()
    sts = await admin_message.reply_text(ui.finish(note("info", "Checking users…")), parse_mode=HTML)
    removed = checked = 0

    async for user in users:
        user_id = user.get("id")
        if not user_id:
            continue
        try:
            await bot.get_users(int(user_id))
        except Exception:
            await db.delete_user(int(user_id))
            removed += 1
        checked += 1
        if checked % 25 == 0:
            await sts.edit(ui.finish(note("info", "Checking users…", kv("Checked", checked) + "\n" + kv("Removed", removed))), parse_mode=HTML)

    await sts.edit(
        ui.finish(note("ok", "Clean-up complete", kv("Checked", checked) + "\n" + kv("Removed", removed))),
        parse_mode=HTML,
    )
