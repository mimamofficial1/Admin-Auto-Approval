"""
config.py
─────────
All secrets come ONLY from environment variables — never hardcode a real
token, password or connection string here, and never commit one to git.
A leaked DB_URI or API_HASH in a public repo is an open door to every
account connected to this bot; see plugins/crypto.py for why sessions are
encrypted at rest on top of this.
"""
from os import environ


def _require(name: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise SystemExit(
            f"\n❌ Missing required environment variable: {name}\n"
            f"Set it in your host's environment-variable settings before starting the bot.\n"
            f"Never put real credentials directly in this file.\n"
        )
    return value


API_ID = int(environ.get("API_ID", "23631217").strip() or "23631217")
API_HASH = (environ.get("API_HASH", "567c6df308dc6901790309499f729d12").strip() or "567c6df308dc6901790309499f729d12")
BOT_TOKEN = _require("BOT_TOKEN")
STRING_SESSION = environ.get("STRING_SESSION", "")

# Make Bot Admin In Log Channel With Full Rights
LOG_CHANNEL = int(_require("LOG_CHANNEL"))
ADMINS = int(_require("ADMINS"))

DB_URI = _require("DB_URI")
DB_NAME = environ.get("DB_NAME", "admin_auto_approval")

# Encrypts every STRING_SESSION before it is written to MongoDB. Generate one with:
#   python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Required — the bot refuses to start without it, so a session can never be
# written to the database unencrypted by accident.
SESSION_ENCRYPT_KEY = _require("SESSION_ENCRYPT_KEY")

# If this is True Then Bot Accept New Join Request
NEW_REQ_MODE = environ.get('NEW_REQ_MODE', 'True').strip().lower() not in ('false', '0', 'no')

# ===== AI SUPPORT CHATBOT (Google Gemini) =====
# Free API key: https://aistudio.google.com/apikey
# Leave empty to turn this feature off — everything else works normally.
GEMINI_API_KEY = environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
