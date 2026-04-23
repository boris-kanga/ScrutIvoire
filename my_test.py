import asyncio
import json
import uuid
import re

from src.domain.election import CandidateStagingResult, LocalityStagingResult
from src.infrastructure.database.pgdb import PgDB
from src.infrastructure.database.redisdb import RedisDB
from src.infrastructure.file_storage.s3 import S3StorageAdapter

from src.core.config import S3_CONFIG, POSTGRES_DB_URI, REDIS_CONFIG
from src.repository.election_repo import ElectionRepo
from src.services.election_service import ElectionService


async def delete_s3_storage():
    from src.worker import Worker
    s = S3StorageAdapter(**S3_CONFIG)

    await s.delete_all_storage()
    #  5V4fz3TLrkb0rX-CAAAF 9e5edcb3-85bb-4a32-9f48-5fa0858a6699
    #await Worker()._processing_archive_task("1", "9e5edcb3-85bb-4a32-9f48-5fa0858a6699")



# asyncio.run(delete_s3_storage())

async def test_main():
    db = PgDB(dsn=POSTGRES_DB_URI)




    election_id = uuid.UUID('8dce6dec-b148-4279-b5e3-ad3f279f87cb')

    rd = RedisDB(url='redis://{host}:{port}'.format(**REDIS_CONFIG))
    storage = S3StorageAdapter(**S3_CONFIG)
    election_service = ElectionService(ElectionRepo(db), rd, storage)
    print(await election_service.get_all())
    election = await election_service.get(election_id)

    print(election)


    with open("tmp.json", "r", encoding="utf-8") as f:
        extracted_locality = json.loads(f.read())
    locality_staging = []
    candidate_staging = []

    await db.run_query("""
    DELETE FROM locality_results_staging;
    DELETE FROM candidate_results_staging;
    DELETE FROM locality_winner
    """)
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
    ids = await election_service.repo.insert_archived_staging_data(
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
    ids = await election_service.repo.insert_archived_staging_data(
        candidates=candidate_staging
    )
    winners = []
    for i, c in enumerate(candidate_staging):
        if c.winner:
            winners.append({
                "candidate_id": ids[i]
            })
    await election_service.repo.insert_archived_staging_data(
        locality_winners=winners
    )

asyncio.run(test_main())

if __name__ == '__main__':
    pass