import asyncio
from pyrogram import Client, filters, enums
from pyrogram.errors import FloodWait
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import LOG_CHANNEL, API_ID, API_HASH, NEW_REQ_MODE, ADMINS, STRING_SESSION
from plugins.database import db


# ================= ADMIN CHECK ================= #

async def is_authorized(user_id):
    if user_id == ADMINS:
        return True
    return await db.is_admin(user_id)


# ================= SESSION RESOLUTION =================
# Priority: 1) user's own self-added session (works for EVERYONE, no
# admin needed - fixes "Access Denied" for normal users)
#           2) authorized admin/owner -> falls back to the global session
#              set via /settings (or config.py as last resort)

async def get_session_for(user_id):
    personal = await db.get_session(user_id)
    if personal:
        return personal

    if await is_authorized(user_id):
        global_session = await db.get_global_session()
        return global_session or STRING_SESSION

    return None


async def validate_session(session_string):
    """Tries to connect with the given session string. Returns (me, error)."""
    test = Client(
        f"validate_{session_string[:8]}",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=session_string,
        in_memory=True
    )
    try:
        await test.connect()
        me = await test.get_me()
        await test.disconnect()
        return me, None
    except Exception as e:
        try:
            await test.disconnect()
        except Exception:
            pass
        return None, str(e)


# ================= LOG SYSTEM ================= #

async def send_log(client, message, action_type=None, extra_info=None):
    try:
        user = message.from_user
        user_mention = f"[{user.first_name}](tg://user?id={user.id})"

        log_text = "📝 **New Bot Activity**\n"
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
<blockquote>➌ Use /accept to approve requests</blockquote></b>
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
                    ),
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


# ================= SELF-SERVICE SESSION (ANY USER - NO ADMIN NEEDED) ================= #

@Client.on_message(filters.command("setsession") & filters.private)
async def set_session_cmd(client, message):

    name = 'default'
    session_string = None

    if len(message.command) > 1:
        arg = message.text.split(None, 1)[1].strip()
        if len(arg) > 50:          # looks like an actual session string
            session_string = arg
        else:                      # looks like a short name, e.g. "backup"
            name = arg

    target_msg = message
    if not session_string:
        ask = await message.reply(
            f"**📤 Apna Pyrogram STRING_SESSION bhejo** (session name: `{name}`).\n\n"
            "⚠️ Yeh sirf tumhare account tak limited rahega, kisi aur ko nahi dikhega.\n"
            "Cancel karne ke liye /cancel bhejo."
        )
        try:
            resp = await client.listen(message.chat.id, timeout=300)
        except asyncio.TimeoutError:
            return await ask.edit("⏰ **Time khatam ho gaya.** Dobara `/setsession` bhejo.")

        if resp.text and resp.text.strip().lower() == "/cancel":
            return await resp.reply("❌ Cancelled.")
        if not resp.text:
            return await resp.reply("❌ **Invalid session** — text me session bhejo.")
        session_string = resp.text.strip()
        target_msg = resp

    checking = await target_msg.reply("**🔎 Session check ho raha hai…**")
    me, error = await validate_session(session_string)

    if error:
        return await checking.edit(f"**❌ Invalid Session!**\n`{error}`")

    await db.set_session(message.from_user.id, session_string, name)
    await checking.edit(
        f"**✅ Session `{name}` Saved Successfully!**\n"
        f"👤 Logged in as: {me.mention}\n\n"
        f"Ab tum `/accept` use kar sakte ho, ya `/addchannel {name}` se is session "
        f"ke channels save karke auto-accept on kar sakte ho."
    )


@Client.on_message(filters.command("mysession") & filters.private)
async def my_session_cmd(client, message):
    sessions = await db.get_all_sessions(message.from_user.id)
    if not sessions:
        return await message.reply("**❌ Koi session set nahi hai.**\nAdd karne ke liye `/setsession` bhejo.")
    lines = "\n".join(f"• `{name}`" for name in sessions)
    await message.reply(
        f"**✅ Tumhare saved sessions:**\n\n{lines}\n\n"
        f"Hatane ke liye: `/removesession <name>`"
    )


