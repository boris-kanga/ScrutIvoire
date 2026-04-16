import uuid
from typing import List

from src.domain.election import Election, Document
from src.infrastructure.database.pgdb import PgDB

from functools import partial


class ElectionRepo:
    def __init__(self, db: PgDB):
        self.db = db

    async def get_election_by_status(self, status) -> List[Election]:
        els = await self.db.run_query(
            """
            SELECT * FROM elections
            WHERE status = $1
            """, params=(status,)
        )
        elections = []
        for el in els:
            _id = uuid.UUID(str(el["id"]))
            el = Election(
                name=el["name"],
                type=el["type"],
                status=el["status"]
            )
            el.id = _id
            elections.append(el)
        return elections

    async def create_election_document(self, doc: Document):
        print(doc.to_dict())

        _id = await self.db.insert(
            doc.to_dict(), "source_documents", id_field="id"
        )
        doc.id = uuid.UUID(str(_id))
        return doc

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
