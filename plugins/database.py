import motor.motor_asyncio
from config import DB_NAME, DB_URI


class Database:

    def __init__(self, uri, database_name):
        self._client = motor.motor_asyncio.AsyncIOMotorClient(uri)
        self.db = self._client[database_name]
        self.col = self.db.users
        self.admin_col = self.db.admins

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


db = Database(DB_URI, DB_NAME)
