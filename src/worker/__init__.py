import asyncio
import io
import re
from typing import List

import pdfplumber


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
from src.repository.llm_repo import LLMRepo

from src.services.election_service import ElectionService
from src.utils.tools import extract_date_from_text
from src.worker.archive_utils import extract_election_name_from_pdf_page_1, \
    find_pdf_utils_columns, map_columns_force, get_regions, is_region




class Worker:
    def __init__(
            self,
            db: PgDB = None,
            rd: RedisDB = None,
            storage: FileStorageProtocol = None,
            socket = None,
            llm_repo = None
    ):
        if db is None:
            db = PgDB(dsn=POSTGRES_DB_URI)

        if rd is None:
            rd = RedisDB(url='redis://{host}:{port}'.format(**REDIS_CONFIG))

        if storage is None:
            storage = S3StorageAdapter(**S3_CONFIG)
        if socket is None:
            socket = AsyncRedisManager(**REDIS_CONFIG)

        if llm_repo is None:
            llm_repo = LLMRepo()


        self.db = db
        self.rd = rd
        self.storage = storage

        self.socket = socket

        self.llm_repo = llm_repo

        self.mr = RedisMessageBroker(self.rd)

        self._tasks: List[asyncio.Task] = []

    async def _get_columns_from_archive(self, columns, name):
        messages = self.llm_repo.get_prompt(
            "column_detector",
            user_arg=dict(
                title=name,
                columns=columns,
            ),
            system_arg=dict(
                title=name
            )
        )
        response = {'success': True, 'result': {
            'election_metadata': {'type': 'legislative', 'format': 'row',
                                  'confidence_score': 0.8},
            'mapping_index': {'region': 0, 'locality': 1,
                              'polling_stations_count': 3,
                              'registered_voters_total': 4, 'voters_total': 5,
                              'null_ballots': 7, 'expressed_votes': 8,
                              'blank_ballots_count': 9,
                              'blank_ballots_pct': 10,
                              'unregistered_voters_count': -1},
            'candidate_results': {
                'row_mode': {'party_idx': 11, 'candidate_name_idx': 12,
                             'score_idx': 13, 'percent_idx': 14,
                             'status_idx': -1}, 'column_mode': []}},
                    'provider': 'groq',
                    'model': 'meta-llama/llama-4-scout-17b-16e-instruct',
                    'prompt_tokens': 893, 'completion_tokens': 871,
                    'latency_ms': 5564}

        # response = await self.llm_repo.run(
        #     "column_detector",
        #     messages, {}, timeout=60
        # )
        if not response["success"]:
            rsp, candidate_results_format, candidate_results = map_columns_force(columns)
            if not all(
                (rsp[k] is not None and rsp[k] != -1) for k in (
                "region", "locality", "polling_stations_count",
                "voters_total", "participation_rate",
                )
            ):
                return None
            name = str(name)
            election_type = None
            if "legislative" in name:
                election_type = "legislative"
            return {
                "idx": rsp,
                "candidate_results_format": candidate_results_format,
                "candidate_results": candidate_results,
                "confidence_score": 0.5,
                "election_type": election_type
            }
        else:
            result = response["result"]

            rsp = result["mapping_index"]
            if not all(
                    (rsp[k] is not None and rsp[k] != -1) for k in (
                "region", "locality", "polling_stations_count",
                "voters_total", "participation_rate",
                )
            ):
                return None
            _f = result["election_metadata"]["format"]
            return {
                "idx": rsp,
                "candidate_results_format": _f,
                "candidate_results": result["candidate_results"][_f+"_mode"],
                "confidence_score": result["election_metadata"]["confidence_score"],
                "election_type": result["election_metadata"]["type"]
            }

    async def _processing_archive_task(self, sid, election_id):
        service = ElectionService(ElectionRepo(self.db), self.rd, self.storage)

        election = await service.get(election_id)
        if not election:
            return

        table_settings = {
            # "snap_y_tolerance": 20,
            # "join_tolerance": 100,
            # "vertical_strategy": "lines",
            # "horizontal_strategy": "lines",
            # "snap_tolerance": 3,      # Relie les lignes qui ne se touchent pas tout à fait
            # "join_tolerance": 3,      # Fusionne les bords de cellules proches
            # "edge_min_length": 3,     # Ignore les petits segments parasites

            "vertical_strategy": "lines",  # ou "text" selon ton PDF
            "horizontal_strategy": "lines",
            "snap_y_tolerance": 3,
            # Augmente ceci pour fusionner les lignes proches
            # "join_tolerance": 5,
            "intersection_y_tolerance": 10
        }

        def _sync_read(_filename):
            with pdfplumber.open(_filename) as pdf:
                for p in pdf.pages:
                    yield p

        async def _async_read_pdf(_filename):
            _iter = _sync_read(_filename)
            while True:
                try:
                    p = await asyncio.to_thread(next, _iter)
                    yield p
                except StopIteration:
                    break

        async def _to_async(func, *args, **kwargs):
            return await asyncio.to_thread(func, *args, **kwargs)

        async def _loop(fn, *args, **kw):
            def _inner():
                for p in fn(*args, **kw):
                    yield p

            _iter = _inner()
            while True:
                try:
                    yield await asyncio.to_thread(next, _iter)
                except StopIteration:
                    break

        async def _crop(p, cord, b=None):
            c = await _to_async(p.crop, cord)
            _img = await _to_async(c.to_image, resolution=300)
            if b is None:
                b = io.BytesIO()
            await _to_async(_img.save, b, format="PNG")
            return b

        doc = election.doc
        async with doc.get() as filename:
            page1 = None
            columns_meta = None
            name = None
            column_cache = set()
            index_row = 0
            last_region = None

            last_locality = {
                "value": None,
                "cords": {},
                "stage": {},
                "candidates": []
            }
            page_index = -1

            extracted_locality = []
            async for page in _async_read_pdf(filename):
                page_index += 1
                table_index = 0
                # extract election name from page1
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
                # place the cursor to the right table and calculate: columns_meta and index_row and table_index
                if columns_meta is None:
                    async for table_rows_data in _loop(page.extract_tables,
                                                       table_settings=table_settings):

                        column, index_row = find_pdf_utils_columns(
                            table_rows_data
                        )
                        if column not in column_cache:
                            column_cache.add(column)
                        else:
                            continue
                        columns_meta = await self._get_columns_from_archive(
                            column, name
                        )
                        if columns_meta is not None:
                            break
                        table_index += 1
                    if columns_meta is None:
                        continue
                # at this at step we got the right start page for treatment
                candidate_results_format = columns_meta["candidate_results_format"]
                region_idx = columns_meta["idx"]["region"]
                locality_idx = columns_meta["idx"]["locality"]
                idxs = columns_meta["idx"]
                candidate_results_idx = columns_meta["candidate_results"]

                _current_table_index = 0
                async for table in _loop(
                        page.find_tables, table_settings=table_settings
                ):
                    if _current_table_index < table_index:
                        # to prevent no right table base on the top step.
                        continue
                    index = -1
                    async for row in _loop(table.rows):
                        index += 1
                        if index < index_row:
                            # to don't consider the table header base on index_row calculated a few top
                            continue

                        row_content = await _to_async(row.extract)
                        r = (row_content[region_idx] or "").strip()
                        if not r and not last_region:
                            continue
                        row_box = row.bbox
                        # treat region
                        if r:
                            if r.count("\n") > 2:
                                # texte inverse
                                r = r.replace("\n", "")[::-1]
                            _is_region, rr = await is_region(r)
                            if _is_region:
                                last_region = rr

                        locality = str(
                            row_content[locality_idx] or
                            last_locality["value"] or ""
                        ).lower()
                        if not locality or re.search(
                                r"\b(total|pourcentage|%)\b", locality
                        ) or re.search(r"^[\s\d]*$", locality):
                            continue

                        if locality and locality != last_locality["value"]:
                            # je viens d'obtenir un nouveau locality
                            if last_locality["value"]:
                                _locality_bbox = last_locality["cords"][page_index]
                                _locality_bbox = (
                                    min(b[0] for b in _locality_bbox),
                                    min(b[1] for b in _locality_bbox),
                                    max(b[2] for b in _locality_bbox),
                                    max(b[3] for b in _locality_bbox),
                                )
                                last_locality["cords"][page_index] = _locality_bbox
                                extracted_locality.append(last_locality)

                            last_locality = {
                                "value": locality,
                                "cords": {page_index: []},
                                "candidates": [],
                                "stage": {
                                    "election_id": election_id,
                                    "locality": locality,
                                    "region": last_region,
                                    "source_id": None,
                                    **{
                                        k: row_content[i]
                                            for k,i in idxs.items() if (
                                                i not in (
                                                    -1,
                                                    None,
                                                    region_idx,
                                                    locality_idx
                                                )
                                            )
                                    }
                                }
                            }


                        last_locality["cords"][page_index].append(row_box)

                        if candidate_results_format == "row":
                            cand = {}
                            pty_idx = candidate_results_idx.get("party_idx")

                            if pty_idx is not None and pty_idx != -1:
                                cand["party_ticker"] = row_content[pty_idx]

                            name_idx = candidate_results_idx["candidate_name_idx"]
                            if name_idx is not None and name_idx != -1:
                                cand["full_name"] = row_content[name_idx]

                            score_idx = candidate_results_idx["score_idx"]
                            if score_idx is not None and score_idx != -1:
                                cand["raw_value"] = row_content[score_idx]

                            cand["bbox_json"] = [{page_index: row_box}]

                            last_locality["candidates"].append(cand)
                        else:
                            cand = {}
                            for c in candidate_results_idx:
                                cand["full_name"] = c["candidate_name"]
                                cand["raw_value"] = row_content[c["score_idx"]]
                                if "party_ticker" in c:
                                    cand["party_ticker"] = c["party_ticker"]
                                cand["bbox_json"] = [{page_index: row_box}]
                                last_locality["candidates"].append(cand)

                    # region end
                    # if last_region[0]:
                    #     _region_bbox = last_region[1][page_index]
                    #     _region_bbox = (
                    #         min(b[0] for b in _region_bbox),
                    #         min(b[1] for b in _region_bbox),
                    #         max(b[2] for b in _region_bbox),
                    #         max(b[3] for b in _region_bbox),
                    #     )
                    #     region_img = await _crop(
                    #         page, _region_bbox
                    #     )
                    #     last_region[1][page_index] = _region_bbox
                    #     last_region[2].append(region_img)
                    #     extracted_region.append(last_region)

                    if last_locality["value"]:
                        _locality_bbox = last_locality["cords"][page_index]
                        _locality_bbox = (
                            min(b[0] for b in _locality_bbox),
                            min(b[1] for b in _locality_bbox),
                            max(b[2] for b in _locality_bbox),
                            max(b[3] for b in _locality_bbox),
                        )

                        last_locality["cords"][page_index] = _locality_bbox
                        extracted_locality.append(last_locality)

                    #we suppose only one right table for each page so break the loop
                    break

            if columns_meta is None:
                await self.socket.emit(
                    "election_processing",
                    {
                        "error": (
                            "Le parsing du document a échoué "
                            "a l'etape identification des colonnes"
                        ),
                    },
                    to=sid
                )
            else:
                # loop on extracted_locality
                for locality in extracted_locality:
                    pass
                pass



    async def archive_processing(self):
        async for message in self.mr.subscribe(
                MessageBrokerChannel.PROCESSING_ELECTION_RAPPORT
        ):
            data = message["data"]
            sid = data["sid"]
            election_id = data["election_id"]
            self._tasks.append(
                asyncio.create_task(
                    self._processing_archive_task(
                        sid, election_id
                    )
                )
            )
            await asyncio.sleep(0)

    async def run(self):
        await asyncio.gather(
            self.archive_processing(),
        )
