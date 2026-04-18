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


def get_column_x_bounds(table, col_idx):
    """
    Retourne (x0, x1) de la colonne `col_idx` dans le tableau.
    On prend la première cellule non nulle de cette colonne pour
    récupérer ses bornes horizontales.
    """
    if isinstance(col_idx, list):
        col_idx = col_idx[0]
    for row in table.rows:
        cells = row.cells
        if col_idx < len(cells) and cells[col_idx] is not None:
            cell = cells[col_idx]
            # cell = (x0, top, x1, bottom)
            return cell[0], cell[2]
    return None, None


def get_boundary_edges(page, x0_col, x1_col, *_, tol=5):
    """
    Retourne les Y des lignes horizontales qui traversent la colonne
    définie par [x0_col, x1_col].

    Une ligne horizontale est considérée comme frontière si :
    - elle couvre au moins la plage [x0_col, x1_col]
    - elle a une largeur suffisante (> 10pt) pour ne pas être un artefact

    Calculé une seule fois par page pour éviter de ralentir la boucle.
    """
    boundaries = []
    for e in page.edges:
        # Garder uniquement les edges horizontaux suffisamment longs
        if e.get('width', 0) < 10:
            continue
        # L'edge doit couvrir la colonne ciblée
        if e['x0'] <= x0_col + tol and e['x1'] >= x1_col - tol:
            boundaries.append(e['y0'])

    # Dédupliquer les Y très proches (paires d'edges = les deux bords d'un trait)
    boundaries.sort()
    deduped = []
    for y in boundaries:
        if not deduped or y - deduped[-1] > 2:
            deduped.append(y)

    return deduped


def get_row_content_at_idx(row, idx):
    if isinstance(idx, int):
        idx = [idx]
    res = None
    for i in sorted(idx):
        if i >= 0:
            if row[i] is not None:
                res = ((res or "") + " " + str(row[i])).strip()
    return res


def has_crossed_boundary(row_bbox, boundaries, last_processed_y, tol=2):
    row_bottom = row_bbox[3]
    for boundary_y in boundaries:
        if last_processed_y < boundary_y <= row_bottom + tol:
            return True
    return False


