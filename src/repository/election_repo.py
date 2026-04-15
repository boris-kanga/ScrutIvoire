from src.infrastructure.database.pgdb import PgDB
from src.infrastructure.database.redisdb import RedisDB


class ElectionRepo:
    def __init__(self, db: PgDB, rd: RedisDB):
        self.db = db
        self.rd = rd

    async def get_current_election(self):
        return await self.rd.get("election:current")