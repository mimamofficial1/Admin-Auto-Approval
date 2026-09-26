import asyncio
import aiohttp
from pyrogram import Client, filters, enums
from pyrogram.errors import (
    FloodWait, PhoneNumberInvalid, PhoneCodeInvalid, PhoneCodeExpired,
    SessionPasswordNeeded, PasswordHashInvalid,
)
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import (
    LOG_CHANNEL, API_ID, API_HASH, NEW_REQ_MODE, ADMINS, STRING_SESSION,
    GEMINI_API_KEY, GEMINI_MODEL,
)
from plugins.database import db
from plugins.broadcast import run_broadcast, run_clean
from pyrogram import raw


# ================= ADMIN CHECK ================= #

async def is_authorized(user_id):
    if user_id == ADMINS:
        return True
    return await db.is_admin(user_id)


# ================= SESSION RESOLUTION =================
# Priority: 1) user's own self-added session (works for EVERYONE, no
# admin needed - fixes "Access Denied" for normal users)
#           2) authorized admin/owner -> falls back to the global session
#              set via Global Session panel (or config.py as last resort)

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
<blockquote>➌ Tap 🛠 Open Menu neeche, sab kuch buttons se ho jaayega</blockquote></b>
"""

    await m.reply_photo(
        "https://graph.org/file/74f3b07e680826de251ee-11c68075c29d2227d5.jpg",
        caption=caption,
        parse_mode=enums.ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🛠 Open Settings", callback_data="menu:main")],
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


# ============================================================================
# ==================== BUTTON MENU (replaces typed commands) ================
# ============================================================================
# Sab feature (login, session, channels, stats, admin tools) ab is menu ke
# buttons se hi chalte hain. Jahan text/number/session-string input zaroori
# hai (phone, OTP, channel ID, user ID waghera), wahan bot poochta hai aur
# client.listen() se agla message wait karta hai - bilkul waisa hi jaisa
# pehle /setsession, /addchannel me tha, bas ab typing ki jagah button dabane
# se shuru hota hai. Cancel karne ke liye hamesha /cancel bhejo.

MENU_TEXT = "🛠 <b>Menu</b>\n\nNeeche se koi option choose karo:"


def main_menu_markup(user_id) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("🔑 Login", callback_data="menu:login"),
         InlineKeyboardButton("📤 Add Session", callback_data="menu:addsession")],
        [InlineKeyboardButton("📋 My Sessions", callback_data="menu:mysessions"),
         InlineKeyboardButton("🗑 Remove Session", callback_data="menu:removesession")],
        [InlineKeyboardButton("➕ Add Channel", callback_data="menu:addchannel"),
         InlineKeyboardButton("📂 My Channels", callback_data="menu:mychannels")],
        [InlineKeyboardButton("📊 Stats", callback_data="menu:stats"),
         InlineKeyboardButton("⚡ Accept Pending", callback_data="menu:accept")],
    ]
    rows.append([InlineKeyboardButton("👑 Admin Panel", callback_data="menu:admin")])
    rows.append([InlineKeyboardButton("❌ Close", callback_data="menu:close")])
    return InlineKeyboardMarkup(rows)


def admin_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Approve User", callback_data="menu:approveuser"),
         InlineKeyboardButton("❌ Reject User", callback_data="menu:rejectuser")],
        [InlineKeyboardButton("👑 Manage Admins", callback_data="menu:manageadmins")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="menu:broadcast"),
         InlineKeyboardButton("🧹 Clean DB", callback_data="menu:clean")],
        [InlineKeyboardButton("🌐 Global Session", callback_data="menu:globalsession")],
        [InlineKeyboardButton("🔙 Back", callback_data="menu:main")],
    ])


def manage_admins_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Admin", callback_data="menu:addadmin"),
         InlineKeyboardButton("🗑 Remove Admin", callback_data="menu:removeadmin")],
        [InlineKeyboardButton("📋 Admins List", callback_data="menu:admins")],
        [InlineKeyboardButton("🔙 Back", callback_data="menu:admin")],
    ])


async def _listen_text(client, chat_id, prompt, entry, timeout=300):
    """Common helper: ask a question, wait for the next text reply. Returns
    the response Message, or None (and already replies to the user) if it
    timed out / was cancelled / wasn't text."""
    ask = await entry.reply(f"{prompt}\n\nCancel karne ke liye /cancel bhejo.")
    try:
        resp = await client.listen(chat_id, timeout=timeout)
    except asyncio.TimeoutError:
        await ask.edit("⏰ **Time khatam ho gaya.** Menu se dobara try karo.")
        return None
    if resp.text and resp.text.strip().lower() == "/cancel":
        await resp.reply("❌ Cancelled.")
        return None
    return resp