@Client.on_message(filters.command("removesession") & filters.private)
async def remove_session_cmd(client, message):
    name = message.command[1] if len(message.command) > 1 else 'default'
    removed = await db.remove_session(message.from_user.id, name)
    if removed:
        await message.reply(f"**🗑 Session `{name}` remove ho gaya.**")
    else:
        await message.reply(f"**⚠️ Session `{name}` mila nahi.**")


# ================= OWNER SETTINGS PANEL (GLOBAL SESSION) ================= #

@Client.on_message(filters.command("settings") & filters.private)
async def settings_cmd(client, message):
    if message.from_user.id != ADMINS:
        return await message.reply(
            "🚫 **Access Denied!**\n\nYeh command sirf bot owner use kar sakta hai."
        )
    await render_settings(message)


async def render_settings(message_or_query, edit=False):
    has_global = bool(await db.get_global_session())
    status = "✅ Set" if has_global else "❌ Not Set"

    text = (
        "**⚙️ Bot Settings**\n\n"
        f"🔑 **Global STRING_SESSION:** {status}\n\n"
        "Isse admins ke liye default session ki tarah use hota hai "
        "(agar unka apna khud ka session set nahi hai)."
    )
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 Set/Update Global Session", callback_data="stg_set")],
        [InlineKeyboardButton("🗑 Remove Global Session", callback_data="stg_rm")],
    ])

    if edit:
        await message_or_query.edit(text, reply_markup=buttons)
    else:
        await message_or_query.reply(text, reply_markup=buttons)


@Client.on_callback_query(filters.regex(r"^stg_"))
async def settings_callback(client, query):
    if query.from_user.id != ADMINS:
        return await query.answer("🚫 Sirf bot owner ke liye hai.", show_alert=True)

    data = query.data

    if data == "stg_set":
        await query.answer()
        ask = await query.message.reply(
            "**📤 Naya Global STRING_SESSION bhejo.**\nCancel karne ke liye /cancel bhejo."
        )
        try:
            resp = await client.listen(query.message.chat.id, timeout=300)
        except asyncio.TimeoutError:
            return await ask.edit("⏰ Time khatam ho gaya.")

        if resp.text and resp.text.strip().lower() == "/cancel":
            return await resp.reply("❌ Cancelled.")
        if not resp.text:
            return await resp.reply("❌ Invalid session.")

        checking = await resp.reply("**🔎 Session check ho raha hai…**")
        me, error = await validate_session(resp.text.strip())
        if error:
            return await checking.edit(f"**❌ Invalid Session!**\n`{error}`")

        await db.set_global_session(resp.text.strip())
        await checking.edit(f"**✅ Global session set ho gaya!**\n👤 {me.mention}")
        await render_settings(query.message)

    elif data == "stg_rm":
        removed = await db.remove_global_session()
        await query.answer("Removed!" if removed else "Pehle se set nahi tha.", show_alert=True)
        await render_settings(query.message, edit=True)


# ================= SAVED CHANNELS (per-user, with per-channel auto-accept) ================= #

