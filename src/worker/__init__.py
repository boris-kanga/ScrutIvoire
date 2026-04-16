import asyncio

from src.infrastructure.database.pgdb import PgDB
from src.infrastructure.database.redisdb import RedisDB
from src.infrastructure.file_storage import FileStorageProtocol

from socketio import AsyncRedisManager

from src.core.config import POSTGRES_DB_URI, REDIS_CONFIG, S3_CONFIG
from src.infrastructure.file_storage.s3 import S3StorageAdapter
from src.infrastructure.message_broker.redis_message_broker import \
    RedisMessageBroker

from src.domain.message_broker import MessageBrokerChannel
from src.repository.election_repo import ElectionRepo


class Worker:
    def __init__(
            self,
            db: PgDB = None,
            rd: RedisDB = None,
            storage: FileStorageProtocol = None,
            socket = None
    ):
        if db is None:
            db = PgDB(dsn=POSTGRES_DB_URI)

        if rd is None:
            rd = RedisDB(url='redis://{host}:{port}'.format(**REDIS_CONFIG))

        if storage is None:
            storage = S3StorageAdapter(**S3_CONFIG)
        if socket is None:
            socket = AsyncRedisManager(**REDIS_CONFIG)


        self.db = db
        self.rd = rd
        self.storage = storage

        self.socket = socket

        self.mr = RedisMessageBroker(self.rd)

    def archive_processing(self):
        async for message in self.mr.subscribe(
                MessageBrokerChannel.PROCESSING_ELECTION_RAPPORT
        ):
            data = message["data"]
            sid = data["sid"]
            election_id = data["election_id"]
            election = await ElectionRepo(self.db).get(election_id)


    async def run(self):
        pass