@Client.on_callback_query(filters.regex(r"^menu:(.+)$"))
async def cb_menu_router(client, query):
    user_id = query.from_user.id
    chat_id = query.message.chat.id
    entry = query.message
    key = query.matches[0].group(1)

    # ---- plain navigation (no access check needed) ----
    if key == "main":
        await query.answer()
        return await entry.edit(MENU_TEXT, parse_mode=enums.ParseMode.HTML, reply_markup=main_menu_markup(user_id))

    if key == "close":
        await query.answer()
        try:
            await entry.delete()
        except Exception:
            pass
        return

    # ---- admin-gated navigation ----
    if key == "admin":
        if not await is_authorized(user_id):
            return await query.answer("🚫 Sirf admin/owner ke liye.", show_alert=True)
        await query.answer()
        return await entry.edit("👑 <b>Admin Panel</b>", parse_mode=enums.ParseMode.HTML, reply_markup=admin_menu_markup())

    if key == "manageadmins":
        if user_id != ADMINS:
            return await query.answer("🚫 Sirf bot owner ke liye.", show_alert=True)
        await query.answer()
        return await entry.edit("👑 <b>Manage Admins</b>", parse_mode=enums.ParseMode.HTML, reply_markup=manage_admins_markup())

    if key == "globalsession":
        if user_id != ADMINS:
            return await query.answer("🚫 Sirf bot owner ke liye.", show_alert=True)
        await query.answer()
        return await render_settings(entry, edit=True)

    # ---- session actions ----
    if key == "login":
        await query.answer()
        return await _do_login(client, chat_id, user_id, entry)

    if key == "addsession":
        await query.answer()
        return await _do_addsession(client, chat_id, user_id, entry)

    if key == "mysessions":
        await query.answer()
        sessions = await db.get_all_sessions(user_id)
        if not sessions:
            text = "**❌ Koi session set nahi hai.**\nAdd karne ke liye 🔑 Login ya 📤 Add Session use karo."
        else:
            lines = "\n".join(f"• `{name}`" for name in sessions)
            text = f"**✅ Tumhare saved sessions:**\n\n{lines}"
        return await entry.reply(text)

    if key == "removesession":
        await query.answer()
        sessions = await db.get_all_sessions(user_id)
        if not sessions:
            return await entry.reply("**❌ Koi session set nahi hai.**")
        rows = [[InlineKeyboardButton(f"🗑 {name}", callback_data=f"sessrm:{name}")] for name in sessions]
        rows.append([InlineKeyboardButton("🔙 Back", callback_data="menu:main")])
        return await entry.reply("**Kaunsa session remove karna hai?**", reply_markup=InlineKeyboardMarkup(rows))

    # ---- channel actions ----
    if key == "addchannel":
        await query.answer()
        return await _do_addchannel_start(client, chat_id, user_id, entry)

    if key == "mychannels":
        await query.answer()
        return await _render_mychannels(entry, user_id)

    # ---- stats / accept ----
    if key == "stats":
        await query.answer()
        return await _do_stats(entry, user_id)

    if key == "accept":
        await query.answer()
        return await _do_accept(client, chat_id, user_id, entry)

    # ---- admin-only actions ----
    if key == "approveuser":
        if not await is_authorized(user_id):
            return await query.answer("🚫 Access Denied!", show_alert=True)
        await query.answer()
        return await _do_approve_reject(client, chat_id, entry, approve=True)

    if key == "rejectuser":
        if not await is_authorized(user_id):
            return await query.answer("🚫 Access Denied!", show_alert=True)
        await query.answer()
        return await _do_approve_reject(client, chat_id, entry, approve=False)

    if key == "addadmin":
        if user_id != ADMINS:
            return await query.answer("🚫 Sirf bot owner ke liye.", show_alert=True)
        await query.answer()
        return await _do_add_remove_admin(client, chat_id, entry, add=True)

    if key == "removeadmin":
        if user_id != ADMINS:
            return await query.answer("🚫 Sirf bot owner ke liye.", show_alert=True)
        await query.answer()
        return await _do_add_remove_admin(client, chat_id, entry, add=False)

    if key == "admins":
        if user_id != ADMINS:
            return await query.answer("🚫 Sirf bot owner ke liye.", show_alert=True)
        await query.answer()
        return await _render_admins_list(entry)

    if key == "broadcast":
        if user_id != ADMINS:
            return await query.answer("🚫 Sirf bot owner ke liye.", show_alert=True)
        await query.answer()
        return await _do_broadcast(client, chat_id, entry)

    if key == "clean":
        if user_id != ADMINS:
            return await query.answer("🚫 Sirf bot owner ke liye.", show_alert=True)
        await query.answer()
        return await run_clean(client, entry)

    await query.answer()


