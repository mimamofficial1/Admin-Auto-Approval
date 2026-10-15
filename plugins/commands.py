import asyncio
import aiohttp
from pyrogram import Client, filters, enums
from pyrogram.errors import (
    FloodWait, PhoneNumberInvalid, PhoneCodeInvalid, PhoneCodeExpired,
    SessionPasswordNeeded, PasswordHashInvalid, ListenerTimeout,
)
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import (
    LOG_CHANNEL, API_ID, API_HASH, NEW_REQ_MODE, ADMINS, STRING_SESSION,
    GEMINI_API_KEY, GEMINI_MODEL,
)
from plugins.database import db
from plugins.broadcast import run_broadcast, run_clean
from plugins import ui
from plugins.ui import esc, code, mention, note, screen, kv, bullets, quote, btn, ubtn, kb, back_row
from pyrogram import raw

HTML = enums.ParseMode.HTML


async def send(entry, text: str, markup=None):
    return await entry.reply(ui.finish(text), parse_mode=HTML, reply_markup=markup, disable_web_page_preview=True)


async def edit(entry, text: str, markup=None):
    return await entry.edit(ui.finish(text), parse_mode=HTML, reply_markup=markup, disable_web_page_preview=True)


_edit_msg = edit  # alias used where a function's own parameter is named `edit`


def usage(cmd: str, what: str) -> str:
    return screen("ℹ️", "Usage", f"{code(cmd)}\n\n{what}")


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


async def revoke_session(session_string):
    """Logs the account out of this STRING_SESSION on Telegram's side, so a
    copy of it that was ever exposed (leaked DB, old backup, ...) stops
    working the moment the user removes it from the bot. Best-effort: never
    raises, since the string is being deleted either way."""
    if not session_string:
        return
    acc = Client(f"revoke_{session_string[:8]}", api_id=API_ID, api_hash=API_HASH,
                 session_string=session_string, in_memory=True)
    try:
        await acc.connect()
        await acc.log_out()
    except Exception as e:
        print(f"REVOKE SESSION ERROR (non-fatal): {e}")
        try:
            await acc.disconnect()
        except Exception:
            pass


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
        lines = [kv("User", mention(user)), kv("ID", code(user.id))]

        if action_type == "start":
            icon, title = "🚀", "Bot started"
        elif action_type == "approve":
            icon, title = "✅", "Admin approved pending requests"
        elif action_type == "auto":
            icon, title = "🔁", "Auto-approved a join request"
            lines += [kv("Chat", esc(message.chat.title)), kv("Chat ID", code(message.chat.id))]
        else:
            icon, title = "📝", "Bot activity"

        if extra_info:
            lines.append(kv("Info", extra_info))

        log_text = ui.finish(screen(icon, title, quote("\n".join(lines))))
        try:
            await client.send_message(LOG_CHANNEL, log_text, parse_mode=HTML)
        except FloodWait as e:
            await asyncio.sleep(e.value)
            await client.send_message(LOG_CHANNEL, log_text, parse_mode=HTML)

    except Exception as e:
        print(f"LOG ERROR: {e}")


# ================= START ================= #

