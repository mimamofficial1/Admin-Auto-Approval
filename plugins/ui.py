"""
plugins/ui.py
─────────────
One shared design system for every message the bot sends: typography
helpers, button style, and the static pages (start, about). Handlers only
assemble these pieces, so the bot always speaks with one voice.

Style
  • Every screen: icon + title, a divider, then content — all bold.
  • Buttons: ꜱᴍᴀʟʟ ᴄᴀᴘꜱ with one emoji each.
  • User-supplied text is always HTML-escaped — it can never break a message
    or inject fake formatting.
"""
import html
import re

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

BRAND = "Prime Approve"
DIV = "━━━━━━━━━━━━━━━━━━━━"

LINK_CHANNEL = "https://t.me/Mrn_Officialx"
LINK_DEV = "https://t.me/mimam_officialx"
LINK_UPDATE = "https://t.me/+u6qe756hjylkNmE1"

_ICONS = {"ok": "✅", "warn": "⚠️", "err": "❌", "info": "ℹ️", "stop": "🚫", "lock": "🔒", "wait": "⏳"}


# ═══════════════════════════ text primitives ═══════════════════════════

def esc(value) -> str:
    """Escape anything that came from a user, a chat title or an exception."""
    return html.escape(str(value), quote=False)


def code(value) -> str:
    return f"<code>{esc(value)}</code>"


def mention(user) -> str:
    """Safe clickable mention built from raw user data (never trusts Pyrogram's own .mention)."""
    name = esc(getattr(user, "first_name", None) or "there")
    return f'<a href="tg://user?id={user.id}">{name}</a>'


def head(icon: str, title: str) -> str:
    return f"{icon} <b>{esc(title)}</b>\n{DIV}"


def screen(icon: str, title: str, *blocks: str, hint: str = None) -> str:
    parts = [head(icon, title)] + [b for b in blocks if b]
    if hint:
        parts.append(f"<i>{esc(hint)}</i>")
    return "\n\n".join(parts)


def note(kind: str, title: str, detail: str = None) -> str:
    out = f"{_ICONS[kind]} <b>{esc(title)}</b>"
    if detail:
        out += f"\n{detail}"
    return out


def kv(label: str, value) -> str:
    return f"<b>{esc(label)}</b> · {value}"


def bullets(items) -> str:
    return "\n".join(f"• {i}" for i in items)


def quote(text: str) -> str:
    return f"<blockquote>{text}</blockquote>"


def state(on: bool, yes: str = "On", no: str = "Off") -> str:
    return f"🟢 {yes}" if on else f"🔴 {no}"


def trim(text, n: int = 40) -> str:
    text = str(text)
    return text if len(text) <= n else text[: n - 1] + "…"


# ═══════════════════════════ typography ═══════════════════════════
# Buttons use small caps (a–z only; emoji/digits/symbols untouched).
# Every outgoing message is bolded end-to-end with finish(); <code> values
# keep their monospace look since <b><code> still renders as code.

_SMALLCAPS = str.maketrans(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ",
)


def sc(text: str) -> str:
    return text.translate(_SMALLCAPS)


_BQ = re.compile(r"(<blockquote>.*?</blockquote>)", re.S)
_B_TAGS = re.compile(r"</?b>")


def _bold_segment(seg: str) -> str:
    seg = _B_TAGS.sub("", seg)
    m = re.match(r"^(\s*)(.*?)(\s*)$", seg, re.S)
    lead, core, tail = m.group(1), m.group(2), m.group(3)
    return f"{lead}<b>{core}</b>{tail}" if core else seg


def finish(text: str) -> str:
    """Bold the whole message (block quotes bolded inside); call this last, right before sending."""
    out = []
    for part in _BQ.split(text):
        if part.startswith("<blockquote>"):
            out.append("<blockquote>" + _bold_segment(part[len("<blockquote>"):-len("</blockquote>")]) + "</blockquote>")
        else:
            out.append(_bold_segment(part))
    return "".join(out)


# ═══════════════════════════ buttons ═══════════════════════════

def btn(label: str, data: str, raw: bool = False) -> InlineKeyboardButton:
    """raw=True keeps the label untouched — use it for chat/user names."""
    return InlineKeyboardButton(label if raw else sc(label), callback_data=data)


def ubtn(label: str, url: str, raw: bool = False) -> InlineKeyboardButton:
    return InlineKeyboardButton(label if raw else sc(label), url=url)


def kb(*rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([list(r) for r in rows if r])


def back_row(data: str = "menu:main") -> list:
    return [btn("🔙 Back", data)]


# ═══════════════════════════ start screen ═══════════════════════════

def start_text(user) -> str:
    return finish(
        f"✨ <b>Welcome, {mention(user)}</b>\n"
        f"<i>{BRAND} — Join Request Bot</i>\n"
        f"{DIV}\n\n"
        "Accepts channel and group join requests instantly, or clears a "
        "huge pending queue in one go.\n\n"
        "<b>Get started</b>\n"
        "<b>1.</b> Add me to your channel or group\n"
        "<b>2.</b> Make me admin with <b>Invite Users</b> permission\n"
        "<b>3.</b> Open the menu below — everything runs from buttons\n\n"
        + quote("Your account stays yours: session strings are "
                "encrypted and only used to accept requests.")
    )


def start_buttons(bot_username: str) -> InlineKeyboardMarkup:
    return kb(
        [btn("🛠 Open Menu", "menu:main")],
        [ubtn("➕ Add to Channel", f"https://t.me/{bot_username}?startchannel=true"),
         ubtn("➕ Add to Group", f"https://t.me/{bot_username}?startgroup=true")],
        [ubtn("📢 Updates", LINK_CHANNEL)],
        [ubtn("👤 Developer", LINK_DEV), ubtn("🌷 News", LINK_UPDATE)],
    )
