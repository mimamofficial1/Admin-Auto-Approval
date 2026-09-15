from pyrogram.errors import InputUserDeactivated, FloodWait, UserIsBlocked, PeerIdInvalid
from plugins.database import db
from pyrogram import Client, filters
from config import ADMINS
import asyncio
import datetime
import time
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


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


async def run_broadcast(bot, admin_message, b_msg):
    """Core broadcast loop - takes the message to copy out (b_msg) and
    reports progress into admin_message. Called from the button-menu
    handler in commands.py (button ke through 'send me the message to
    broadcast' poochh ke yeh function call hota hai)."""
    users = await db.get_all_users()
    total_users = await db.total_users_count()

    if total_users == 0:
        return await admin_message.reply_text("❌ No users in database.")

    sts = await admin_message.reply_text("🚀 Broadcast Started...")
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
            await sts.edit(
                f"📢 Broadcast In Progress...\n\n"
                f"👥 Total Users: {total_users}\n"
                f"✅ Success: {success}\n"
                f"🚫 Blocked: {blocked}\n"
                f"🗑 Deleted: {deleted}\n"
                f"❌ Failed: {failed}\n"
                f"📊 Completed: {done}/{total_users}"
            )

    time_taken = datetime.timedelta(seconds=int(time.time() - start_time))
    await sts.edit(
        f"✅ Broadcast Completed!\n\n"
        f"⏱ Time Taken: {time_taken}\n\n"
        f"👥 Total Users: {total_users}\n"
        f"✅ Success: {success}\n"
        f"🚫 Blocked: {blocked}\n"
        f"🗑 Deleted: {deleted}\n"
        f"❌ Failed: {failed}"
    )


async def run_clean(bot, admin_message):
    """Core DB-cleanup loop, called from the button-menu handler."""
    users = await db.get_all_users()
    sts = await admin_message.reply_text("🧹 Checking users...")
    removed = checked = 0

    async for user in users:
        user_id = user.get("id")
        if not user_id:
            continue
        try:
            await bot.get_users(int(user_id))
        except:
            await db.delete_user(int(user_id))
            removed += 1
        checked += 1
        if checked % 25 == 0:
            await sts.edit(f"🔍 Checked: {checked}\n🗑 Removed: {removed}")

    await sts.edit(
        f"✅ Clean Completed!\n\n"
        f"🔍 Total Checked: {checked}\n"
        f"🗑 Total Removed: {removed}"
    )