# ================= LOGIN (phone + OTP + 2FA -> auto-generates session) ================= #
# /setsession ke liye pehle se generated session string chahiye thi - Login
# seedha phone/OTP/password poochh ke khud session bana deta hai, phir usi
# db.set_session() me save karta hai taaki Add Channel/Accept waghera sab
# pehle jaisa hi kaam karein.

async def _do_login(client, chat_id, user_id, entry):
    name = 'default'

    phone_resp = await _listen_text(
        client, chat_id,
        f"**📞 Apna Telegram phone number bhejo** (country code ke saath, session name: `{name}`).\n\nExample: `+919876543210`",
        entry,
    )
    if not phone_resp:
        return
    if not phone_resp.text:
        return await phone_resp.reply("❌ **Invalid number** — text me phone number bhejo.")

    phone = phone_resp.text.strip()
    temp_client = Client(f"login_{user_id}", api_id=API_ID, api_hash=API_HASH, in_memory=True)
    await temp_client.connect()

    status = await phone_resp.reply("🔄 **OTP bheja ja raha hai…**")
    try:
        sent = await temp_client.send_code(phone)
    except PhoneNumberInvalid:
        await temp_client.disconnect()
        return await status.edit("❌ **Invalid phone number!** Menu se dobara Login try karo.")
    except Exception as e:
        await temp_client.disconnect()
        return await status.edit(f"❌ **Error:** `{e}`")

    await status.edit(
        "📩 **OTP tumhare Telegram app pe bhej diya gaya hai.**\n\n"
        "Code spaces ke saath bhejo (jaise `1 2 3 4 5`), warna Telegram use "
        "auto-delete kar deta hai.\n\nCancel: /cancel"
    )
    try:
        otp_resp = await client.listen(chat_id, timeout=300)
    except asyncio.TimeoutError:
        await temp_client.disconnect()
        return await status.edit("⏰ **Time khatam ho gaya.** Menu se dobara Login try karo.")

    if otp_resp.text and otp_resp.text.strip().lower() == "/cancel":
        await temp_client.disconnect()
        return await otp_resp.reply("❌ Cancelled.")

    otp = (otp_resp.text or "").strip().replace(" ", "")

    try:
        await temp_client.sign_in(phone, sent.phone_code_hash, otp)
    except PhoneCodeInvalid:
        await temp_client.disconnect()
        return await otp_resp.reply("❌ **Wrong OTP!** Menu se dobara Login try karo.")
    except PhoneCodeExpired:
        await temp_client.disconnect()
        return await otp_resp.reply("⏰ **OTP expire ho gaya!** Menu se dobara Login try karo.")
    except SessionPasswordNeeded:
        pass_ask = await otp_resp.reply("🔒 **Two-Step Verification hai.** Apna password bhejo:")
        try:
            pass_resp = await client.listen(chat_id, timeout=300)
        except asyncio.TimeoutError:
            await temp_client.disconnect()
            return await pass_ask.edit("⏰ **Time khatam ho gaya.** Menu se dobara Login try karo.")
        if pass_resp.text and pass_resp.text.strip().lower() == "/cancel":
            await temp_client.disconnect()
            return await pass_resp.reply("❌ Cancelled.")
        try:
            await temp_client.check_password(pass_resp.text.strip())
        except PasswordHashInvalid:
            await temp_client.disconnect()
            return await pass_resp.reply("❌ **Wrong password!** Menu se dobara Login try karo.")
        except Exception as e:
            await temp_client.disconnect()
            return await pass_resp.reply(f"❌ **Error:** `{e}`")
    except Exception as e:
        await temp_client.disconnect()
        return await otp_resp.reply(f"❌ **Error:** `{e}`")

    session_string = await temp_client.export_session_string()
    me = await temp_client.get_me()
    await temp_client.disconnect()

    await db.set_session(user_id, session_string, name)
    await entry.reply(
        f"🎉 **Login Successful!**\n"
        f"👤 Logged in as: {me.mention}\n"
        f"🔑 Session `{name}` saved.\n\n"
        f"Ab tum ⚡ Accept Pending use kar sakte ho, ya ➕ Add Channel se is session "
        f"ke channels save karke auto-accept on kar sakte ho.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="menu:main")]])
    )


