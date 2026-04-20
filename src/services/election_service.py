import contextlib
import re
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

    async def get_all(self):
        els = await self.repo.get_all_elections()
        stats = await self.repo.get_stat(
            [e.id for e in els],
        )
        stats = {
            str(s["election_id"]): s
            for s in stats
        }

        return [
            {
                **(stats.get(str(el.id)) or {}),
                **el.to_dict(),
                "nat": (el.type or "").lower() in ("presidential", "referendum")
            }
            for el in els
        ]

    async def top_n_locality(self, election, n=5):
        res = await self.repo.get_locality_participation_rate(election.id)
        return sorted(res, key=lambda r: r["participation_rate"], reverse=True)[:n]

    async def party_ticker_repr(self, election):
        winners = await self.repo.election_winner(election.id)
        party_ticker = {}
        independent = 0
        for winner in winners:
            if winner["is_independent"]:
                independent += 1
                continue
            party_ticker.setdefault(winner["party_ticker"], []).append(1)
        party_ticker = [[p, sum(s)] for p, s in party_ticker.items()]
        party_ticker = sorted(party_ticker, key=lambda r: r[1], reverse=True)
        party_ticker.append(["INDEPENDANT", independent])
        return party_ticker

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
            )

            locality_staging.append(staging)
        ids = await self.repo.insert_archived_staging_data(
            localities=locality_staging
        )
        reg = re.compile(r"\bi+n+d+\wp+e+n+", flags=re.IGNORECASE)
        for i, locality in enumerate(extracted_locality):
            for c in locality["candidates"]:
                c = CandidateStagingResult(
                    locality_id=ids[i],
                    full_name=c["full_name"],
                    raw_value=c["raw_value"],
                    bbox_json=c["bbox_json"],
                    party_ticker=c["party_ticker"],
                    winner=c.get("winner"),
                    is_independent=(
                        None if not c["party_ticker"] else
                        reg.search(c["party_ticker"]) is not None
                    )
                )
                candidate_staging.append(c)
        ids = await self.repo.insert_archived_staging_data(
            candidates=candidate_staging
        )
        winners = []
        for i, c in enumerate(candidate_staging):
            if c.winner:
                winners.append({
                    "candidate_id": ids[i]
                })
        await self.repo.insert_archived_staging_data(
            locality_winners=winners
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

        if await self.storage.file_exists(str(election_id), REPORT_FILE_NAME):

            @contextlib.asynccontextmanager
            async def _():
                async with aiofiles.tempfile.NamedTemporaryFile(mode="w+b", suffix=".pdf") as f:
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

    async def delete_archive(self, election_id):
        await self.repo.delete_election(election_id)
        await self.storage.delete_bucket(str(election_id))

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

        print("pulication")
        await self._mr.publish(
            MessageBrokerChannel.PROCESSING_ELECTION_RAPPORT,
            {
                "sid": sid,
                "election_id": str(election.id)
            }
        )
        print("ok")