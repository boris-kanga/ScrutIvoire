import contextlib
import json
import re
import uuid
from datetime import datetime
from functools import partial
from typing import Optional

import aiofiles
from kb_tools.tools import remove_accent_from_text

from thefuzz import process, fuzz

from src.core.logger import get_logger
from src.domain.election import Election, Document, DocumentType, \
    LocalityStagingResult, int_parser
from src.infrastructure.database.redisdb import RedisDB
from src.infrastructure.file_storage import FileStorageProtocol
from src.infrastructure.message_broker.redis_message_broker import \
    RedisMessageBroker
from src.repository.election_repo import ElectionRepo

from src.domain.message_broker import MessageBrokerChannel

from io import BytesIO, IOBase

from src.repository.entity_resolution import EntityResolution
from src.utils.tools import value_parser, calculer_hash

REPORT_FILE_NAME = "rapport.pdf"


logger = get_logger(__name__)


class ElectionService:

    def __init__(self, repo: ElectionRepo, rd: RedisDB, storage: FileStorageProtocol):
        self.repo = repo
        self.rd = rd
        self._mr = RedisMessageBroker(self.rd)

        self.storage = storage

        self.resolver_entity = EntityResolution(
            repo.db
        )

    async def set_archive_process_working(self, actual, election_id, room=None):
        await self.rd.set("process-" + str(election_id), actual)

    async def delete_archive_process_working(self, election_id):
        await self.rd.delete("process-" + str(election_id))

    async def get_archive_process_state(self, election_id):
        return await self.rd.get("process-" + str(election_id))

    async def get_all(self, with_integrity=False):
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
                **({} if not with_integrity else {
                    "integrity_status": el.doc.integrity_status,
                    "last_integrity_check": el.doc.last_integrity_check
                }),
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

    @staticmethod
    def text_as_canonic(text):
        return remove_accent_from_text((" ".join(text.split())).upper())

    async def add_extracted_archive_data(self, extracted_locality, election):
        ref_entities = []

        locality_staging = []
        candidate_staging = []
        circonscriptions = []
        candidates_raw = []

        regions = {ll["stage"]["region"] for ll in extracted_locality}
        regions = [
            {"election_id": election.id, "original_raw_name": r}
            for r in regions
        ]
        regions = {
            r["original_raw_name"]: i
            for r, i in zip(
                regions,
                await self.repo.insert_archived_staging_data(regions=regions)
            )
        }
        ref_entities += [
            {
                "election_id": election.id,
                "region_id": i,
                "canonic_name": self.text_as_canonic(raw),
                "raw_name": raw,
                "type": "REGION"

            }
            for raw, i in regions.items()
        ]

        political_parties = {
            c.get("party_ticker")
            for ll in extracted_locality
            for c in ll["candidates"]
            if c.get("party_ticker")
        }
        political_parties = [
            {"election_id": election.id, "original_raw_name": p}
            for p in political_parties
        ]

        political_parties = {
            r["original_raw_name"]: i
            for r, i in zip(
                political_parties,
                await self.repo.insert_archived_staging_data(political_parties=political_parties)
            )
        }
        ref_entities += [
            {
                "election_id": election.id,
                "party_id": i,
                "canonic_name": self.text_as_canonic(raw),
                "raw_name": raw,
                "type": "PARTY"

            }
            for raw, i in political_parties.items()
        ]


        # massive insert circonscriptions
        locality_skipped = []
        for locality in extracted_locality:
            # winner - value - cords - candidates
            circonscriptions.append({
                "election_id": election.id,
                "region_id": regions[locality["stage"].pop("region")],
                "original_raw_name": locality["value"].replace("\n", " "),
                "source_id": election.doc.id,
                "bbox_json": json.dumps(locality["cords"]),
                "crop_url": locality["crop_url"]
            })

        c_ids = await self.repo.insert_archived_staging_data(
            circonscriptions=circonscriptions
        )

        for i, locality in enumerate(extracted_locality):
            # winner - value - cords - candidates
            cc = circonscriptions[i]
            refs = self.resolver_entity.extraction_ref_entities(cc["original_raw_name"], type_="locality")
            ref_entities += [
                {
                    "circonscription_id": c_ids[i],
                    "election_id": election.id,
                    **r
                }
                for r in refs
            ]

            try:
                staging = LocalityStagingResult(
                    **locality["stage"],
                    election_id=election.id,
                    circonscription_id=c_ids[i],
                )
            except TypeError:
                locality_skipped.append(locality)
                logger.info("On skip la localite pour imcompletude de donnee.")
                # Cas https://cei.ci/wp-content/uploads/2023/09/Municipales_2023.pdf
                # SARHALA
                continue

            locality_staging.append(staging)
        await self.repo.insert_archived_staging_data(
            localities=locality_staging
        )
        # state insert candidates
        reg = re.compile(r"\bi+n+d+(?:[eé]+p+[ea]+n+t+e*)?\b", flags=re.IGNORECASE)
        for i, locality in enumerate(extracted_locality):
            for c in locality["candidates"]:
                is_ind = (
                    None if not c["party_ticker"] else
                    reg.search(c["party_ticker"]) is not None
                )
                cand = {
                    "election_id": election.id,
                    "original_raw_name": c["full_name"],
                    "bbox_json": json.dumps(c["bbox_json"]),
                    "is_independent": is_ind,
                    "source_id": election.doc.id,
                    "crop_url": c["crop_url"]
                }
                if is_ind is False:
                    cand["party_id"] = political_parties.get(c.get("party_ticker"))

                if election.is_national:
                    pass
                else:
                    cand["circonscription_id"] = c_ids[i]
                candidates_raw.append(cand)

                candidate_staging.append(
                    dict(
                        circonscription_id = c_ids[i],
                        raw_value=value_parser(int_parser, c["raw_value"], 0),
                        winner=c.get("winner")
                    )
                )

        candidate_ids = await self.repo.insert_archived_staging_data(
            candidates_raw=candidates_raw
        )
        candidate_staging = [
            {
                **c,
                "candidate_id": candidate_ids[i],
                "election_id": election.id
            }
            for i, c in enumerate(candidate_staging)
        ]
        await self.repo.insert_archived_staging_data(
            candidates_staging=candidate_staging
        )

        ref_entities += [
            {
                "election_id": election.id,
                "candidate_id": c["candidate_id"],
                "type": "CANDIDATE",
                "canonic_name": self.text_as_canonic(candidates_raw[i]["original_raw_name"]),
                "raw_name": candidates_raw[i]["original_raw_name"]
            }
            for i, c in enumerate(candidate_staging)
        ]

        # alimentation de ref_entities
        # ref_entities
        await self.repo.insert_archived_staging_data(
            ref_entities=ref_entities
        )
        return locality_skipped

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

    async def get_history(self, election_id, session_id):
        return await self.repo.get_chat_history(
            election_id, session_id
        )

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
            election.delete = partial(self.repo.delete_election, election.id)

            election.update = partial(self.repo.update_election, election)
        return election

    async def delete_archive(self, election_id):
        await self.repo.delete_election(election_id)
        await self.storage.delete_bucket(str(election_id))
        await self.delete_archive_process_working(election_id)
        # CANCEL_ELECTION_PROCESS
        if await self.rd.get(f"election:{election_id}:process_id"):
            await self._mr.publish(
                MessageBrokerChannel.CANCEL_ELECTION_PROCESS,
                {
                    "election_id": str(election_id)
                }
            )

    async def verify_report_integrity(self, election_id):
        el = await self.get(election_id)
        doc = el.doc
        if not el.doc.integrity_status:
            return {
                "last_integrity_check": el.doc.last_integrity_check,
                "integrity_status": el.doc.integrity_status
            }

        async with doc.get() as filename:
            if doc.integrity_hash == await calculer_hash(filename):
                doc.last_integrity_check = datetime.now()
            else:
                doc.last_integrity_check = datetime.now()
                doc.integrity_status = False
            await self.repo.update_election(el)
        return {
            "last_integrity_check": el.doc.last_integrity_check,
            "integrity_status": el.doc.integrity_status
        }

    async def get_integrity_status(self, election_id):
        el = await self.get(election_id)
        return {
            "last_integrity_check": el.doc.last_integrity_check,
            "integrity_status": el.doc.integrity_status
        }

    async def start_archiving_process(
            self,
            election: Election,
            archive_hash,
            file: BytesIO,
            uploaded_by:Optional[uuid.UUID],
            room_id,
            /, filename=None
    ):
        if not filename:
            filename = str(file.name)
        # TODO: case xlsx file
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
                "room": room_id,
                "election_id": str(election.id)
            }
        )

    async def ask_llm(self, question, archive_id, room_id):
        await self._mr.publish(
            MessageBrokerChannel.CHAT,
            {
                "room": room_id,
                "election_id": archive_id,
                "question": question

            }
        )
        # on va attendre que le worker reponde
        async for m in self._mr.subscribe(room_id, timeout=60):
            break

