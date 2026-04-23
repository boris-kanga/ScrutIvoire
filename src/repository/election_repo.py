import json
import uuid
from datetime import datetime
from typing import List

from kb_tools.tools import get_buffer

from src.domain.election import Election, Document, DocumentType, \
    LocalityStagingResult
from src.infrastructure.database.pgdb import PgDB

from functools import partial

from src.utils.tools import cache


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

        if _dict.get("doc_id"):
            el.doc = Document(
                election_id=el.id,
                file_name=_dict["file_name"],
                storage_url=_dict["storage_url"],
                integrity_hash=_dict["integrity_hash"],
                uploaded_by=_dict["uploaded_by"],
                file_type=_dict["file_type"],
                uploaded_at=_dict["uploaded_at"],
                last_integrity_check=_dict["last_integrity_check"],
                integrity_status=_dict["integrity_status"]
            )
            el.doc.id = uuid.UUID(str(_dict["doc_id"]))

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
                WITH zone AS (
                        SELECT 
                         id as c_id
                        FROM circonscriptions
                        WHERE election_id IN (
                                {",".join("$%s"%(i+1) for i in range(len(b)))}
                            )
                    ),
                    locality_res AS (
                        SELECT 
                            *
                        FROM locality_results_staging l INNER JOIN zone
                            ON l.circonscription_id=c_id
                    ),
                    seat AS (
                        SELECT 
                            c_id,
                            SUM(CASE WHEN winner THEN 1 ELSE 0 END) as seat_count
                        FROM candidate_results_staging c INNER JOIN zone
                            on c.circonscription_id=c_id
                        GROUP BY c_id
                    )
                SELECT 
                    l.election_id,
                    sum(voters_total) AS voters_total,
                    sum(expressed_votes) AS expressed_votes,
                    sum(pop_size) AS pop_size,
                    SUM(registered_voters_total) AS registered_voters_total,
                    SUM(seat_count) AS nb_seat
                    
                FROM locality_res l LEFT JOIN seat
                    ON l.c_id = seat.c_id
                
                GROUP BY l.election_id
                """, params=tuple(b)
            )
        return res

    async def get_all_elections(self):
        els = await self.db.run_query(
            """
            SELECT 
            s.*, 
            s.id as doc_id,
            e.*
            FROM elections e LEFT JOIN source_documents s
                ON e.id=s.election_id
            WHERE e.status = 'ARCHIVED'
            """
        )
        return [self._dict_to_election(el) for el in els]

    async def get_locality_participation_rate(self, election_id):
        return await self.db.run_query(
            """
            SELECT 
                l.id, 
                c.original_raw_name AS locality,
                participation_rate
            FROM locality_results_staging l INNER JOIN circonscriptions c
                ON l.circonscription_id = c.id
            WHERE c.election_id = $1
            """, params=(election_id,)
        )

    async def election_winner(self, election_id):
        # SELECT crs.raw_value FROM candidate_results_staging crs JOIN candidates c ON crs.candidate_id = c.id WHERE c.party_id = 63 AND c.election_id = '0a17a7d8-e39c-428d-aae5-1d0ebd42ba25' AND c.is_independent = False
        return await self.db.run_query(
            """
            WITH cand AS (
                SELECT 
                    c.id                AS candidate_id,
                    p.original_raw_name AS party_ticker,
                    c.original_raw_name AS full_name,
                    c.election_id,
                    is_independent
                FROM candidates c LEFT JOIN political_parties p
                    ON c.party_id = p.id
            )
            SELECT
                w.circonscription_id,
                cand.party_ticker, 
                cand.full_name,
                cand.is_independent
            FROM 
                cand INNER JOIN
                candidate_results_staging w
                    ON cand.candidate_id = w.candidate_id
            WHERE cand.election_id = $1 AND winner
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
        if getattr(election, "doc", None):
            doc = election.doc
            await self.db.run_query(
                """
                UPDATE source_documents
                SET 
                    last_integrity_check=$1,
                    integrity_status=$2
                WHERE id = $3
                """,
                params=(
                    doc.last_integrity_check,
                    doc.integrity_status,
                    doc.id
                )
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
            self, *,
            regions=None,
            political_parties=None,
            circonscriptions=None,
            candidates_raw=None,

            localities: List[LocalityStagingResult]=None,
            candidates_staging=None,
            ref_entities=None
    ):
        res = None
        if regions:
            res = await self.db.insert_many(
                regions,
                "regions",
                id_field="id"
            )
        elif political_parties:
            res = await self.db.insert_many(
                political_parties,
                "political_parties",
                id_field="id"
            )
        elif circonscriptions:
            res = await self.db.insert_many(
                circonscriptions,
                "circonscriptions",
                id_field="id"
            )
        elif candidates_raw:
            res = await self.db.insert_many(
                candidates_raw,
                "candidates",
                id_field="id"
            )
        elif localities:
            res = await self.db.insert_many(
                [s.to_dict() for s in localities],
                "locality_results_staging",
                id_field="id"
            )
        elif candidates_staging:
            res = await self.db.insert_many(
                candidates_staging,
                "candidate_results_staging",
                id_field="id"
            )
        elif ref_entities:
            res = await self.db.insert_many(
                ref_entities,
                "ref_entities",
                id_field="id"
            )
        return res

    async def insert_question(self, dict_q):
        return await self.db.insert(
            dict_q, "chat_session", id_field="id"
        )

    async def update_question(
            self,
            question_id,
            answer, answer_meta, status
    ):
        await self.db.run_query(
            """
            UPDATE chat_session
                SET status = $1,
                    answer=$2,
                    answer_meta=$3,
                    answer_time=$4
                WHERE id=$5
            """,
            params=(
                status, answer, json.dumps(answer_meta), datetime.now(),
                question_id
            )
        )

    async def get_chat_history(self, election_id, session_id, status="DONE"):
        res = await self.db.run_query(
            f"""
            SELECT * 
            FROM chat_session 
            WHERE election_id = $1 AND session_id=$2
            {'AND status=$3' if status else ''}
            ORDER BY ask_time
            """, params=(
                election_id,
                session_id, *([] if not status else [status])
            )
        )
        data = []
        for r in res:
            try:
                data.append(
                    {
                        "question": r["question"],
                        "answer": json.loads(r["answer"])
                    }
                )
            except json.decoder.JSONDecodeError:
                continue
        return data

    async def get_entity_by_category(self, category, election_id):
        if not isinstance(category, list):
            category = [category]
        category = list(set(category))
        res = await self.db.run_query(
            f"""
            SELECT * FROM ref_entities
            WHERE type IN (
                {','.join(f'${i+2}' for i,_ in enumerate(category))}
            ) AND election_id=$1
            """, params=(election_id, *category)
        )
        result = []
        for r in res:
            if r["type"] in ("COMMUNE", "SOUS_PREFECTURE", "ZONE"):
                result.append({
                    "canonic_name": r["canonic_name"],
                    "id": r["circonscription_id"]
                })
            elif r["type"] == "REGION":
                result.append({
                    "canonic_name": r["canonic_name"],
                    "id": r["region_id"]
                })
            elif r["type"] == "CANDIDATE":
                result.append({
                    "canonic_name": r["canonic_name"],
                    "id": r["candidate_id"]
                })
            elif r["type"] == "PARTY":
                result.append({
                    "canonic_name": r["canonic_name"],
                    "id": r["party_id"]
                })
        return result