# ================= ADD SESSION (paste an already-generated string) ================= #

async def _do_addsession(client, chat_id, user_id, entry):
    name = 'default'
    resp = await _listen_text(
        client, chat_id,
        f"**📤 Apna Pyrogram STRING_SESSION bhejo** (session name: `{name}`).\n\n"
        "⚠️ Yeh sirf tumhare account tak limited rahega, kisi aur ko nahi dikhega.",
        entry,
    )
    if not resp:
        return
    if not resp.text:
        return await resp.reply("❌ **Invalid session** — text me session bhejo.")

    session_string = resp.text.strip()
    checking = await resp.reply("**🔎 Session check ho raha hai…**")
    me, error = await validate_session(session_string)

    if error:
        return await checking.edit(f"**❌ Invalid Session!**\n`{error}`")

    await db.set_session(user_id, session_string, name)
    await checking.edit(
        f"**✅ Session `{name}` Saved Successfully!**\n"
        f"👤 Logged in as: {me.mention}\n\n"
        f"Ab tum ⚡ Accept Pending use kar sakte ho, ya ➕ Add Channel se is session "
        f"ke channels save karke auto-accept on kar sakte ho."
    )


# ================= OWNER SETTINGS PANEL (GLOBAL SESSION) ================= #

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
        [InlineKeyboardButton("🔙 Back", callback_data="menu:admin")],
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


# ================= SESSION REMOVE (button per saved session) ================= #

@Client.on_callback_query(filters.regex(r"^sessrm:(.+)$"))
async def cb_remove_session(client, query):
    user_id = query.from_user.id
    name = query.matches[0].group(1)
    removed = await db.remove_session(user_id, name)
    await query.answer(f"🗑 Session `{name}` removed." if removed else "⚠️ Nahi mila.", show_alert=True)
    sessions = await db.get_all_sessions(user_id)
    if not sessions:
        return await query.message.edit("**❌ Koi session set nahi hai.**")
    rows = [[InlineKeyboardButton(f"🗑 {n}", callback_data=f"sessrm:{n}")] for n in sessions]
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="menu:main")])
    await query.message.edit("**Kaunsa session remove karna hai?**", reply_markup=InlineKeyboardMarkup(rows))


# ================= SAVED CHANNELS (per-user, with per-channel auto-accept) ================= #

async def _do_addchannel_start(client, chat_id, user_id, entry):
    sessions = await db.get_all_sessions(user_id)
    if not sessions:
        return await entry.reply(
            "❌ **Pehle koi session add karo.**\nMenu se 🔑 Login ya 📤 Add Session use karo.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="menu:main")]])
        )
    if len(sessions) == 1:
        return await _ask_channel_for_session(client, chat_id, user_id, entry, next(iter(sessions)))

    rows = [[InlineKeyboardButton(name, callback_data=f"addch_sess:{name}")] for name in sessions]
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="menu:main")])
    await entry.reply("**Kaunsa session use karna hai is channel ke liye?**", reply_markup=InlineKeyboardMarkup(rows))


@Client.on_callback_query(filters.regex(r"^addch_sess:(.+)$"))
async def cb_addchannel_pick_session(client, query):
    session_name = query.matches[0].group(1)
    await query.answer()
    await _ask_channel_for_session(client, query.message.chat.id, query.from_user.id, query.message, session_name)


async def _ask_channel_for_session(client, chat_id, user_id, entry, session_name):
    resp = await _listen_text(
        client, chat_id,
        "**📤 Channel/Group ki ID bhejo ya wahan se koi message forward karo.**",
        entry, timeout=120,
    )
    if not resp:
        return

    ch_id, title = None, None
    if resp.forward_from_chat:
        ch_id = resp.forward_from_chat.id
        title = resp.forward_from_chat.title
    elif resp.text:
        try:
            ch_id = int(resp.text.strip())
        except ValueError:
            return await resp.reply("❌ Invalid ID.")

    if not ch_id:
        return await resp.reply("❌ Invalid Input.")

    if not title:
        try:
            chat = await client.get_chat(ch_id)
            title = chat.title
        except Exception:
            title = str(ch_id)

    await db.add_channel(user_id, ch_id, title=title, session_name=session_name)
    await resp.reply(
        f"✅ **Channel Saved:** {title} (`{ch_id}`)\n"
        f"🔑 Session: `{session_name}`  |  🔁 Auto-Accept: ✅ ON (default)\n\n"
        f"Toggle/remove karne ke liye 📂 My Channels menu use karo.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="menu:main")]])
    )


