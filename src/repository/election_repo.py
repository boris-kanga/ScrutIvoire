import uuid
from typing import List

from src.domain.election import Election, Document, DocumentType, \
    LocalityStagingResult, CandidateStagingResult
from src.infrastructure.database.pgdb import PgDB

from functools import partial


class ElectionRepo:
    def __init__(self, db: PgDB):
        self.db = db

    @staticmethod
    def _dict_to_election(_dict):
        el = Election(
            name=_dict["name"],
            type=_dict["type"],
            status=_dict["status"]
        )
        el.id = uuid.UUID(str(_dict["id"]))
        return el

    async def get_election_by_status(self, status) -> List[Election]:
        els = await self.db.run_query(
            """
            SELECT * FROM elections
            WHERE status = $1
            """, params=(status,)
        )
        return [self._dict_to_election(el) for el in els]

    async def get_document_by_url(self, file_url, election_id):
        meta = await self.db.run_query(
            """
            SELECT * FROM source_documents
            WHERE storage_url=$1
            AND election_id=$2
            """, params=(file_url, election_id), limit=1
        )
        if not meta:
            return None
        meta = meta[0]
        doc = Document(
            election_id=election_id,
            file_name=meta["file_name"],
            file_type=DocumentType(meta["file_type"]),
            storage_url=file_url,
            integrity_hash=meta["integrity_hash"],
            uploaded_by=uuid.UUID(str(meta["uploaded_by"])),
            uploaded_at=meta["uploaded_at"],
            last_integrity_check=meta["last_integrity_check"],
            integrity_status=meta["integrity_status"],

        )
        doc.id = uuid.UUID(str(meta["id"]))
        return doc

    async def create_election_document(self, doc: Document):
        _id = await self.db.insert(
            doc.to_dict(), "source_documents", id_field="id"
        )
        doc.id = uuid.UUID(str(_id))
        return doc

    async def get(self, election_id):
        res = await self.db.run_query(
            """
            SELECT * FROM elections
            WHERE id = $1
            """, params=(election_id,), limit=1
        )
        if not res:
            return None
        res = res[0]
        return self._dict_to_election(res)

    async def delete_election(self, election_id):
        await self.db.run_query(
            """
            DELETE FROM elections WHERE id = $1
            """, params=(election_id,)
        )

    async def update_election(self, election: Election):
        await self.db.run_query(
            """
            UPDATE elections
            SET
                name=$1,
                status=$2,
                type=$3
            WHERE id = $4
            """,
            params=(
                election.name,
                election.status,
                election.type,
                election.id
            ),

        )

    async def add_election(self, election: Election):
        election.id = await self.db.insert({
            "name": election.name,
            "status": election.status,
            "type": election.type,
        }, "elections", id_field="id")
        election.id = uuid.UUID(str(election.id))
        election.delete = partial(self.delete_election, election.id)

        election.update = partial(self.update_election, election)

        return election

    async def insert_archived_staging_data(
            self, *, locality: List[LocalityStagingResult]=None,
            candidate: List[CandidateStagingResult]=None
    ):
        res = None
        if locality:
            res = await self.db.insert_many(
                [s.to_dict(bbox_json_as_text=True) for s in locality],
                "locality_results_staging",
                id_field="id"
            )
        else:
            await self.db.insert_many(
                [s.to_dict(bbox_json_as_text=True) for s in candidate],
                "candidate_results_staging",
                id_field="id"
            )
        return res
