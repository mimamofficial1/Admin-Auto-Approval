from os import environ

API_ID = int(environ.get("API_ID", "23631217"))
API_HASH = environ.get("API_HASH", "567c6df308dc6901790309499f729d12")
BOT_TOKEN = environ.get("BOT_TOKEN", "")
STRING_SESSION = environ.get("STRING_SESSION", "")

# Make Bot Admin In Log Channel With Full Rights
LOG_CHANNEL = int(environ.get("LOG_CHANNEL", "-1002154224937"))
ADMINS = int(environ.get("ADMINS", "6139759254"))

# Warning - Give Db uri in deploy server environment variable, don't give in repo.
DB_URI = environ.get("DB_URI", "mongodb+srv://mohammadmuzaffarimambaturbari:sHXNxpKZ9PDjyYQr@cluster0.dqjjo.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
DB_NAME = environ.get("DB_NAME", "mohammadmuzaffarimambaturbari")

# If this is True Then Bot Accept New Join Request
NEW_REQ_MODE = bool(environ.get('NEW_REQ_MODE', True))

# ===== AI SUPPORT CHATBOT (Google Gemini) =====
# Free API key yahan se lo: https://aistudio.google.com/apikey
# Agar yeh empty rahega, AI chatbot feature silently OFF rahega - baaki
# bot ka kaam normal chalta rahega.
GEMINI_API_KEY = environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
