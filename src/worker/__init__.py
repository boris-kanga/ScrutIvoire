import asyncio
import re

import pdfplumber

from kb_tools.tools import remove_accent_from_text


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

from src.services.election_service import ElectionService
from src.utils.tools import extract_date_from_text
from src.worker.archive_utils import extract_election_name_from_pdf_page_1, \
    find_pdf_utils_columns


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

    async def archive_processing(self):
        service = ElectionService(ElectionRepo(self.db), self.rd, self.storage)

        def _sync_read(_filename):
            with pdfplumber.open(filename) as pdf:
                for p in pdf.pages:
                    yield p

        async def _async_read(_filename):
            _iter = _sync_read(_filename)
            while True:
                try:
                    p = await asyncio.to_thread(next, _iter)
                    yield p
                except StopIteration:
                    break

        async for message in self.mr.subscribe(
                MessageBrokerChannel.PROCESSING_ELECTION_RAPPORT
        ):
            data = message["data"]
            sid = data["sid"]
            election_id = data["election_id"]
            election = await service.get(election_id)
            if not election:
                return
            doc = election.doc
            async with doc.get() as filename:
                page1 = None
                async for page in _async_read(filename):
                    if page1 is None:
                        page1 = page
                        name = await asyncio.to_thread(
                            extract_election_name_from_pdf_page_1,
                            page1
                        )
                        if name is not None:
                            await self.socket.emit(
                                "election_processing",
                                {
                                    "election_name": name,
                                },
                                to=sid
                            )
                        # detecter les colonnes du tableau.
                        table = await asyncio.to_thread(
                            page.extract_table
                        )
                        column = find_pdf_utils_columns(table)








    async def run(self):
        await asyncio.gather(
            self.archive_processing(),
        )
