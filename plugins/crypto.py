"""
plugins/crypto.py
──────────────────
Encrypts Telegram STRING_SESSION values before they are stored in MongoDB.

Why: a STRING_SESSION is a full, no-password login to the Telegram account
that generated it. Storing it in plain text means a database leak (a
misconfigured connection string, a backup, a hacked server) hands over
every connected account instantly. This encrypts it with a key that lives
only in the bot's environment variables, never in the database and never
in the git repo.

Setup: generate a key ONCE and set it as the SESSION_ENCRYPT_KEY env var
on your host (Koyeb / Railway / Render / Sevalla settings panel):

    python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Keep this key secret and never commit it. Losing it makes every stored
session unreadable; changing it does the same, so copy it once, store it
in your host's env vars, and leave it alone.
"""
import logging

from cryptography.fernet import Fernet, InvalidToken
from config import SESSION_ENCRYPT_KEY

logger = logging.getLogger(__name__)

_fernet = Fernet(SESSION_ENCRYPT_KEY.encode()) if SESSION_ENCRYPT_KEY else None

# A Pyrofork STRING_SESSION is base64 of a fixed-size struct and is never
# this long or shaped like a Fernet token (always starts with "gAAAAA").
_FERNET_PREFIX = "gAAAAA"


def encrypt_session(session_string: str) -> str:
    """Encrypt before writing to MongoDB. Returns the session unchanged if
    no key is configured (logged loudly so it's never a silent downgrade)."""
    if not _fernet:
        logger.warning("SESSION_ENCRYPT_KEY not set — sessions are being stored UNENCRYPTED.")
        return session_string
    return _fernet.encrypt(session_string.encode()).decode()


def decrypt_session(stored_value: str) -> str:
    """Decrypt a value read from MongoDB. Transparently accepts an older,
    unencrypted session (saved before SESSION_ENCRYPT_KEY existed) so
    nobody is logged out by this change — the next save re-encrypts it."""
    if not stored_value:
        return stored_value
    if not stored_value.startswith(_FERNET_PREFIX):
        return stored_value  # legacy plaintext value
    if not _fernet:
        logger.error("Stored session is encrypted but SESSION_ENCRYPT_KEY is not set — cannot decrypt.")
        return None
    try:
        return _fernet.decrypt(stored_value.encode()).decode()
    except InvalidToken:
        logger.error("Could not decrypt a stored session — SESSION_ENCRYPT_KEY may have changed.")
        return None
