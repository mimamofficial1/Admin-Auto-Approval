import asyncio
import logging

from pyrogram import Client
from pyrogram.errors import FloodWait

from config import API_ID, API_HASH, ADMINS
from plugins.database import db
from plugins.commands import approve_requests, validate_session

logger = logging.getLogger(__name__)

AUTO_ACCEPT_INTERVAL = 5 * 60         # scan saved channels every 5 minutes
SESSION_CHECK_INTERVAL = 6 * 60 * 60  # verify every saved session every 6 hours


async def auto_accept_loop(bot):
    """Background job for channels managed by a USER SESSION rather than
    the bot itself being admin there. Covers 2 cases the live
    chat_join_request event can't:
      1. Requests that piled up while the bot process was offline.
      2. Channels where only someone's userbot account is admin, so the
         bot's own client never even receives the join-request update.
    """
    await asyncio.sleep(15)  # let the bot finish starting up first
    while True:
        try:
            channels = await db.get_all_auto_accept_channels()
            for ch in channels:
                session_string = await db.get_session(ch['user_id'], ch.get('session_name', 'default'))
                if not session_string:
                    continue

                acc = None
                try:
                    acc = Client(
                        f"sched_{ch['chat_id']}",
                        api_id=API_ID,
                        api_hash=API_HASH,
                        session_string=session_string,
                        in_memory=True
                    )
                    await acc.connect()
                    _cid, count, err = await approve_requests(acc, ch['chat_id'])

                    if err is None and count:
                        await db.increment_stats(ch['chat_id'], count)
                        try:
                            await bot.send_message(
                                ch['user_id'],
                                "🔁 **Auto-Accept:** "
                                f"`{count}` pending request(s) accepted in "
                                f"**{ch.get('title') or ch['chat_id']}**."
                            )
                        except Exception:
                            pass

                except FloodWait as e:
                    await asyncio.sleep(e.value)
                except Exception as e:
                    logger.warning(f"auto_accept_loop error for {ch['chat_id']}: {e}")
                finally:
                    if acc and acc.is_connected:
                        await acc.disconnect()

        except Exception as e:
            logger.warning(f"auto_accept_loop top-level error: {e}")

        await asyncio.sleep(AUTO_ACCEPT_INTERVAL)


async def session_health_loop(bot):
    """Periodically re-validates every saved session (personal + global).
    If one has expired/logged-out, pings the owner (for the global
    session) or the user themself (for a personal one) so it can be
    replaced before it silently breaks auto-accept."""
    await asyncio.sleep(30)
    while True:
        try:
            async for doc in db.session_col.find({}):
                user_id = doc['id']
                sessions = doc.get('sessions') or ({'default': doc['session']} if 'session' in doc else {})
                for name, session_string in sessions.items():
                    _me, error = await validate_session(session_string)
                    if error:
                        try:
                            await bot.send_message(
                                user_id,
                                "⚠️ **Session Expired!**\n\n"
                                f"Tumhara session `{name}` ab kaam nahi kar raha:\n`{error}`\n\n"
                                f"Naya session add karo: `/setsession {name}`"
                            )
                        except Exception:
                            pass

            global_session = await db.get_global_session()
            if global_session:
                _me, error = await validate_session(global_session)
                if error:
                    try:
                        await bot.send_message(
                            ADMINS,
                            f"⚠️ **Global Session Expired!**\n`{error}`\n\n"
                            "`/settings` se naya global session set karo."
                        )
                    except Exception:
                        pass

        except Exception as e:
            logger.warning(f"session_health_loop error: {e}")

        await asyncio.sleep(SESSION_CHECK_INTERVAL)