async def _render_mychannels(entry, user_id):
    channels = await db.get_user_channels(user_id)
    if not channels:
        return await entry.reply(
            "**Koi saved channel nahi hai.**\nAdd karne ke liye ➕ Add Channel use karo.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="menu:main")]])
        )

    text_lines = ["**📂 Your Saved Channels:**\n"]
    rows = []
    for ch in channels:
        state = "✅ ON" if ch.get('auto_accept', True) else "❌ OFF"
        title = ch.get('title') or str(ch['chat_id'])
        text_lines.append(f"• {title} (`{ch['chat_id']}`) — Session: `{ch.get('session_name', 'default')}` | Auto: {state}")
        rows.append([
            InlineKeyboardButton(f"🔁 Toggle {title[:15]}", callback_data=f"chtg:{ch['chat_id']}"),
            InlineKeyboardButton("🗑 Remove", callback_data=f"chrm:{ch['chat_id']}"),
        ])
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="menu:main")])
    await entry.reply("\n".join(text_lines), reply_markup=InlineKeyboardMarkup(rows))


@Client.on_callback_query(filters.regex(r"^chtg:(-?\d+)$"))
async def cb_toggle_channel(client, query):
    user_id = query.from_user.id
    chat_id = int(query.matches[0].group(1))
    new_val = await db.toggle_auto_accept(user_id, chat_id)
    if new_val is None:
        return await query.answer("⚠️ Pehle Add Channel se yeh channel save karo.", show_alert=True)
    await query.answer(f"✅ Auto-Accept ab {'ON' if new_val else 'OFF'} hai.")
    await _render_mychannels(query.message, user_id)


@Client.on_callback_query(filters.regex(r"^chrm:(-?\d+)$"))
async def cb_remove_channel(client, query):
    user_id = query.from_user.id
    chat_id = int(query.matches[0].group(1))
    removed = await db.remove_channel(user_id, chat_id)
    await query.answer("✅ Removed." if removed else "⚠️ Not found.", show_alert=True)
    await _render_mychannels(query.message, user_id)


# ================= STATS (per-channel breakdown) ================= #

async def _do_stats(entry, user_id):
    back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="menu:main")]])

    if user_id == ADMINS:
        total_users = await db.total_users_count()
        all_stats = await db.get_all_stats()
        grand_total = sum(s.get('total', 0) for s in all_stats)
        top = sorted(all_stats, key=lambda s: s.get('total', 0), reverse=True)[:15]
        lines = "\n".join(f"• `{s['chat_id']}` → `{s.get('total', 0)}`" for s in top) or "—"
        return await entry.reply(
            f"**📊 Bot-Wide Stats**\n\n"
            f"👥 Total Bot Users: `{total_users}`\n"
            f"✅ Total Requests Accepted (all channels): `{grand_total}`\n\n"
            f"**Top Channels:**\n{lines}",
            reply_markup=back_btn,
        )

    channels = await db.get_user_channels(user_id)
    if not channels:
        return await entry.reply("**Tumne koi channel save nahi kiya.**\nUse ➕ Add Channel first.", reply_markup=back_btn)

    lines, grand_total = [], 0
    for ch in channels:
        count = await db.get_stats(ch['chat_id'])
        grand_total += count
        state = "✅ ON" if ch.get('auto_accept', True) else "❌ OFF"
        lines.append(f"• {ch.get('title') or ch['chat_id']} (`{ch['chat_id']}`) — Accepted: `{count}` | Auto: {state}")

    await entry.reply(
        "**📊 Your Channel Stats**\n\n" + "\n".join(lines) + f"\n\n**Total Accepted:** `{grand_total}`",
        reply_markup=back_btn,
    )


# ================= MANUAL REVIEW (suspicious join requests) ================= #

async def _do_approve_reject(client, chat_id, entry, approve: bool):
    action = "approve" if approve else "reject"
    resp = await _listen_text(
        client, chat_id,
        f"**Chat ID aur User ID bhejo, space se separate** (jise {'approve' if approve else 'reject'} karna hai).\n\nExample: `-1001234567890 123456789`",
        entry,
    )
    if not resp or not resp.text:
        return
    parts = resp.text.split()
    if len(parts) < 2:
        return await resp.reply("❌ **Usage:** `chat_id user_id`")
    try:
        target_chat_id, target_user_id = int(parts[0]), int(parts[1])
    except ValueError:
        return await resp.reply("❌ Invalid IDs.")

    try:
        if approve:
            await client.approve_chat_join_request(target_chat_id, target_user_id)
            await db.increment_stats(target_chat_id, 1)
            await resp.reply("✅ Approved.")
        else:
            await client.decline_chat_join_request(target_chat_id, target_user_id)
            await resp.reply("🗑 Rejected.")
    except Exception as e:
        await resp.reply(f"❌ Error: `{e}`")