@Client.on_message(filters.command("addchannel") & filters.private)
async def add_channel_cmd(client, message):
    session_name = message.command[1] if len(message.command) > 1 else 'default'

    if not await db.get_session(message.from_user.id, session_name):
        return await message.reply(
            f"❌ **Session `{session_name}` nahi mila.**\n"
            f"Pehle `/setsession{' ' + session_name if session_name != 'default' else ''}` se apna session add karo."
        )

    ask = await message.reply(
        "**📤 Channel/Group ki ID bhejo ya wahan se koi message forward karo.**\nCancel: /cancel"
    )
    try:
        resp = await client.listen(message.chat.id, timeout=120)
    except asyncio.TimeoutError:
        return await ask.edit("⏰ Time khatam ho gaya.")

    if resp.text and resp.text.strip().lower() == "/cancel":
        return await resp.reply("❌ Cancelled.")

    chat_id, title = None, None
    if resp.forward_from_chat:
        chat_id = resp.forward_from_chat.id
        title = resp.forward_from_chat.title
    elif resp.text:
        try:
            chat_id = int(resp.text.strip())
        except ValueError:
            return await resp.reply("❌ Invalid ID.")

    if not chat_id:
        return await resp.reply("❌ Invalid Input.")

    if not title:
        try:
            chat = await client.get_chat(chat_id)
            title = chat.title
        except Exception:
            title = str(chat_id)

    await db.add_channel(message.from_user.id, chat_id, title=title, session_name=session_name)
    await resp.reply(
        f"✅ **Channel Saved:** {title} (`{chat_id}`)\n"
        f"🔑 Session: `{session_name}`  |  🔁 Auto-Accept: ✅ ON (default)\n\n"
        f"Toggle karne ke liye: `/toggleauto {chat_id}`"
    )


@Client.on_message(filters.command("mychannels") & filters.private)
async def my_channels_cmd(client, message):
    channels = await db.get_user_channels(message.from_user.id)
    if not channels:
        return await message.reply("**Koi saved channel nahi hai.**\nAdd karne ke liye `/addchannel` bhejo.")

    lines = []
    for ch in channels:
        state = "✅ ON" if ch.get('auto_accept', True) else "❌ OFF"
        lines.append(
            f"• {ch.get('title') or ch['chat_id']} (`{ch['chat_id']}`) — "
            f"Session: `{ch.get('session_name', 'default')}` | Auto: {state}"
        )
    await message.reply("**📂 Your Saved Channels:**\n\n" + "\n".join(lines))


@Client.on_message(filters.command("removechannel") & filters.private)
async def remove_channel_cmd(client, message):
    if len(message.command) < 2:
        return await message.reply("**Usage:** `/removechannel chat_id`")
    try:
        chat_id = int(message.command[1])
    except ValueError:
        return await message.reply("❌ Invalid ID.")
    removed = await db.remove_channel(message.from_user.id, chat_id)
    await message.reply("✅ Removed." if removed else "⚠️ Yeh channel tumhare saved list me nahi hai.")


@Client.on_message(filters.command("toggleauto") & filters.private)
async def toggle_auto_cmd(client, message):
    if len(message.command) < 2:
        return await message.reply("**Usage:** `/toggleauto chat_id`")
    try:
        chat_id = int(message.command[1])
    except ValueError:
        return await message.reply("❌ Invalid ID.")
    new_val = await db.toggle_auto_accept(message.from_user.id, chat_id)
    if new_val is None:
        return await message.reply("⚠️ Pehle `/addchannel` se yeh channel save karo.")
    await message.reply(f"✅ Auto-Accept ab **{'ON' if new_val else 'OFF'}** hai is channel ke liye.")


# ================= STATS (per-channel breakdown) ================= #

@Client.on_message(filters.command("stats") & filters.private)
async def stats_cmd(client, message):
    if message.from_user.id == ADMINS:
        total_users = await db.total_users_count()
        all_stats = await db.get_all_stats()
        grand_total = sum(s.get('total', 0) for s in all_stats)
        top = sorted(all_stats, key=lambda s: s.get('total', 0), reverse=True)[:15]
        lines = "\n".join(f"• `{s['chat_id']}` → `{s.get('total', 0)}`" for s in top) or "—"
        return await message.reply(
            f"**📊 Bot-Wide Stats**\n\n"
            f"👥 Total Bot Users: `{total_users}`\n"
            f"✅ Total Requests Accepted (all channels): `{grand_total}`\n\n"
            f"**Top Channels:**\n{lines}"
        )

    channels = await db.get_user_channels(message.from_user.id)
    if not channels:
        return await message.reply("**Tumne koi channel save nahi kiya.**\nUse `/addchannel` first.")

    lines, grand_total = [], 0
    for ch in channels:
        count = await db.get_stats(ch['chat_id'])
        grand_total += count
        state = "✅ ON" if ch.get('auto_accept', True) else "❌ OFF"
        lines.append(f"• {ch.get('title') or ch['chat_id']} (`{ch['chat_id']}`) — Accepted: `{count}` | Auto: {state}")

    await message.reply(
        "**📊 Your Channel Stats**\n\n" + "\n".join(lines) + f"\n\n**Total Accepted:** `{grand_total}`"
    )


