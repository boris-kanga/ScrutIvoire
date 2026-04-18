import contextlib
import uuid
from functools import partial
from typing import Optional

import aiofiles

from src.domain.election import Election, Document, DocumentType, \
    LocalityStagingResult, CandidateStagingResult
from src.infrastructure.database.redisdb import RedisDB
from src.infrastructure.file_storage import FileStorageProtocol
from src.infrastructure.message_broker.redis_message_broker import \
    RedisMessageBroker
from src.repository.election_repo import ElectionRepo

from src.domain.message_broker import MessageBrokerChannel

from io import BytesIO, IOBase


REPORT_FILE_NAME = "rapport.pdf"

class ElectionService:

    def __init__(self, repo: ElectionRepo, rd: RedisDB, storage: FileStorageProtocol):
        self.repo = repo
        self.rd = rd
        self._mr = RedisMessageBroker(self.rd)

        self.storage = storage

    async def add_extracted_archive_data(self, extracted_locality, election):
        locality_staging = []
        candidate_staging = []
        for locality in extracted_locality:
            # winner - value - cords - candidates
            staging = LocalityStagingResult(
                **locality["stage"],
                locality=locality["value"],
                election_id=election.id,
                source_id=election.doc.id,
                bbox_json=locality["cords"],
                processed_by=None,
                winner=locality["winner"],
            )

            locality_staging.append(staging)
        ids = await self.repo.insert_archived_staging_data(
            locality=locality_staging
        )
        for i, locality in enumerate(extracted_locality):
            for c in locality["candidates"]:
                c = CandidateStagingResult(
                    locality_id=ids[i],
                    full_name=c["full_name"],
                    raw_value=c["raw_value"],
                    bbox_json=c["bbox_json"],
                    party_ticker=c["party_ticker"]
                )
                candidate_staging.append(c)
        await self.repo.insert_archived_staging_data(
            candidate=candidate_staging
        )

    async def get_report_url(self, election_id):
        return await self.storage.get_presigned_url(
            election_id, REPORT_FILE_NAME
        )

    async def get_current_election(self):
        current = await self.rd.get(MessageBrokerChannel.CURRENT_ELECTION)
        if current:
            return current
        drafts = await self.repo.get_election_by_status("DRAFT")
        if drafts:
            return drafts[0]
        return None

    async def get(self, election_id):
        election = await self.repo.get(election_id)

        if not election:
            return None

        if await self.storage.file_exists(election_id, REPORT_FILE_NAME):

            @contextlib.asynccontextmanager
            async def _():
                async with aiofiles.tempfile.TemporaryFile(mode="w+b") as f:
                    await self.storage.download(
                        election_id, REPORT_FILE_NAME, f.name
                    )
                    yield f.name
                return

            doc = await self.repo.get_document_by_url(
                REPORT_FILE_NAME,
                election_id
            )
            doc.get = partial(_)

            election.doc = doc
        return election

    async def start_archiving_process(
            self,
            election: Election,
            archive_hash,
            file: BytesIO,
            uploaded_by:Optional[uuid.UUID],
            sid,
            /, filename=None
    ):
        if not filename:
            filename = str(file.name)
        # TODO: case pdf
        doc = Document(
            election_id=election.id,
            file_name=filename,
            storage_url=REPORT_FILE_NAME,
            integrity_hash=archive_hash,
            uploaded_by=uploaded_by,
            file_type=DocumentType.PDF_ARCHIVE,
        )
        await self.repo.create_election_document(doc)

        await self.storage.upload(
            str(election.id),
            file.read(),
            doc.storage_url
        )

        await self._mr.publish(
            MessageBrokerChannel.PROCESSING_ELECTION_RAPPORT,
            {
                "sid": sid,
                "election_id": str(election.id)
            }
        )