# ================= ADMIN MANAGEMENT (OWNER ONLY) ================= #

async def _do_add_remove_admin(client, chat_id, entry, add: bool):
    resp = await _listen_text(
        client, chat_id,
        f"**User ID bhejo jise {'admin banana' if add else 'admin se hatana'} hai:**",
        entry,
    )
    if not resp or not resp.text:
        return
    try:
        target_id = int(resp.text.strip())
    except ValueError:
        return await resp.reply("❌ **Invalid user ID!**")

    if add:
        added = await db.add_admin(target_id)
        msg = f"✅ **User `{target_id}` ko admin bana diya gaya!**" if added else f"⚠️ **User `{target_id}` pehle se admin hai!**"
    else:
        removed = await db.remove_admin(target_id)
        msg = f"✅ **User `{target_id}` ko admin se hata diya gaya!**" if removed else f"⚠️ **User `{target_id}` admin nahi tha!**"

    await resp.reply(msg)


async def _render_admins_list(entry):
    admins = await db.get_all_admins()
    text = "👑 **Admin List:**\n\n"
    text += f"`1.` `{ADMINS}` — 👑 Owner\n"
    for i, admin_id in enumerate(admins, 2):
        text += f"`{i}.` `{admin_id}`\n"
    await entry.reply(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="menu:manageadmins")]]))


# ================= BROADCAST (OWNER ONLY) ================= #

async def _do_broadcast(client, chat_id, entry):
    resp = await _listen_text(
        client, chat_id,
        "**📢 Jo message broadcast karna hai woh bhejo ya forward karo** (text/photo/video, kuch bhi).",
        entry,
    )
    if not resp:
        return
    await run_broadcast(client, resp, resp)


# ================= APPROVE FUNCTION ================= #

async def _pending_count(acc, chat_id):
    """Gets the TOTAL pending join-request count in a SINGLE API call,
    instead of paging through every request one-by-one like
    get_chat_join_requests() does. Telegram's raw response already
    includes a `count` field for the full match - we just read it with
    limit=1. For a channel with thousands of pending requests this turns
    what used to be dozens of sequential network round-trips into one,
    which is what actually made /accept feel slow before."""
    r = await acc.invoke(
        raw.functions.messages.GetChatInviteImporters(
            peer=await acc.resolve_peer(chat_id),
            requested=True,
            offset_date=0,
            offset_user=raw.types.InputUserEmpty(),
            limit=1,
        )
    )
    return r.count


async def approve_requests(acc, chat_id):
    """Approves ALL pending join requests in one chat - loops until it's
    REALLY zero.

    REAL BUG FOUND: Telegram's own bulk-approve API
    (approve_all_chat_join_requests, raw: hideAllChatJoinRequests) does
    NOT clear a big channel in one shot - it silently approves only one
    internal batch (~100 requests) per call and quietly leaves the rest
    pending. That's exactly why running /accept several times in a row
    showed the count SLOWLY SHRINKING instead of going to 0
    (e.g. 7121 -> 7021 -> 6921) - each run was only clearing one more
    batch, not everything. This was never a counting/math bug - the
    count was accurate the whole time, the approve call itself just
    wasn't finishing the job.

    Fix: keep calling approve_all_chat_join_requests and re-checking the
    real remaining count (via the fast single-call _pending_count) until
    it actually hits 0 (or genuinely stops shrinking / a safety cap is
    hit). One /accept now clears everything in one go, no matter how
    many times you'd have needed to spam it before.
    """
    try:
        before = await _pending_count(acc, chat_id)
    except FloodWait as e:
        await asyncio.sleep(e.value)
        try:
            before = await _pending_count(acc, chat_id)
        except Exception as e:
            return chat_id, 0, str(e)
    except Exception as e:
        return chat_id, 0, str(e)

    if before == 0:
        return chat_id, 0, None

    remaining = before
    rounds = 0
    MAX_ROUNDS = 500  # safety cap - each round clears a batch, so this covers even huge queues

    while remaining > 0 and rounds < MAX_ROUNDS:
        try:
            await acc.approve_all_chat_join_requests(chat_id)
        except FloodWait as e:
            await asyncio.sleep(e.value)
            continue
        except Exception as e:
            approved_so_far = before - remaining
            return chat_id, approved_so_far, (str(e) if approved_so_far == 0 else None)

        rounds += 1

        try:
            new_remaining = await _pending_count(acc, chat_id)
        except FloodWait as e:
            await asyncio.sleep(e.value)
            try:
                new_remaining = await _pending_count(acc, chat_id)
            except Exception:
                break  # can't verify anymore - stop with what we've confirmed so far
        except Exception:
            break

        if new_remaining >= remaining:
            break  # not shrinking anymore - avoid looping forever
        remaining = new_remaining

    return chat_id, before - remaining, None


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