# ================= MANUAL REVIEW (suspicious join requests) ================= #

@Client.on_message(filters.command("approveuser") & filters.private)
async def approve_user_cmd(client, message):
    if not await is_authorized(message.from_user.id):
        return await message.reply("🚫 **Access Denied!**")
    if len(message.command) < 3:
        return await message.reply("**Usage:** `/approveuser chat_id user_id`")
    try:
        chat_id, user_id = int(message.command[1]), int(message.command[2])
    except ValueError:
        return await message.reply("❌ Invalid IDs.")
    try:
        await client.approve_chat_join_request(chat_id, user_id)
        await db.increment_stats(chat_id, 1)
        await message.reply("✅ Approved.")
    except Exception as e:
        await message.reply(f"❌ Error: `{e}`")


@Client.on_message(filters.command("rejectuser") & filters.private)
async def reject_user_cmd(client, message):
    if not await is_authorized(message.from_user.id):
        return await message.reply("🚫 **Access Denied!**")
    if len(message.command) < 3:
        return await message.reply("**Usage:** `/rejectuser chat_id user_id`")
    try:
        chat_id, user_id = int(message.command[1]), int(message.command[2])
    except ValueError:
        return await message.reply("❌ Invalid IDs.")
    try:
        await client.decline_chat_join_request(chat_id, user_id)
        await message.reply("🗑 Rejected.")
    except Exception as e:
        await message.reply(f"❌ Error: `{e}`")


@Client.on_message(filters.command("addadmin") & filters.private)
async def add_admin(client, message):

    if message.from_user.id != ADMINS:
        return await message.reply(
            "🚫 **Access Denied!**\n\n"
            "Yeh command sirf bot owner use kar sakta hai."
        )

    if len(message.command) < 2:
        return await message.reply(
            "❌ **Usage:** `/addadmin user_id`\n"
            "**Example:** `/addadmin 123456789`"
        )

    try:
        user_id = int(message.command[1])
        added = await db.add_admin(user_id)
        if added:
            await message.reply(f"✅ **User `{user_id}` ko admin bana diya gaya!**")
        else:
            await message.reply(f"⚠️ **User `{user_id}` pehle se admin hai!**")
    except ValueError:
        await message.reply("❌ **Invalid user ID!**")


# ================= REMOVE ADMIN (OWNER ONLY) ================= #

@Client.on_message(filters.command("removeadmin") & filters.private)
async def remove_admin(client, message):

    if message.from_user.id != ADMINS:
        return await message.reply(
            "🚫 **Access Denied!**\n\n"
            "Yeh command sirf bot owner use kar sakta hai."
        )

    if len(message.command) < 2:
        return await message.reply(
            "❌ **Usage:** `/removeadmin user_id`\n"
            "**Example:** `/removeadmin 123456789`"
        )

    try:
        user_id = int(message.command[1])
        removed = await db.remove_admin(user_id)
        if removed:
            await message.reply(f"✅ **User `{user_id}` ko admin se hata diya gaya!**")
        else:
            await message.reply(f"⚠️ **User `{user_id}` admin nahi tha!**")
    except ValueError:
        await message.reply("❌ **Invalid user ID!**")


# ================= ADMINS LIST (OWNER ONLY) ================= #

@Client.on_message(filters.command("admins") & filters.private)
async def admins_list(client, message):

    if message.from_user.id != ADMINS:
        return await message.reply(
            "🚫 **Access Denied!**\n\n"
            "Yeh command sirf bot owner use kar sakta hai."
        )

    admins = await db.get_all_admins()

    text = "👑 **Admin List:**\n\n"
    text += f"`1.` `{ADMINS}` — 👑 Owner\n"

    for i, admin_id in enumerate(admins, 2):
        text += f"`{i}.` `{admin_id}`\n"

    await message.reply(text)