@Client.on_message(filters.command("start"))
async def start_message(c, m):

    if not await db.is_user_exist(m.from_user.id):
        await db.add_user(m.from_user.id, m.from_user.first_name)
        await send_log(c, m, "start")

    bot_username = (await c.get_me()).username

    await m.reply_photo(
        "https://graph.org/file/74f3b07e680826de251ee-11c68075c29d2227d5.jpg",
        caption=ui.start_text(m.from_user),
        parse_mode=HTML,
        reply_markup=ui.start_buttons(bot_username),
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

def menu_text() -> str:
    return screen("🛠", "Menu", "Choose an option below.")


def main_menu_markup(user_id) -> InlineKeyboardMarkup:
    rows = [
        [btn("🔑 Login", "menu:login"), btn("📤 Add Session", "menu:addsession")],
        [btn("📋 My Sessions", "menu:mysessions"), btn("🗑 Remove Session", "menu:removesession")],
        [btn("➕ Add Channel", "menu:addchannel"), btn("📂 My Channels", "menu:mychannels")],
        [btn("📊 Stats", "menu:stats"), btn("⚡ Accept Pending", "menu:accept")],
        [btn("👑 Admin Panel", "menu:admin")],
        [btn("❌ Close", "menu:close")],
    ]
    return kb(*rows)


def admin_menu_markup() -> InlineKeyboardMarkup:
    return kb(
        [btn("✅ Approve User", "menu:approveuser"), btn("❌ Reject User", "menu:rejectuser")],
        [btn("👑 Manage Admins", "menu:manageadmins")],
        [btn("📢 Broadcast", "menu:broadcast"), btn("🧹 Clean DB", "menu:clean")],
        [btn("🌐 Global Session", "menu:globalsession")],
        back_row("menu:main"),
    )


def manage_admins_markup() -> InlineKeyboardMarkup:
    return kb(
        [btn("➕ Add Admin", "menu:addadmin"), btn("🗑 Remove Admin", "menu:removeadmin")],
        [btn("📋 Admins List", "menu:admins")],
        back_row("menu:admin"),
    )


async def _listen_text(client, chat_id, prompt, entry, timeout=300):
    """Common helper: ask a question, wait for the next text reply. Returns
    the response Message, or None (and already replies to the user) if it
    timed out / was cancelled / wasn't text."""
    ask = await send(entry, screen("✏️", "Input needed", prompt, hint="Cancel anytime with /cancel."))
    try:
        resp = await client.listen(chat_id, timeout=timeout)
    except (asyncio.TimeoutError, ListenerTimeout):
        await edit(ask, note("warn", "Timed out", "Open the menu and try again."))
        return None
    if resp.text and resp.text.strip().lower() == "/cancel":
        await send(resp, note("ok", "Cancelled"))
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
        return await edit(entry, menu_text(), main_menu_markup(user_id))

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
            return await query.answer("🚫 Admins/owner only.", show_alert=True)
        await query.answer()
        return await edit(entry, screen("👑", "Admin Panel", "Manage admins, broadcast and the global session."), admin_menu_markup())

    if key == "manageadmins":
        if user_id != ADMINS:
            return await query.answer("🚫 Owner only.", show_alert=True)
        await query.answer()
        return await edit(entry, screen("👑", "Manage Admins"), manage_admins_markup())

    if key == "globalsession":
        if user_id != ADMINS:
            return await query.answer("🚫 Owner only.", show_alert=True)
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
            text = note("info", "No session set", "Add one with 🔑 Login or 📤 Add Session.")
        else:
            text = screen("📋", "Your Sessions", bullets(code(n) for n in sessions))
        return await send(entry, text)

    if key == "removesession":
        await query.answer()
        sessions = await db.get_all_sessions(user_id)
        if not sessions:
            return await send(entry, note("info", "No session set"))
        rows = [[btn(f"🗑 {name}", f"sessrm:{name}", raw=True)] for name in sessions]
        rows.append(back_row("menu:main"))
        return await send(entry, screen("🗑", "Remove Session", "Which one should be removed?"), kb(*rows))

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
            return await query.answer("🚫 Access denied.", show_alert=True)
        await query.answer()
        return await _do_approve_reject(client, chat_id, entry, approve=True)

    if key == "rejectuser":
        if not await is_authorized(user_id):
            return await query.answer("🚫 Access denied.", show_alert=True)
        await query.answer()
        return await _do_approve_reject(client, chat_id, entry, approve=False)

    if key == "addadmin":
        if user_id != ADMINS:
            return await query.answer("🚫 Owner only.", show_alert=True)
        await query.answer()
        return await _do_add_remove_admin(client, chat_id, entry, add=True)

    if key == "removeadmin":
        if user_id != ADMINS:
            return await query.answer("🚫 Owner only.", show_alert=True)
        await query.answer()
        return await _do_add_remove_admin(client, chat_id, entry, add=False)

    if key == "admins":
        if user_id != ADMINS:
            return await query.answer("🚫 Owner only.", show_alert=True)
        await query.answer()
        return await _render_admins_list(entry)

    if key == "broadcast":
        if user_id != ADMINS:
            return await query.answer("🚫 Owner only.", show_alert=True)
        await query.answer()
        return await _do_broadcast(client, chat_id, entry)

    if key == "clean":
        if user_id != ADMINS:
            return await query.answer("🚫 Owner only.", show_alert=True)
        await query.answer()
        return await run_clean(client, entry)

    await query.answer()


# ================= LOGIN (phone + OTP + 2FA -> auto-generates session) ================= #
# /setsession ke liye pehle se generated session string chahiye thi - Login
# seedha phone/OTP/password poochh ke khud session bana deta hai, phir usi
# db.set_session() me save karta hai (encrypted - see plugins/crypto.py)
# taaki Add Channel/Accept waghera sab pehle jaisa hi kaam karein.

async def _do_login(client, chat_id, user_id, entry):
    name = 'default'

    phone_resp = await _listen_text(
        client, chat_id,
        f"Send your Telegram phone number with the country code.\n(session name: {code(name)})\n\n"
        f"<b>Example</b>\n{code('+919876543210')}",
        entry,
    )
    if not phone_resp:
        return
    if not phone_resp.text:
        return await send(phone_resp, note("err", "Invalid number", "Send it as text."))

    phone = phone_resp.text.strip()
    temp_client = Client(f"login_{user_id}", api_id=API_ID, api_hash=API_HASH, in_memory=True)
    await temp_client.connect()

    status = await send(phone_resp, note("wait", "Sending the code…"))
    try:
        sent = await temp_client.send_code(phone)
    except PhoneNumberInvalid:
        await temp_client.disconnect()
        return await edit(status, note("err", "Invalid phone number", "Open the menu and try Login again."))
    except Exception as e:
        await temp_client.disconnect()
        return await edit(status, note("err", "Something went wrong", code(e)))

    await edit(status, screen(
        "📩", "Code sent",
        "Open Telegram and send the code with spaces between the digits "
        f"(e.g. {code('1 2 3 4 5')}) — otherwise Telegram auto-deletes it.",
        hint="Cancel anytime with /cancel.",
    ))
    try:
        otp_resp = await client.listen(chat_id, timeout=300)
    except (asyncio.TimeoutError, ListenerTimeout):
        await temp_client.disconnect()
        return await edit(status, note("warn", "Timed out", "Open the menu and try Login again."))

    if otp_resp.text and otp_resp.text.strip().lower() == "/cancel":
        await temp_client.disconnect()
        return await send(otp_resp, note("ok", "Cancelled"))

    otp = (otp_resp.text or "").strip().replace(" ", "")

    try:
        await temp_client.sign_in(phone, sent.phone_code_hash, otp)
    except PhoneCodeInvalid:
        await temp_client.disconnect()
        return await send(otp_resp, note("err", "Wrong code", "Open the menu and try Login again."))
    except PhoneCodeExpired:
        await temp_client.disconnect()
        return await send(otp_resp, note("err", "Code expired", "Open the menu and try Login again."))
    except SessionPasswordNeeded:
        pass_ask = await send(otp_resp, screen("🔒", "Two-step verification", "Send your password."))
        try:
            pass_resp = await client.listen(chat_id, timeout=300)
        except (asyncio.TimeoutError, ListenerTimeout):
            await temp_client.disconnect()
            return await edit(pass_ask, note("warn", "Timed out", "Open the menu and try Login again."))
        if pass_resp.text and pass_resp.text.strip().lower() == "/cancel":
            await temp_client.disconnect()
            return await send(pass_resp, note("ok", "Cancelled"))
        try:
            await temp_client.check_password(pass_resp.text.strip())
        except PasswordHashInvalid:
            await temp_client.disconnect()
            return await send(pass_resp, note("err", "Wrong password", "Open the menu and try Login again."))
        except Exception as e:
            await temp_client.disconnect()
            return await send(pass_resp, note("err", "Something went wrong", code(e)))
    except Exception as e:
        await temp_client.disconnect()
        return await send(otp_resp, note("err", "Something went wrong", code(e)))

    session_string = await temp_client.export_session_string()
    me = await temp_client.get_me()
    await temp_client.disconnect()

    await db.set_session(user_id, session_string, name)
    await send(
        entry,
        screen("🎉", "Login successful",
              quote(kv("Account", mention(me)) + "\n" + kv("Session", code(name))),
              hint="Use ⚡ Accept Pending now, or ➕ Add Channel to save this session's channels for auto-accept."),
        kb(back_row("menu:main"))
    )


# ================= ADD SESSION (paste an already-generated string) ================= #

async def _do_addsession(client, chat_id, user_id, entry):
    name = 'default'
    resp = await _listen_text(
        client, chat_id,
        f"Send your Pyrogram STRING_SESSION.\n(session name: {code(name)})\n\n"
        + quote("🔒 It is encrypted before being stored and is only used for your own account."),
        entry,
    )
    if not resp:
        return
    if not resp.text:
        return await send(resp, note("err", "Invalid session", "Send it as text."))

    session_string = resp.text.strip()
    checking = await send(resp, note("wait", "Checking the session…"))
    me, error = await validate_session(session_string)

    if error:
        return await edit(checking, note("err", "Invalid session", code(error)))

    await db.set_session(user_id, session_string, name)
    await edit(checking, screen(
        "✅", f"Session {name} saved",
        quote(kv("Account", mention(me))),
        hint="Use ⚡ Accept Pending now, or ➕ Add Channel to save this session's channels for auto-accept.",
    ))


# ================= OWNER SETTINGS PANEL (GLOBAL SESSION) ================= #

async def render_settings(message_or_query, edit=False):
    has_global = bool(await db.get_global_session())
    text = screen(
        "⚙️", "Bot Settings",
        quote(kv("Global STRING_SESSION", "✅ Set" if has_global else "❌ Not set")),
        "Used as the default session for admins who have no personal session set.",
    )
    buttons = kb(
        [btn("🔑 Set / Update Global Session", "stg_set")],
        [btn("🗑 Remove Global Session", "stg_rm")],
        back_row("menu:admin"),
    )

    if edit:
        await _edit_msg(message_or_query, text, buttons)
    else:
        await send(message_or_query, text, buttons)


@Client.on_callback_query(filters.regex(r"^stg_"))
async def settings_callback(client, query):
    if query.from_user.id != ADMINS:
        return await query.answer("🚫 Owner only.", show_alert=True)

    data = query.data

    if data == "stg_set":
        await query.answer()
        ask = await send(query.message, screen("📤", "Global session", "Send the new STRING_SESSION.", hint="Cancel with /cancel."))
        try:
            resp = await client.listen(query.message.chat.id, timeout=300)
        except (asyncio.TimeoutError, ListenerTimeout):
            return await edit(ask, note("warn", "Timed out"))

        if resp.text and resp.text.strip().lower() == "/cancel":
            return await send(resp, note("ok", "Cancelled"))
        if not resp.text:
            return await send(resp, note("err", "Invalid session"))

        checking = await send(resp, note("wait", "Checking the session…"))
        me, error = await validate_session(resp.text.strip())
        if error:
            return await edit(checking, note("err", "Invalid session", code(error)))

        await db.set_global_session(resp.text.strip())
        await edit(checking, note("ok", "Global session set", kv("Account", mention(me))))
        await render_settings(query.message)

    elif data == "stg_rm":
        session_string = await db.get_global_session()
        removed = await db.remove_global_session()
        if removed and session_string:
            await revoke_session(session_string)  # kills any leaked copy of this string too
        await query.answer("Removed and logged out!" if removed else "Nothing was set.", show_alert=True)
        await render_settings(query.message, edit=True)


# ================= SESSION REMOVE (button per saved session) ================= #

@Client.on_callback_query(filters.regex(r"^sessrm:(.+)$"))
async def cb_remove_session(client, query):
    user_id = query.from_user.id
    name = query.matches[0].group(1)
    session_string = await db.get_session(user_id, name)
    removed = await db.remove_session(user_id, name)
    if removed and session_string:
        await revoke_session(session_string)  # kills any leaked copy of this string too
    await query.answer(f"🗑 Session '{name}' removed and logged out." if removed else "⚠️ Not found.", show_alert=True)
    sessions = await db.get_all_sessions(user_id)
    if not sessions:
        return await edit(query.message, note("info", "No session set"))
    rows = [[btn(f"🗑 {n}", f"sessrm:{n}", raw=True)] for n in sessions]
    rows.append(back_row("menu:main"))
    await edit(query.message, screen("🗑", "Remove Session", "Which one should be removed?"), kb(*rows))


# ================= SAVED CHANNELS (per-user, with per-channel auto-accept) ================= #

async def _do_addchannel_start(client, chat_id, user_id, entry):
    sessions = await db.get_all_sessions(user_id)
    if not sessions:
        return await send(
            entry, note("err", "Add a session first", "Use 🔑 Login or 📤 Add Session from the menu."),
            kb(back_row("menu:main")),
        )
    if len(sessions) == 1:
        return await _ask_channel_for_session(client, chat_id, user_id, entry, next(iter(sessions)))

    rows = [[btn(name, f"addch_sess:{name}", raw=True)] for name in sessions]
    rows.append(back_row("menu:main"))
    await send(entry, screen("🔑", "Choose a session", "Which session should manage this channel?"), kb(*rows))


@Client.on_callback_query(filters.regex(r"^addch_sess:(.+)$"))
async def cb_addchannel_pick_session(client, query):
    session_name = query.matches[0].group(1)
    await query.answer()
    await _ask_channel_for_session(client, query.message.chat.id, query.from_user.id, query.message, session_name)


async def _ask_channel_for_session(client, chat_id, user_id, entry, session_name):
    resp = await _listen_text(
        client, chat_id,
        "Send the channel/group ID, or forward a message from it.",
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
            return await send(resp, note("err", "Invalid ID"))
    else:
        return await send(resp, note("err", "Invalid input"))

    if not ch_id:
        return await send(resp, note("err", "Invalid input"))

    if not title:
        try:
            chat = await client.get_chat(ch_id)
            title = chat.title
        except Exception:
            title = str(ch_id)

    await db.add_channel(user_id, ch_id, title=title, session_name=session_name)
    await send(
        resp,
        screen("✅", "Channel saved",
              quote(kv("Channel", esc(title)) + "\n" + kv("ID", code(ch_id)) + "\n"
                    + kv("Session", code(session_name)) + "\n" + kv("Auto-accept", "🟢 On (default)")),
              hint="Toggle or remove it from 📂 My Channels."),
        kb(back_row("menu:main")),
    )


async def _render_mychannels(entry, user_id):
    channels = await db.get_user_channels(user_id)
    if not channels:
        return await send(
            entry, note("info", "No saved channels", "Add one with ➕ Add Channel."),
            kb(back_row("menu:main")),
        )

    lines, rows = [], []
    for ch in channels:
        title = ch.get('title') or str(ch['chat_id'])
        lines.append(f"• {esc(title)} {code(ch['chat_id'])} — {code(ch.get('session_name', 'default'))} — "
                     f"{ui.state(ch.get('auto_accept', True), 'On', 'Off')}")
        rows.append([
            btn(f"🔁 {trim_title(title)}", f"chtg:{ch['chat_id']}", raw=True),
            btn("🗑 Remove", f"chrm:{ch['chat_id']}"),
        ])
    rows.append(back_row("menu:main"))
    await send(entry, screen("📂", "Your Saved Channels", "\n".join(lines)), kb(*rows))


def trim_title(title: str) -> str:
    return ui.trim(title, 15)


@Client.on_callback_query(filters.regex(r"^chtg:(-?\d+)$"))
async def cb_toggle_channel(client, query):
    user_id = query.from_user.id
    chat_id = int(query.matches[0].group(1))
    new_val = await db.toggle_auto_accept(user_id, chat_id)
    if new_val is None:
        return await query.answer("⚠️ Add this channel first.", show_alert=True)
    await query.answer(f"✅ Auto-accept is now {'ON' if new_val else 'OFF'}.")
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
    back = kb(back_row("menu:main"))

    if user_id == ADMINS:
        total_users = await db.total_users_count()
        all_stats = await db.get_all_stats()
        grand_total = sum(s.get('total', 0) for s in all_stats)
        top = sorted(all_stats, key=lambda s: s.get('total', 0), reverse=True)[:15]
        lines = bullets(f"{code(s['chat_id'])} → {code(s.get('total', 0))}" for s in top) or "—"
        return await send(
            entry,
            screen("📊", "Bot-Wide Stats",
                  quote(kv("Total bot users", code(total_users)) + "\n"
                        + kv("Total accepted (all channels)", code(grand_total))),
                  "<b>Top channels</b>\n" + lines),
            back,
        )

    channels = await db.get_user_channels(user_id)
    if not channels:
        return await send(entry, note("info", "No saved channels", "Add one with ➕ Add Channel first."), back)

    lines, grand_total = [], 0
    for ch in channels:
        count = await db.get_stats(ch['chat_id'])
        grand_total += count
        lines.append(f"• {esc(ch.get('title') or ch['chat_id'])} {code(ch['chat_id'])} — accepted "
                     f"{code(count)} — {ui.state(ch.get('auto_accept', True), 'On', 'Off')}")

    await send(entry, screen("📊", "Your Channel Stats", "\n".join(lines),
                             hint=f"Total accepted: {grand_total}"), back)


# ================= MANUAL REVIEW (suspicious join requests) ================= #

async def _do_approve_reject(client, chat_id, entry, approve: bool):
    resp = await _listen_text(
        client, chat_id,
        f"Send the chat ID and user ID, separated by a space, to {'approve' if approve else 'reject'}.\n\n"
        f"<b>Example</b>\n{code('-1001234567890 123456789')}",
        entry,
    )
    if not resp or not resp.text:
        return
    parts = resp.text.split()
    if len(parts) < 2:
        return await send(resp, usage("chat_id user_id", "Both IDs are required."))
    try:
        target_chat_id, target_user_id = int(parts[0]), int(parts[1])
    except ValueError:
        return await send(resp, note("err", "Invalid IDs"))

    try:
        if approve:
            await client.approve_chat_join_request(target_chat_id, target_user_id)
            await db.increment_stats(target_chat_id, 1)
            await send(resp, note("ok", "Approved"))
        else:
            await client.decline_chat_join_request(target_chat_id, target_user_id)
            await send(resp, note("ok", "Rejected"))
    except Exception as e:
        await send(resp, note("err", "Something went wrong", code(e)))


# ================= ADMIN MANAGEMENT (OWNER ONLY) ================= #

async def _do_add_remove_admin(client, chat_id, entry, add: bool):
    resp = await _listen_text(
        client, chat_id,
        f"Send the user ID to {'make an admin' if add else 'remove from admins'}.",
        entry,
    )
    if not resp or not resp.text:
        return
    try:
        target_id = int(resp.text.strip())
    except ValueError:
        return await send(resp, note("err", "Invalid user ID"))

    if add:
        added = await db.add_admin(target_id)
        msg = note("ok", "Admin added", code(target_id)) if added else note("warn", "Already an admin", code(target_id))
    else:
        removed = await db.remove_admin(target_id)
        msg = note("ok", "Admin removed", code(target_id)) if removed else note("warn", "Not an admin", code(target_id))

    await send(resp, msg)


async def _render_admins_list(entry):
    admins = await db.get_all_admins()
    lines = [f"1. {code(ADMINS)} — 👑 Owner"]
    for i, admin_id in enumerate(admins, 2):
        lines.append(f"{i}. {code(admin_id)}")
    await send(entry, screen("👑", "Admin List", "\n".join(lines)), kb(back_row("menu:manageadmins")))


# ================= BROADCAST (OWNER ONLY) ================= #

async def _do_broadcast(client, chat_id, entry):
    resp = await _listen_text(
        client, chat_id,
        "Send or forward the message to broadcast — text, photo, video, anything.",
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
        f"• {code(cid)} → " + (f"✅ {count}" if err is None else f"❌ {esc(err)}")
        for cid, (count, err) in results.items()
    )
    grand_total = sum(count for count, _err in results.values())
    text = screen("⚡", "Processing…", lines, hint=f"{done}/{expected} channels done · {grand_total} accepted so far")
    return text, grand_total


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
                await edit(msg, text)
            except Exception:
                pass

    await asyncio.gather(*[worker(cid) for cid in chat_ids])

    lines = "\n".join(
        f"• {code(cid)} → " + (f"✅ {count}" if err is None else f"❌ {esc(err)}")
        for cid, (count, err) in results.items()
    )
    grand_total = sum(count for count, _err in results.values())
    await edit(msg, screen("✅", "All channels processed", lines, hint=f"Total accepted: {grand_total}"))


# ================= ACCEPT (ANY USER WITH A SESSION, OR AUTHORIZED ADMIN) ================= #

async def _do_accept(client, chat_id, user_id, entry):
    session_string = await get_session_for(user_id)

    if not session_string:
        return await send(
            entry,
            note("stop", "Access denied",
                "No session is set for your account.\nUse 🔑 Login or 📤 Add Session from the menu — "
                "then you'll be able to accept requests for your own channels/groups."),
            kb(back_row("menu:main")),
        )

    show = await send(entry, note("wait", "Please wait…"))
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
        return await edit(show, note("err", "Session error", code(e)))

    try:
        await edit(show, screen("📥", "Send the channel", "Send one or more channel IDs, or forward a message from the channel."))

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
            return await send(entry, note("err", "Invalid input"))

        await vj.delete()

        if not chat_ids:
            return await edit(show, note("err", "Invalid input"))

        msg = await edit(show, note("wait", "Starting approval…"))
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
                    ui.finish(screen(
                        "⚠️", "Promoted to admin, but auto-accept failed",
                        quote(kv("Chat", esc(update.chat.title)) + "\n" + kv("Chat ID", code(update.chat.id))
                              + "\n" + kv("Error", code(err))))),
                    parse_mode=HTML,
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
                ui.finish(note("ok", "I'm now an admin here",
                              f"{code(count)} already-pending join request(s) were approved instantly.")),
                parse_mode=HTML,
            )
        except Exception:
            pass

        try:
            await client.send_message(
                LOG_CHANNEL,
                ui.finish(screen(
                    "📝", "Promoted to admin — pending requests cleared",
                    quote(kv("Chat", esc(update.chat.title)) + "\n" + kv("Chat ID", code(update.chat.id))
                          + "\n" + kv("Accepted", code(count))))),
                parse_mode=HTML,
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
                text=ui.finish(screen("👋", f"Welcome to {esc(m.chat.title)}!",
                                      quote(f"Hello {mention(m.from_user)}, your join request was approved."),
                                      hint=f"Powered by {esc('@Mrn_Officialx')}")),
                parse_mode=HTML
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
    f"Tum '{ui.BRAND}' ke helpful support assistant ho, yeh Telegram bot channel/group "
    "ke join requests auto-accept karta hai. User ke sawalon ka short, friendly, Hinglish "
    "me reply do. Yeh bot poora button-menu se chalta hai - koi command yaad rakhne ki "
    "zaroorat nahi. User /start bheje, phir 'Open Menu' button dabaye - wahan se Login, "
    "Add Session, My Sessions, Remove Session, Add Channel, My Channels, Stats, Accept "
    "Pending, aur (admin/owner ke liye) Admin Panel - sab kuch buttons se milta hai. Bot "
    "ko channel/group me admin banao 'Invite Users' permission ke saath, tabhi yeh kaam "
    "karega. Jawab crisp rakho, zyada lamba mat likho."
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
        return await send(message, note("warn", "AI could not reply right now", "Try again in a moment."))

    await message.reply(reply)