# ================= ACCEPT (ANY USER WITH A SESSION, OR AUTHORIZED ADMIN) ================= #

async def _do_accept(client, chat_id, user_id, entry):
    session_string = await get_session_for(user_id)

    if not session_string:
        return await entry.reply(
            "🚫 **Access Denied!**\n\n"
            "Aapka koi STRING_SESSION set nahi hai.\n"
            "Menu se 🔑 Login ya 📤 Add Session use karo — phir aap apne khud ke "
            "channels/groups ke pending requests accept kar paoge.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="menu:main")]])
        )

    show = await entry.reply("**Please Wait…**")
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
        await show.edit(
            "**Send Channel ID / Multiple IDs\n"
            "Or Forward Message From Channel**"
        )

        vj = await client.listen(chat_id)
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
            return await entry.reply("**❌ Invalid Input**")

        await vj.delete()

        if not chat_ids:
            return await show.edit("**❌ Invalid Input**")

        msg = await show.edit("**⚡ Starting Approval…**")
        await process_all_requests(acc, chat_ids, msg)

    finally:
        if acc and acc.is_connected:
            await acc.disconnect()



# ================= AUTO ACCEPT ON BOT PROMOTED TO ADMIN ================= #
# Restores the old behaviour: jaise hi bot ko kisi channel/group me ADMIN
# banaya jata hai (aur wo pehle admin nahi tha), turant us chat ke saare
# already-pending join requests bhi accept ho jaate hain - bina /accept
# command chalaye. (Naye join requests to on_chat_join_request se already
# live handle hote hain - yeh sirf ADMIN-banate-hi-ke-purane-pending wala
# case cover karta hai.)

@Client.on_chat_member_updated()
async def on_bot_promoted_to_admin(client, update):

    try:
        my_id = client.me.id if client.me else (await client.get_me()).id
        if not update.new_chat_member or update.new_chat_member.user.id != my_id:
            return  # yeh update kisi aur member ka hai, bot ka nahi

        new_status = update.new_chat_member.status
        old_status = update.old_chat_member.status if update.old_chat_member else None

        if new_status != enums.ChatMemberStatus.ADMINISTRATOR:
            return  # admin nahi bana
        if old_status == enums.ChatMemberStatus.ADMINISTRATOR:
            return  # pehle se hi admin tha (rights update hua bas) - skip

        # Agar "invite users" right explicitly OFF hai to hi skip karo -
        # baaki har case (right ON ya pata nahi) me try zaroor karo.
        privileges = update.new_chat_member.privileges
        if privileges and privileges.can_invite_users is False:
            return

        # Telegram ke server par admin rights turant is API call ke liye
        # ready nahi hote (thoda propagation delay hota hai) - isliye
        # chhota sa wait karke, fail hone par ek retry ke saath try karo,
        # bajaye turant hi silently give up karne ke.
        chat_id, count, err = await approve_requests(client, update.chat.id)
        if err:
            await asyncio.sleep(3)
            chat_id, count, err = await approve_requests(client, update.chat.id)

        if err:
            try:
                await client.send_message(
                    LOG_CHANNEL,
                    "⚠️ **Admin Bana Par Auto-Accept Fail Ho Gaya**\n"
                    f"💬 **Chat:** {update.chat.title}\n"
                    f"🆔 **Chat ID:** `{update.chat.id}`\n"
                    f"❌ **Error:** `{err}`"
                )
            except Exception:
                pass
            return

        if not count:
            return

        await db.increment_stats(chat_id, count)

        try:
            await client.send_message(
                chat_id,
                "✅ **Admin Bana Diya Gaya!**\n\n"
                f"🔁 `{count}` pehle se pending join request(s) turant accept kar diye gaye."
            )
        except Exception:
            pass

        try:
            await client.send_message(
                LOG_CHANNEL,
                "📝 **New Bot Activity**\n"
                "📱 **Action:** Bot Promoted To Admin → Auto Accepted Pending Requests\n"
                f"💬 **Chat:** {update.chat.title}\n"
                f"🆔 **Chat ID:** `{update.chat.id}`\n"
                f"✅ **Accepted:** `{count}`"
            )
        except Exception:
            pass

    except Exception as e:
        print(f"AUTO ACCEPT ON PROMOTION ERROR: {e}")