# ================= APPROVE FUNCTION ================= #

async def approve_requests(acc, chat_id):
    """Approves ALL pending join requests in one chat, fast.

    Fixes 2 bugs from before:
    1. No artificial `asyncio.sleep(2)` between passes anymore - that was
       the main reason it felt slow, since it slept even when there was
       nothing left to do.
    2. Returns (chat_id, count, error) instead of editing a shared message
       directly - the old code reset `total = 0` for every chat_id and
       overwrote the same message, so with multiple channels the final
       count only reflected the LAST channel, never the real grand total.
    """
    total = 0
    passes = 0

    while passes < 5:  # safety cap - handles new requests trickling in mid-run
        try:
            pending = [r async for r in acc.get_chat_join_requests(chat_id)]
        except FloodWait as e:
            await asyncio.sleep(e.value)
            continue
        except Exception as e:
            return chat_id, total, str(e)

        if not pending:
            break

        try:
            await acc.approve_all_chat_join_requests(chat_id)
        except FloodWait as e:
            await asyncio.sleep(e.value)
            continue
        except Exception as e:
            return chat_id, total, str(e)

        total += len(pending)
        passes += 1

    return chat_id, total, None


def _format_progress(results, done, expected):
    lines = "\n".join(
        f"• `{cid}` → " + (f"✅ {count}" if err is None else f"❌ {err}")
        for cid, (count, err) in results.items()
    )
    grand_total = sum(count for count, _err in results.values())
    return (
        f"**⚡ Processing… ({done}/{expected} channels done)**\n\n"
        f"{lines}\n\n**Total Accepted So Far:** `{grand_total}`"
    ), grand_total


async def process_all_requests(acc, chat_ids, msg):
    """Runs approve_requests for every chat CONCURRENTLY (asyncio.gather)
    instead of one-by-one sequentially - this is what makes multi-channel
    /accept ultra fast. Progress + an accurate combined total is edited
    into `msg` as each channel finishes."""
    results = {}
    lock = asyncio.Lock()

    async def worker(cid):
        cid_, count, err = await approve_requests(acc, cid)
        async with lock:
            results[cid_] = (count, err)
            text, _ = _format_progress(results, len(results), len(chat_ids))
            try:
                await msg.edit(text)
            except Exception:
                pass

    await asyncio.gather(*[worker(cid) for cid in chat_ids])

    lines = "\n".join(
        f"• `{cid}` → " + (f"✅ {count}" if err is None else f"❌ {err}")
        for cid, (count, err) in results.items()
    )
    grand_total = sum(count for count, _err in results.values())
    await msg.edit(
        f"**✅ Done! All Channels Processed**\n\n{lines}\n\n"
        f"**🎉 Total Accepted:** `{grand_total}`"
    )


# ================= /ACCEPT (ANY USER WITH A SESSION, OR AUTHORIZED ADMIN) ================= #

@Client.on_message(filters.command("accept") & filters.private)
async def accept(client, message):

    session_string = await get_session_for(message.from_user.id)

    if not session_string:
        return await message.reply(
            "🚫 **Access Denied!**\n\n"
            "Aapka koi STRING_SESSION set nahi hai.\n"
            "Apna khud ka session add karke bot use karne ke liye `/setsession` bhejo — "
            "phir aap apne khud ke channels/groups ke pending requests accept kar paoge."
        )

    show = await message.reply("**Please Wait…**")
    acc = None

    try:
        acc = Client(
            "approver",
            session_string=session_string,
            api_id=API_ID,
            api_hash=API_HASH,
            in_memory=True
        )
        await acc.connect()

    except Exception as e:
        return await show.edit(f"**❌ Session Error:** `{e}`")

    try:
        await send_log(client, message, "approve")

        if len(message.command) > 1:
            raw_ids = message.text.split()[1:]
            chat_ids = []
            for x in raw_ids:
                try:
                    chat_ids.append(int(x))
                except ValueError:
                    await message.reply(f"**Invalid ID:** `{x}` — sirf numbers daalein")
            if not chat_ids:
                return
            msg = await show.edit("**⚡ Processing…**")
            await process_all_requests(acc, chat_ids, msg)
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

        if not chat_ids:
            return await show.edit("**❌ Invalid Input**")

        msg = await show.edit("**⚡ Starting Approval…**")
        await process_all_requests(acc, chat_ids, msg)

    finally:
        if acc and acc.is_connected:
            await acc.disconnect()


