import uuid
from typing import List

from kb_tools.tools import get_buffer

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

    async def get_stat(self, election_ids):
        res = []
        for b in get_buffer(election_ids, max_buffer=2000, vv=False):

            if not b:
                continue
            res += await self.db.run_query(
                f"""
                WITH winner AS (
                    SELECT 
                        locality_id,
                        count(*) as winner_count
                    FROM locality_winner w INNER JOIN
                        candidate_results_staging c
                        ON c.id = w.candidate_id
                    GROUP BY locality_id
                )
                SELECT 
                    election_id,
                    sum(voters_total) AS voters_total,
                    sum(expressed_votes) AS expressed_votes,
                    sum(pop_size) AS pop_size,
                    SUM(registered_voters_total) AS registered_voters_total,
                    SUM(winner_count) AS nb_seat
                FROM locality_results_staging l LEFT JOIN winner
                    ON l.id = winner.locality_id
                WHERE election_id IN (
                {",".join("$%s"%(i+1) for i in range(len(b)))}
                )
                GROUP BY election_id
                """, params=tuple(b)
            )
        return res

    async def get_all_elections(self):
        els = await self.db.run_query(
            """
            SELECT * FROM elections
            """
        )
        return [self._dict_to_election(el) for el in els]

    async def get_locality_participation_rate(self, election_id):
        return await self.db.run_query(
            """
            SELECT 
                id, 
                locality,
                participation_rate
            FROM locality_results_staging
            WHERE election_id = $1
            """, params=(election_id,)
        )

    async def election_winner(self, election_id):
        return await self.db.run_query(
            """
            SELECT
                party_ticker, 
                full_name,
                l.id AS locality_id,
                locality, 
                region,
                is_independent
            FROM 
                locality_results_staging l INNER JOIN 
                candidate_results_staging c
                    ON l.id = c.locality_id
                INNER JOIN locality_winner w
                    ON w.candidate_id = c.id
            WHERE election_id = $1
            """, params=(election_id,)
        )

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
            self, *, localities: List[LocalityStagingResult]=None,
            candidates: List[CandidateStagingResult]=None,
            locality_winners=None
    ):
        res = None
        if localities:
            res = await self.db.insert_many(
                [s.to_dict(bbox_json_as_text=True) for s in localities],
                "locality_results_staging",
                id_field="id"
            )
        elif candidates:
            res = await self.db.insert_many(
                [s.to_dict(bbox_json_as_text=True) for s in candidates],
                "candidate_results_staging",
                id_field="id"
            )
        elif locality_winners:
            res = await self.db.insert_many(
                locality_winners,
                "locality_winner",
                id_field="id"
            )
        return res