# ================= AUTO APPROVE (instant, per-channel toggle) ================= #

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

        await client.approve_chat_join_request(
            chat_id=m.chat.id,
            user_id=m.from_user.id
        )
        await db.increment_stats(m.chat.id, 1)
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
            await db.increment_stats(m.chat.id, 1)
        except Exception as e:
            print(f"AUTO APPROVE RETRY ERROR: {e}")

    except Exception as e:
        print(f"AUTO APPROVE ERROR: {e}")


# ================= AI SUPPORT CHATBOT (Google Gemini) ================= #
# Private chat me jo bhi normal text aata hai (koi command nahi), uska
# reply Gemini se generate karke diya jata hai - taaki users ko commands
# yaad na rakhne padein, bas apni language me poochh sakte hain.
# GEMINI_API_KEY config/env me set nahi hai to yeh feature silently OFF
# rehta hai, baaki sab bot ka kaam waise hi chalta rehta hai.

GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

AI_SYSTEM_PROMPT = (
    "Tum 'Mrn Officialx Join Request Acceptor Bot' ke helpful support assistant ho, "
    "yeh Telegram bot channel/group ke join requests auto-accept karta hai. "
    "User ke sawalon ka short, friendly, Hinglish me reply do. Yeh bot ab poora "
    "button-menu se chalta hai - koi command yaad rakhne ki zaroorat nahi. User "
    "/start bheje, phir 'Open Menu' button dabaye - wahan se Login, Add Session, "
    "My Sessions, Remove Session, Add Channel, My Channels, Stats, Accept Pending, "
    "aur (admin/owner ke liye) Admin Panel (Approve/Reject User, Manage Admins, "
    "Broadcast, Clean DB, Global Session) - sab kuch buttons se milta hai. Bot ko "
    "channel/group me admin banao 'Invite Users' permission ke saath, tabhi yeh "
    "kaam karega. Jawab crisp rakho, zyada lamba mat likho."
)


async def ask_gemini(prompt: str):
    """Gemini API ko call karta hai. Returns (reply_text, error) - error
    None hone par reply_text use karna hai, warna error message user ko
    dikhane layak nahi hai (bas caller ke liye)."""
    payload = {
        "system_instruction": {"parts": [{"text": AI_SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
    }
    headers = {"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY}

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25)) as session:
            async with session.post(GEMINI_URL, json=payload, headers=headers) as resp:
                data = await resp.json()

                if resp.status != 200:
                    return None, data.get("error", {}).get("message", f"HTTP {resp.status}")

                candidates = data.get("candidates") or []
                if not candidates:
                    return None, "Empty response from Gemini"

                parts = candidates[0].get("content", {}).get("parts", [])
                text = "".join(p.get("text", "") for p in parts).strip()
                return (text, None) if text else (None, "Empty response from Gemini")

    except asyncio.TimeoutError:
        return None, "Timeout"
    except Exception as e:
        return None, str(e)


# In sab command names ki list jo already handlers me define hain - AI
# chatbot sirf tabhi trigger hoga jab text in me se koi command na ho,
# taaki normal command flow (aur unke andar wale client.listen() waits,
# jaise /setsession, /addchannel, /settings) kabhi bhi is se clash na
# karein.
_KNOWN_COMMANDS = ["start", "cancel"]


@Client.on_message(
    filters.private & filters.text & filters.incoming & ~filters.command(_KNOWN_COMMANDS),
    group=5,
)
async def ai_support_chat(client, message):
    if not GEMINI_API_KEY:
        return  # feature off - GEMINI_API_KEY env var set nahi hai

    if not await db.is_user_exist(message.from_user.id):
        await db.add_user(message.from_user.id, message.from_user.first_name)

    try:
        await client.send_chat_action(message.chat.id, enums.ChatAction.TYPING)
    except Exception:
        pass

    reply, error = await ask_gemini(message.text)

    if error:
        return await message.reply("**⚠️ AI abhi reply nahi de paaya.** Thodi der baad try karo.")

    await message.reply(reply)