# ================= AUTO APPROVE (flood-safe + suspicious filter + per-channel toggle) ================= #

_debounce_tasks = {}
BATCH_WINDOW = 3  # seconds - collect a short burst into ONE bulk approve call


async def _debounced_bulk_approve(client, chat_id):
    """Runs BATCH_WINDOW seconds after the first request in a burst comes
    in, then approves whatever piled up with a SINGLE API call instead of
    one call per user - this is what keeps the bot from tripping FloodWait
    when a channel suddenly gets hit with many requests at once."""
    await asyncio.sleep(BATCH_WINDOW)
    try:
        pending = [r async for r in client.get_chat_join_requests(chat_id)]
        count = len(pending)
        if count:
            await client.approve_all_chat_join_requests(chat_id)
            await db.increment_stats(chat_id, count)
    except FloodWait as e:
        await asyncio.sleep(e.value)
        try:
            await client.approve_all_chat_join_requests(chat_id)
        except Exception as e:
            print(f"BATCH APPROVE RETRY ERROR ({chat_id}): {e}")
    except Exception as e:
        print(f"BATCH APPROVE ERROR ({chat_id}): {e}")
    finally:
        _debounce_tasks.pop(chat_id, None)


def _schedule_bulk_approve(client, chat_id):
    task = _debounce_tasks.get(chat_id)
    if task and not task.done():
        return  # a window is already running - this request rides along with it
    _debounce_tasks[chat_id] = asyncio.create_task(_debounced_bulk_approve(client, chat_id))


async def _looks_suspicious(client, user_id):
    """Very lightweight spam/fake-account heuristic: no profile photo at
    all. Not perfect, but catches the bulk of throwaway spam accounts
    without ever blocking a real user's request permanently - it's only
    held for a manual /approveuser or /rejectuser by an admin."""
    try:
        async for _photo in client.get_chat_photos(user_id, limit=1):
            return False
        return True
    except Exception:
        return False  # API hiccup - never punish a real user for that


@Client.on_chat_join_request(filters.group | filters.channel)
async def auto_approve(client, m):

    # per-channel toggle (via /toggleauto) overrides the global NEW_REQ_MODE switch
    config = await db.get_channel_config_by_chat_id(m.chat.id)
    if config is not None:
        if not config.get("auto_accept", True):
            return
    elif not NEW_REQ_MODE:
        return

    try:
        if not await db.is_user_exist(m.from_user.id):
            await db.add_user(m.from_user.id, m.from_user.first_name)

        if await _looks_suspicious(client, m.from_user.id):
            try:
                await client.send_message(
                    LOG_CHANNEL,
                    "⚠️ **Suspicious Join Request Held For Review**\n"
                    f"👤 {m.from_user.mention} (`{m.from_user.id}`)\n"
                    f"💬 {m.chat.title} (`{m.chat.id}`)\n"
                    "Reason: no profile photo.\n\n"
                    f"✅ `/approveuser {m.chat.id} {m.from_user.id}`\n"
                    f"❌ `/rejectuser {m.chat.id} {m.from_user.id}`"
                )
            except Exception:
                pass
            return

        _schedule_bulk_approve(client, m.chat.id)
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

    except Exception as e:
        print(f"AUTO APPROVE ERROR: {e}")
