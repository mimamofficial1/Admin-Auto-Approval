import asyncio
from pyrogram import Client, filters, enums
from pyrogram.errors import FloodWait
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import LOG_CHANNEL, API_ID, API_HASH, NEW_REQ_MODE, ADMINS, STRING_SESSION
from plugins.database import db


# ================= LOG SYSTEM ================= #

async def send_log(client, message, action_type=None, extra_info=None):
    try:
        user = message.from_user
        user_mention = f"[{user.first_name}](tg://user?id={user.id})"

        log_text = f"📝 **New Bot Activity**\n"
        log_text += f"👤 **User:** {user_mention}\n"
        log_text += f"🆔 **User ID:** `{user.id}`\n"

        if action_type == "start":
            log_text += "📱 **Action:** Started the bot\n"
        elif action_type == "approve":
            log_text += "📱 **Action:** Admin Approved Pending Requests\n"
        elif action_type == "auto":
            log_text += "📱 **Action:** Auto Approved Join Request\n"
            log_text += f"💬 **Chat:** {message.chat.title}\n"
            log_text += f"🆔 **Chat ID:** `{message.chat.id}`\n"

        if extra_info:
            log_text += f"\nℹ️ **Extra:** {extra_info}\n"

        try:
            await client.send_message(
                LOG_CHANNEL,
                log_text,
                parse_mode=enums.ParseMode.MARKDOWN
            )
        except FloodWait as e:
            await asyncio.sleep(e.value)
            await client.send_message(
                LOG_CHANNEL,
                log_text,
                parse_mode=enums.ParseMode.MARKDOWN
            )

    except Exception as e:
        print(f"LOG ERROR: {e}")


# ================= START ================= #

@Client.on_message(filters.command("start"))
async def start_message(c, m):

    if not await db.is_user_exist(m.from_user.id):
        await db.add_user(m.from_user.id, m.from_user.first_name)
        await send_log(c, m, "start")

    bot_username = (await c.get_me()).username

    caption = f"""<b><blockquote>✨ Welcome {m.from_user.mention} ✨ @PendingXBot Join Request Bot</blockquote>
<blockquote>✅ Accept New Join Requests Instantly</blockquote>
<blockquote>🕒 Approve All Pending Requests Easily</blockquote>
<blockquote>📌 How To Get Started:</blockquote>
<blockquote>➊ Add me to your Channel or Group</blockquote>
<blockquote>➋ Give Admin Rights (Invite Users Permission)</blockquote>
<blockquote>➌ Use /accept to approve requests</blockquote>
━━━━━━━━━━━━━━━━━━━
🚀 Fast • Secure • Automatic</b>
"""

    await m.reply_photo(
        "https://graph.org/file/74f3b07e680826de251ee-11c68075c29d2227d5.jpg",
        caption=caption,
        parse_mode=enums.ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "➕ Add Me To Your Channel",
                        url=f"https://t.me/{bot_username}?startchannel=true"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "➕ Add Me To Your Group",
                        url=f"https://t.me/{bot_username}?startgroup=true"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "💝 Subscribe Channel",
                        url="https://t.me/Mrn_Officialx"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "❣️ Developer",
                        url="https://t.me/mimam_officialx"
                    ),
                    InlineKeyboardButton(
                        "🌷 Update",
                        url="https://t.me/+u6qe756hjylkNmE1"
                    )
                ]
            ]
        )
    )


# ================= APPROVE FUNCTION ================= #

async def approve_requests(acc, chat_id, msg):
    total = 0

    while True:
        try:
            join_requests = [
                req async for req in acc.get_chat_join_requests(chat_id)
            ]

            if not join_requests:
                break

            total += len(join_requests)

            await msg.edit(f"**Processing…**\nAccepted: `{total}`")

            await acc.approve_all_chat_join_requests(chat_id)
            await asyncio.sleep(2)

        except FloodWait as e:
            await asyncio.sleep(e.value)
            continue

        except Exception as e:
            await msg.edit(f"**❌ Error:** `{e}`")
            return

    await msg.edit(
        f"**✅ Done! Accepted All Requests**\n\nTotal: `{total}`"
    )


# ================= /ACCEPT (ADMIN ONLY) ================= #

@Client.on_message(filters.command("accept") & filters.private & filters.user(ADMINS))
async def accept(client, message):

    if not STRING_SESSION:
        return await message.reply("**❌ STRING_SESSION not set in config!**")

    show = await message.reply("**Please Wait…**")

    acc = None

    try:
        acc = Client(
            "approver",
            session_string=STRING_SESSION,
            api_id=API_ID,
            api_hash=API_HASH
        )
        await acc.connect()

    except Exception as e:
        return await show.edit(f"**❌ Session Error:** `{e}`")

    try:
        await send_log(client, message, "approve")

        if len(message.command) > 1:
            ids = message.text.split()[1:]
            msg = await show.edit("**Processing IDs…**")

            for x in ids:
                try:
                    chat_id = int(x)
                    await approve_requests(acc, chat_id, msg)
                except ValueError:
                    await message.reply(f"**Invalid ID:** `{x}` — sirf numbers daalein")
                except Exception as e:
                    await message.reply(f"Failed For `{x}` → `{e}`")
            return

        await show.edit(
            "**Send Channel ID / Multiple IDs\n"
            "Or Forward Message From Channel**"
        )

        vj = await client.listen(message.chat.id)

        chat_ids = []

        if (
            vj.forward_from_chat
            and vj.forward_from_chat.type
            not in [enums.ChatType.PRIVATE, enums.ChatType.BOT]
        ):
            chat_ids.append(vj.forward_from_chat.id)

        elif vj.text:
            for x in vj.text.split():
                try:
                    chat_ids.append(int(x))
                except ValueError:
                    pass
        else:
            return await message.reply("**❌ Invalid Input**")

        await vj.delete()

        msg = await show.edit("**Starting Approval…**")

        for chat_id in chat_ids:
            await approve_requests(acc, chat_id, msg)

    finally:
        if acc and acc.is_connected:
            await acc.disconnect()


# ================= NON ADMIN ================= #

@Client.on_message(filters.command("accept") & filters.private & ~filters.user(ADMINS))
async def accept_non_admin(client, message):
    await message.reply("**❌ You are not authorized to use this command.**")


# ================= AUTO APPROVE ================= #

@Client.on_chat_join_request(filters.group | filters.channel)
async def auto_approve(client, m):

    if not NEW_REQ_MODE:
        return

    try:
        if not await db.is_user_exist(m.from_user.id):
            await db.add_user(m.from_user.id, m.from_user.first_name)

        await client.approve_chat_join_request(
            chat_id=m.chat.id,
            user_id=m.from_user.id
        )

        await send_log(client, m, "auto")

        try:
            await client.send_message(
                chat_id=m.from_user.id,
                text=f"""<b><blockquote>Hello {m.from_user.mention}!</blockquote>
<blockquote>Welcome To {m.chat.title}</blockquote>

<blockquote>Powered By : @Mrn_Officialx</blockquote>
</b>""",
                parse_mode=enums.ParseMode.HTML
            )
        except Exception:
            pass

    except FloodWait as e:
        await asyncio.sleep(e.value)
        try:
            await client.approve_chat_join_request(
                chat_id=m.chat.id,
                user_id=m.from_user.id
            )
        except Exception as e:
            print(f"AUTO APPROVE RETRY ERROR: {e}")

    except Exception as e:
        print(f"AUTO APPROVE ERROR: {e}")
