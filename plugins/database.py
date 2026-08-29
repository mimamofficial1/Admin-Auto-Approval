import motor.motor_asyncio
from datetime import datetime
from config import DB_NAME, DB_URI


class Database:

    def __init__(self, uri, database_name):
        self._client = motor.motor_asyncio.AsyncIOMotorClient(uri)
        self.db = self._client[database_name]
        self.col = self.db.users
        self.admin_col = self.db.admins
        self.session_col = self.db.sessions
        self.settings_col = self.db.bot_settings
        self.channel_col = self.db.channels
        self.stats_col = self.db.stats

    def new_user(self, id, name):
        return dict(
            id=id,
            name=name,
        )

    async def add_user(self, id, name):
        user = await self.col.find_one({'id': int(id)})
        if not user:
            await self.col.insert_one(self.new_user(id, name))

    async def is_user_exist(self, id):
        user = await self.col.find_one({'id': int(id)})
        return bool(user)

    async def total_users_count(self):
        count = await self.col.count_documents({})
        return count

    async def get_all_users(self):
        return self.col.find({})

    async def delete_user(self, user_id):
        await self.col.delete_many({'id': int(user_id)})

    # ===== ADMIN SYSTEM =====

    async def add_admin(self, user_id):
        exists = await self.admin_col.find_one({'id': int(user_id)})
        if not exists:
            await self.admin_col.insert_one({'id': int(user_id)})
            return True
        return False

    async def remove_admin(self, user_id):
        result = await self.admin_col.delete_one({'id': int(user_id)})
        return result.deleted_count > 0

    async def get_all_admins(self):
        admins = []
        async for admin in self.admin_col.find({}):
            admins.append(admin['id'])
        return admins

    async def is_admin(self, user_id):
        admin = await self.admin_col.find_one({'id': int(user_id)})
        return bool(admin)

    # ===== PER-USER STRING_SESSION (self-service, MULTIPLE sessions/user) =====
    # Stored as {'id': user_id, 'sessions': {name: session_string, ...}}
    # so one person can add several of their own accounts (e.g. "main",
    # "backup") and pick which one manages which saved channel.

    async def _raw_sessions(self, user_id):
        doc = await self.session_col.find_one({'id': int(user_id)})
        if not doc:
            return {}
        if 'sessions' in doc:
            return doc['sessions']
        if 'session' in doc:  # backward compat with the older single-session format
            return {'default': doc['session']}
        return {}

    async def set_session(self, user_id, session_string, name='default'):
        sessions = await self._raw_sessions(user_id)
        sessions[name] = session_string
        await self.session_col.update_one(
            {'id': int(user_id)},
            {'$set': {'sessions': sessions}, '$unset': {'session': ""}},
            upsert=True
        )

    async def get_session(self, user_id, name='default'):
        sessions = await self._raw_sessions(user_id)
        if name in sessions:
            return sessions[name]
        if sessions and name == 'default':
            return next(iter(sessions.values()))  # only one saved -> use it as default
        return None

    async def get_all_sessions(self, user_id):
        return await self._raw_sessions(user_id)

    async def remove_session(self, user_id, name='default'):
        sessions = await self._raw_sessions(user_id)
        if name not in sessions:
            return False
        del sessions[name]
        await self.session_col.update_one(
            {'id': int(user_id)},
            {'$set': {'sessions': sessions}}
        )
        return True

    # ===== GLOBAL STRING_SESSION (owner-set via /settings, like store bot) =====

    async def set_global_session(self, session_string):
        await self.settings_col.update_one(
            {'_id': 'global'},
            {'$set': {'session': session_string}},
            upsert=True
        )

    async def get_global_session(self):
        doc = await self.settings_col.find_one({'_id': 'global'})
        return doc['session'] if doc else None

    async def remove_global_session(self):
        result = await self.settings_col.delete_one({'_id': 'global'})
        return result.deleted_count > 0

    # ===== SAVED CHANNELS (per-user, with per-channel auto-accept toggle) =====

    async def add_channel(self, user_id, chat_id, title=None, session_name='default'):
        existing = await self.channel_col.find_one({'user_id': int(user_id), 'chat_id': int(chat_id)})
        await self.channel_col.update_one(
            {'user_id': int(user_id), 'chat_id': int(chat_id)},
            {
                '$set': {'title': title, 'session_name': session_name},
                '$setOnInsert': {'auto_accept': True} if not existing else {},
            },
            upsert=True
        )

    async def remove_channel(self, user_id, chat_id):
        result = await self.channel_col.delete_one({'user_id': int(user_id), 'chat_id': int(chat_id)})
        return result.deleted_count > 0

    async def get_user_channels(self, user_id):
        return [c async for c in self.channel_col.find({'user_id': int(user_id)})]

    async def get_channel(self, user_id, chat_id):
        return await self.channel_col.find_one({'user_id': int(user_id), 'chat_id': int(chat_id)})

    async def get_channel_config_by_chat_id(self, chat_id):
        """The auto-approve listener only knows the chat_id (not which user
        saved it) - this looks it up regardless of owner."""
        return await self.channel_col.find_one({'chat_id': int(chat_id)})

    async def toggle_auto_accept(self, user_id, chat_id):
        ch = await self.get_channel(user_id, chat_id)
        if not ch:
            return None
        new_val = not ch.get('auto_accept', True)
        await self.channel_col.update_one({'_id': ch['_id']}, {'$set': {'auto_accept': new_val}})
        return new_val

    async def get_all_auto_accept_channels(self):
        return [c async for c in self.channel_col.find({'auto_accept': True})]

    async def get_all_channels(self):
        return [c async for c in self.channel_col.find({})]

    # ===== PER-CHANNEL STATS =====

    async def increment_stats(self, chat_id, count=1):
        if count <= 0:
            return
        await self.stats_col.update_one(
            {'chat_id': int(chat_id)},
            {'$inc': {'total': count}, '$set': {'last_updated': datetime.utcnow()}},
            upsert=True
        )

    async def get_stats(self, chat_id):
        doc = await self.stats_col.find_one({'chat_id': int(chat_id)})
        return doc['total'] if doc else 0

    async def get_all_stats(self):
        return [s async for s in self.stats_col.find({})]


db = Database(DB_URI, DB_NAME)