class Worker:
    def __init__(
            self,
            election_service=None,
            socket = None,
            llm_repo = None,
            msg_broker = None
    ):
        if election_service is None:
            db = PgDB(dsn=POSTGRES_DB_URI)
            rd = RedisDB(url='redis://{host}:{port}'.format(**REDIS_CONFIG))
            storage = S3StorageAdapter(**S3_CONFIG)
            election_service = ElectionService(ElectionRepo(db), rd, storage)

        if msg_broker is None:
            rd = RedisDB(url='redis://{host}:{port}'.format(**REDIS_CONFIG))
            msg_broker = RedisMessageBroker(rd)

        if socket is None:
            socket = AsyncRedisManager(**REDIS_CONFIG)

        if llm_repo is None:
            llm_repo = LLMRepo()


        self.election_service = election_service

        self.socket = socket

        self.llm_repo = llm_repo

        self.mr = msg_broker

        self._tasks: List[asyncio.Task] = []

    async def _get_columns_from_archive(self, columns, name):
        """
        Appelle le LLM pour identifier le mapping des colonnes du tableau.
        Retourne un dict avec :
          - idx             : mapping nom_colonne → index
          - candidate_results_format : 'row' ou 'column'
          - candidate_results        : détail du format candidats
          - confidence_score         : score de confiance du LLM
          - election_type            : 'legislative' ou autre
        En cas d'échec du LLM, tente un mapping forcé heuristique.
        """
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
        response = await self.llm_repo.run(
            "column_detector",
            messages, {}, timeout=60
        )
        if not response["success"]:
            rsp, candidate_results_format, candidate_results = map_columns_force(columns)
            if not all(
                (rsp.get(k) not in (None, -1)) for k in (
                "region", "locality", "polling_stations_count",
                "voters_total", "expressed_votes",
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
                    (rsp.get(k) not in (None, -1)) for k in (
                "region", "locality", "polling_stations_count",
                "voters_total", "expressed_votes",
                )
            ):
                return None
            _f = result["election_metadata"]["format"]
            try:
                real_res = {}
                for k, idx in rsp.items():
                    if idx in (-1, None):
                        continue
                    other = columns[idx]
                    group = []
                    for i, c in enumerate(columns):
                        if c == other:
                            group.append(i)
                        elif len(group):
                            break
                    real_res[k] = group
            except KeyError:
                return None

            return {
                "idx": real_res,
                "candidate_results_format": _f,
                "candidate_results": result["candidate_results"][_f+"_mode"],
                "confidence_score": result["election_metadata"]["confidence_score"],
                "election_type": result["election_metadata"]["type"]
            }

    async def _processing_archive_task(self, sid, election_id):

        election = await self.election_service.get(election_id)
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
                print("on est sur la page:", page_index)
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
                            {"election_name": name},
                            to=sid
                        )

                # place the cursor to the right table and calculate: columns_meta and index_row and table_index
                if columns_meta is None:
                    print("columns_meta est encore none donc on calucl pour voir si la page contient le bon tableau" )
                    async for table_rows_data in _loop(
                        page.extract_tables, table_settings=table_settings
                    ):
                        column, index_row = find_pdf_utils_columns(table_rows_data)
                        print("ce tableau a les colonnes:", column, "sur", index_row, "lignes")
                        if all(not c for c in column):
                            continue
                        if "|".join(column) not in column_cache:
                            column_cache.add("|".join(column))
                        else:
                            continue
                        columns_meta = await self._get_columns_from_archive(
                            column, name
                        )
                        print("le resultat: columns_meta=", columns_meta)
                        if columns_meta is not None:
                            break
                        table_index += 1
                    if columns_meta is None:
                        continue
                print("finalement la page", page_index, "contiens bien le tableau")
                # at this at step we got the right start page for treatment
                candidate_results_format = columns_meta["candidate_results_format"]
                region_idx   = columns_meta["idx"]["region"]
                locality_idx = columns_meta["idx"]["locality"]
                idxs         = columns_meta["idx"]
                candidate_results_idx = columns_meta["candidate_results"]

                # ── Variables pour la détection des frontières par edges ──
                # Calculées une seule fois par page pour ne pas pénaliser la perf.
                region_boundaries   = None   # Y des lignes horizontales de la colonne région
                locality_boundaries = None   # Y des lignes horizontales de la colonne localité

                _current_table_index = 0
                async for table in _loop(page.find_tables, table_settings=table_settings):
                    if _current_table_index < table_index:
                        print("il s'agit ne sagit pas du table")
                        # Sauter les tableaux avant celui identifié lors de la détection des colonnes
                        continue

                    # ── Calculer les frontières une seule fois pour ce tableau/page ──
                    # On récupère les X de la colonne région et localité depuis le tableau
                    region_x0, region_x1 = await _to_async(
                        get_column_x_bounds, table, region_idx
                    )
                    locality_x0, locality_x1 = await _to_async(
                        get_column_x_bounds, table, locality_idx
                    )
                    table_bbox = table.bbox
                    # Calculer les Y des edges horizontaux traversant chaque colonne
                    if region_x0 is not None:
                        region_boundaries = await _to_async(
                            get_boundary_edges, page, region_x0, region_x1, table_bbox
                        )
                    if locality_x0 is not None:
                        locality_boundaries = await _to_async(
                            get_boundary_edges, page, locality_x0, locality_x1, table_bbox
                        )

                    # Réinitialiser le Y de référence au début de chaque page
                    last_row_y = table.bbox[1]

                    table_data = await _to_async(table.extract)

                    index = -1

                    for row in table.rows:
                        index += 1
                        if index < index_row:
                            print("il s'agit du ligne d'entete du tableau")
                            # to don't consider the table header base on index_row calculated a few top
                            last_row_y = row.bbox[3]
                            continue


                        row_content = table_data[index]

                        print("la ligne", index, "du tableau:", row_content)

                        r = (get_row_content_at_idx(row_content, region_idx) or "").strip()
                        r_is_total = (
                                not r or
                                re.search("\b(total|pourcentage|%)\b", str(r), flags=re.I)
                        )
                        if not extracted_locality and r_is_total and last_region is None:
                            print("on a obteu certainement un ligne de total. on skip")
                            continue

                        row_box = row.bbox   # (x0, top, x1, bottom)
                        row_bottom = row_box[3]

                        # ── Détecter un franchissement de frontière RÉGION ──
                        # Si la ligne courante dépasse un edge horizontal de la
                        # colonne région depuis la dernière ligne traitée,
                        # on réinitialise last_region : on sait qu'on a changé
                        # de région mais on ne connaît pas encore son nom.
                        if region_boundaries and has_crossed_boundary(
                            row_box, region_boundaries, last_row_y
                        ):
                            print("la ligne", index, "marque le debut d'une nouvelle region", )
                            last_region = None
                            got_new_locality = True
                        else:
                            got_new_locality = locality_boundaries and has_crossed_boundary(
                            row_box, locality_boundaries, last_row_y
                        )

                        # ── Détecter un franchissement de frontière LOCALITÉ ──
                        # Même logique pour la localité : si on franchit un edge
                        # horizontal de la colonne localité, on sait que la
                        # localité précédente est terminée.
                        if got_new_locality:
                            print("la ligne", index, "marque le debut d'une nouvelle locality", )

                            # Sauvegarder la localité précédente avant de reset
                            if last_locality["value"]:
                                print("on enregistre l'ancien current locality")
                                _bbox = last_locality["cords"].get(page_index)
                                if _bbox and isinstance(_bbox, list):
                                    last_locality["cords"][page_index] = (
                                        min(b[0] for b in _bbox),
                                        min(b[1] for b in _bbox),
                                        max(b[2] for b in _bbox),
                                        max(b[3] for b in _bbox),
                                    )
                                extracted_locality.append(last_locality)
                            last_locality = {
                                "value": None,
                                "cords": {},
                                "stage": {
                                    "region": last_region
                                },
                                "candidates": []
                            }

                        # Mettre à jour le Y de référence après les vérifications
                        last_row_y = row_bottom

                        # ── Traiter la valeur région ──
                        if r:
                            # Corriger le texte inversé (texte rotatif fragmenté)
                            if r.count("\n") > 2:
                                # texte inverse
                                r = r.replace("\n", "")[::-1]

                            # Vérifier si c'est bien un nom de région connu
                            _is_region, rr = await _to_async(is_region, r)
                            if _is_region:
                                print("On a le nom de la region:", rr)
                                last_region = rr
                                # Fill forward : si des lignes précédentes
                                # avaient last_region = None (après un edge),
                                # elles seront naturellement couvertes par
                                # last_region dès maintenant.
                                incre = len(extracted_locality) -1
                                while incre >= 0:
                                    _prev_extracted_locality = extracted_locality[incre]
                                    if _prev_extracted_locality["stage"]["region"] is None:
                                        print("obligation de faire le fillback pour mettre a jour la localite", incre)
                                        _prev_extracted_locality["stage"]["region"] = last_region
                                    else:
                                        break
                                    incre -= 1

                        # ── Traiter la valeur localité ──
                        locality = str(
                            get_row_content_at_idx(row_content, locality_idx) or ""
                        )

                        # Ignorer les lignes de total/pourcentage ou vides
                        if re.search(
                            r"\b(total|pourcentage|%)\b", locality, flags=re.IGNORECASE
                        ) or re.search(r"^\s*\d+[\s\d]*$", locality):
                            print("la ligne", index, " est une ligne de total -> on skip", repr(locality))
                            continue

                        if not locality:
                            if not last_region and not extracted_locality:
                                print("la ligne", index,
                                      " est certaienement une ligne de total -> on skip",
                                      repr(locality))
                                continue
                        # ── Nouvelle localité détectée ──
                        elif locality and locality != last_locality["value"]:
                            print("on vient d'avoir le nom de la current locality:", repr(locality))
                            print("\tprev", last_locality)
                            # Finaliser la localité précédente si elle existe
                            if last_locality["value"] is None:
                                # fill forward
                                last_locality["value"] = locality

                                # TODO: ici
                            else:
                                print("Normalement ce cas ne devrait pas exister vu que via les edgs on a deja traiter le prev et mis a jour le current_locality")
                                _bbox = last_locality["cords"].get(page_index)
                                if _bbox and isinstance(_bbox, list):
                                    last_locality["cords"][page_index] = (
                                        min(b[0] for b in _bbox),
                                        min(b[1] for b in _bbox),
                                        max(b[2] for b in _bbox),
                                        max(b[3] for b in _bbox),
                                    )
                                extracted_locality.append(last_locality)
                                last_locality = {
                                    "value": locality,
                                    "cords": {},
                                    "stage": {"region": last_region},
                                    "candidates": []
                                }

                        for k, i in idxs.items():
                            if k in ("region", "locality") or i in (None, [None], -1, [-1]):
                                continue

                            if last_locality["stage"].get(k) is not None:
                                continue
                            s = get_row_content_at_idx(row_content, i)
                            if not s:
                                continue
                            print("on a trouver a la ligne", index, "[%s]--"% (locality[:10],), k, "==", s)
                            last_locality["stage"][k] = s

                        # Accumuler le bbox de cette ligne dans la localité courante
                        if page_index not in last_locality["cords"]:
                            last_locality["cords"][page_index] = []
                        last_locality["cords"][page_index].append(row_box)

                        # ── Extraire les données candidat ──
                        if candidate_results_format == "row":
                            # Format ligne : un candidat par ligne du tableau
                            cand = {}
                            pty_idx = candidate_results_idx.get("party_idx")

                            if pty_idx is not None and pty_idx != -1:
                                cand["party_ticker"] = get_row_content_at_idx(row_content, pty_idx)

                            name_idx = candidate_results_idx["candidate_name_idx"]
                            # est-ce que ce test est necessaire? dois retirer?
                            if name_idx is not None and name_idx != -1:
                                cand["full_name"] = get_row_content_at_idx(row_content, name_idx)

                            score_idx = candidate_results_idx["score_idx"]
                            # est-ce que ce test est necessaire? dois retirer?
                            if score_idx is not None and score_idx != -1:
                                cand["raw_value"] =get_row_content_at_idx(row_content, score_idx)

                            cand["bbox_json"] = [{page_index: row_box}]
                            print("\t\tajout du candidat:", cand)
                            last_locality["candidates"].append(cand)

                        else:
                            # Format colonne : plusieurs candidats par ligne
                            for c in candidate_results_idx:
                                cand = {
                                    "full_name": c["candidate_name"],
                                    "raw_value": get_row_content_at_idx(row_content, c["score_idx"]),
                                    "bbox_json": [{page_index: row_box}]
                                }
                                if "party_ticker" in c:
                                    cand["party_ticker"] = c["party_ticker"]
                                print("\t\tajout du candidat:", cand)

                                last_locality["candidates"].append(cand)

                    # ── Fin du tableau : finaliser la dernière localité de la page ──
                    if last_locality["value"]:
                        _bbox = last_locality["cords"].get(page_index)
                        if _bbox and isinstance(_bbox, list):
                            last_locality["cords"][page_index] = (
                                min(b[0] for b in _bbox),
                                min(b[1] for b in _bbox),
                                max(b[2] for b in _bbox),
                                max(b[3] for b in _bbox),
                            )
                        extracted_locality.append(last_locality)

                    # On suppose un seul tableau pertinent par page
                    break

            # ── Fin du document : rapport d'erreur si colonnes non détectées ──
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
                    print(locality)

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