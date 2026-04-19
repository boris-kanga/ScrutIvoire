import asyncio
import io
import json
import re
import traceback
import uuid
from functools import partial
from typing import List, Dict

import pdfplumber

from src.domain.election import LocalityStagingResult
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
    find_pdf_utils_columns, map_columns_force, get_regions, is_region, \
    is_candidate_winner, extract_region_locality_text


def get_row_content_at_idx(row, idx):
    """
    Extrait le contenu d'une ligne à un index donné.
    idx peut être un int ou une liste d'int (colonnes fusionnées).
    Concatène les valeurs non nulles séparées par un espace.
    """
    if isinstance(idx, int):
        idx = [idx]
    res = None
    for i in sorted(idx):
        if i >= 0:
            if row[i] is not None:
                res = ((res or "") + " " + str(row[i])).strip()
    return res


def _first_idx(idx):
    """
    Retourne le premier index d'un idx qui peut être int ou liste.
    Utilisé pour accéder à row.cells[] qui n'accepte qu'un entier.
    """
    if isinstance(idx, list):
        return idx[0]
    return idx


def _consolidate_bbox(cords, page_index):
    """
    Consolide la liste de bboxes d'une page en un seul bbox englobant.
    Modifie cords en place : remplace la liste par un tuple (x0,top,x1,bottom).
    Ne fait rien si la liste est déjà consolidée ou absente.
    """
    _bbox = cords.get(page_index)
    if _bbox and isinstance(_bbox, list):
        cords[page_index] = (
            min(b[0] for b in _bbox),
            min(b[1] for b in _bbox),
            max(b[2] for b in _bbox),
            max(b[3] for b in _bbox),
        )


def get_column_x_bounds(table, col_idx):
    if isinstance(col_idx, list):
        col_idx = col_idx[0]
    for row in table.rows:
        cells = row.cells
        if col_idx < len(cells) and cells[col_idx] is not None:
            cell = cells[col_idx]
            return cell[0], cell[2]  # x0, x1
    return None, None


def get_region_separators(page, region_x0, tol=5):
    """
    Retourne les Y (top) des traits de séparation de région.
    Critères : trait fin (height < 3), commence avant la colonne région,
    traverse au moins 50% de la largeur de la page.
    Utilise page.rects dont les coordonnées top sont fiables (pas de bug de conversion).
    """
    seps = []
    min_width = page.width * 0.5
    for r in page.rects:
        if (
            r['height'] < 3
            and r['x0'] <= region_x0 + tol
            and r['width'] >= min_width
        ):
            seps.append(r['top'])
    seps.sort()
    # Dédupliquer les paires proches (les deux bords d'un trait)
    deduped = []
    for y in seps:
        if not deduped or y - deduped[-1] > 2:
            deduped.append(y)
    return deduped


def get_locality_separators(page, locality_x0, tol=5):
    """
    Retourne les Y (top) des traits de séparation de localité.
    Critères : trait fin (height < 3), commence à la colonne localité (pas avant),
    traverse au moins 30% de la largeur de la page.
    """
    seps = []
    min_width = page.width * 0.3
    for r in page.rects:
        if (
            r['height'] < 3
            and locality_x0 - tol <= r['x0'] <= locality_x0 + tol
            and r['width'] >= min_width
        ):
            seps.append(r['top'])
    seps.sort()
    deduped = []
    for y in seps:
        if not deduped or y - deduped[-1] > 2:
            deduped.append(y)
    return deduped


class Worker:
    def __init__(
            self,
            election_service=None,
            socket=None,
            llm_repo=None,
            msg_broker=None
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
            socket = AsyncRedisManager(
                'redis://{host}:{port}'.format(**REDIS_CONFIG)
            )

        if llm_repo is None:
            llm_repo = LLMRepo()

        self.election_service = election_service
        self.socket           = socket
        self.llm_repo         = llm_repo
        self.mr               = msg_broker
        self._tasks: Dict[str, asyncio.Task] = {}

    async def _get_columns_from_archive(self, columns, name):
        """
        Appelle le LLM pour identifier le mapping des colonnes du tableau.
        Retourne un dict avec :
          - idx                      : mapping nom_colonne → liste d'index
          - candidate_results_format : 'row' ou 'column'
          - candidate_results        : détail du format candidats
          - confidence_score         : score de confiance du LLM
          - election_type            : 'legislative' ou autre
        En cas d'échec du LLM, tente un mapping forcé heuristique.
        """
        messages = self.llm_repo.get_prompt(
            "column_detector",
            user_arg=dict(title=name, columns=columns),
            system_arg=dict(title=name)
        )
        response = await self.llm_repo.run(
            "column_detector",
            messages, {}, timeout=60
        )

        if not response["success"]:
            # Fallback heuristique si le LLM échoue
            rsp, candidate_results_format, candidate_results = map_columns_force(columns)
            if not all(
                (rsp.get(k) not in (None, -1)) for k in (
                    "region", "locality", "polling_stations_count",
                    "voters_total", "expressed_votes",
                )
            ):
                return None
            election_type = "legislative" if "legislative" in str(name) else None
            return {
                "idx":                      rsp,
                "candidate_results_format": candidate_results_format,
                "candidate_results":        candidate_results,
                "confidence_score":         0.5,
                "election_type":            election_type
            }

        result = response["result"]
        rsp    = result["mapping_index"]
        if not all(
            (rsp.get(k) not in (None, -1)) for k in (
                "region", "locality", "polling_stations_count",
                "voters_total", "expressed_votes",
            )
        ):
            return None

        _f = result["election_metadata"]["format"]

        # Regrouper les colonnes fusionnées (même libellé d'en-tête) en
        # listes d'index consécutifs, afin que get_row_content_at_idx
        # puisse concaténer les valeurs de plusieurs colonnes.
        try:
            real_res = {}
            for k, idx in rsp.items():
                if k not in LocalityStagingResult.__annotations__:
                    continue
                if idx in (-1, None):
                    continue
                label = columns[idx]
                group = []
                for i, c in enumerate(columns):
                    if c == label:
                        group.append(i)
                    elif group:
                        break
                real_res[k] = group
        except (KeyError, IndexError):
            return None

        return {
            "idx":                      real_res,
            "candidate_results_format": _f,
            "candidate_results":        result["candidate_results"][_f + "_mode"],
            "confidence_score":         result["election_metadata"]["confidence_score"],
            "election_type":            result["election_metadata"]["type"]
        }

    async def _processing_archive_task(self, sid, election_id):
        print("debut du processing de election id", sid, election_id)
        election = await self.election_service.get(election_id)
        if not election:
            print(election, "election pas trouver")
            return []


        print("going to work for election:", election)
        table_settings = {
            "vertical_strategy":        "lines",
            "horizontal_strategy":      "lines",
            "snap_y_tolerance":         3,
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
                    p = await asyncio.to_thread(next, _iter, None)
                    if p is None:
                        break
                    yield p
                except StopIteration:
                    break

        async def _to_async(func, *args, **kwargs):
            return await asyncio.to_thread(func, *args, **kwargs)

        async def _loop(fn, *args, **kw):
            def _inner():
                for item in fn(*args, **kw):
                    yield item
            _iter = _inner()
            while True:
                try:
                    yield await asyncio.to_thread(next, _iter)
                except StopIteration:
                    break

        async def _crop(p, cord, b=None):
            c    = await _to_async(p.crop, cord)
            _img = await _to_async(c.to_image, resolution=300)
            if b is None:
                b = io.BytesIO()
            await _to_async(_img.save, b, format="PNG")
            return b


        async def extract_region_locality_by_prevent_rotation(_row, _idx, _page):
            return_value = ""
            for i in sorted(_idx):
                _cell = _row.cells[i]
                if _cell is None:
                    pass
                else:
                    _tmp = await _to_async(
                        extract_region_locality_text, _page, _cell
                    )
                    return_value += " " + _tmp
            return return_value.strip()


        doc = election.doc
        print("doc", doc)
        async with doc.get() as filename:

            page1         = None
            columns_meta  = None
            name          = None
            column_cache  = set()
            index_row     = 0
            last_region   = None

            # Structure d'une localité en cours de traitement :
            # - value      : nom de la localité (str ou None)
            # - cords      : {page_index: [(bbox), ...] ou tuple consolidé}
            # - stage      : métadonnées (region, nb_bv, inscrits, votants, ...)
            # - candidates : liste des candidats collectés
            last_locality = {
                "value":      None,
                "cords":      {},
                "stage":      {},
                "candidates": [],
                "winner": None
            }

            page_index         = -1
            extracted_locality = []

            async for page in _async_read_pdf(filename):
                page_index  += 1
                table_index  = 0
                # if page_index == 3:
                #     print("\n\n\n\n\n\n", len(page.rects))
                #     for rect in page.rects:
                #         print(rect)
                #     exit()

                # ── Extraire le nom de l'élection depuis la première page ──
                if page1 is None:
                    page1 = page
                    name  = await asyncio.to_thread(
                        extract_election_name_from_pdf_page_1, page1
                    )
                    if name is not None:
                        await self.socket.emit(
                            "election_processing",
                            {"election_name": name},
                            to=sid
                        )

                # ── Identifier les colonnes (une seule fois, sur la première
                #    page qui contient le bon tableau) ──
                if columns_meta is None:
                    async for table_rows_data in _loop(
                        page.extract_tables, table_settings=table_settings
                    ):
                        column, index_row = find_pdf_utils_columns(table_rows_data)
                        if all(not c for c in column):
                            continue
                        key = "|".join(column)
                        if key in column_cache:
                            continue
                        column_cache.add(key)
                        columns_meta = await self._get_columns_from_archive(column, name)
                        if columns_meta is not None:
                            break
                        table_index += 1
                    if columns_meta is None:
                        continue

                # ── Index des colonnes utiles ──
                candidate_results_format = columns_meta["candidate_results_format"]
                region_idx            = columns_meta["idx"]["region"]
                locality_idx          = columns_meta["idx"]["locality"]
                idxs                  = columns_meta["idx"]
                candidate_results_idx = columns_meta["candidate_results"]

                # Premier index entier pour accéder à row.cells[]
                region_cell_idx   = _first_idx(region_idx)
                locality_cell_idx = _first_idx(locality_idx)

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
                    # Calculer les Y des edges horizontaux traversant chaque colonne
                    # REMPLACER les appels à get_boundary_edges par :
                    if region_x0 is not None:
                        region_separators = await _to_async(
                            get_region_separators, page, region_x0
                        )
                    if locality_x0 is not None:
                        locality_separators = await _to_async(
                            get_locality_separators, page, locality_x0
                        )

                    # Réinitialiser le Y de référence au début de chaque page
                    last_row_y = table.bbox[1]

                    table_data = await _to_async(table.extract)

                    index = -1

                    place_row_init_y = False
                    col_x_bounds = {}  # {idx: (x0, x1)}
                    for row in table.rows:
                        index += 1
                        for idx, cell in enumerate(row.cells):
                            if cell is not None and idx not in col_x_bounds:
                                col_x_bounds[idx] = (cell[0], cell[2])

                        print(f"[{page_index+1}page - line {index}]", table_data[index])

                        # ── Sauter les lignes d'en-tête ──
                        if index < index_row:
                            print("il s'agit du ligne d'entete du tableau")
                            # to don't consider the table header base on index_row calculated a few top
                            last_row_y = row.bbox[1]
                            continue

                        if not place_row_init_y:
                            last_row_y = row.bbox[1]
                            place_row_init_y = True

                        row_content = table_data[index]
                        row_box     = row.bbox  # (x0, top, x1, bottom)

                        # ── Cellules physiques ──
                        # row.cells[i] non-None → nouvelle cellule physique sur
                        #   cette ligne (début d'une cellule fusionnée ou cellule
                        #   ordinaire).
                        # row.cells[i] None     → continuation d'une cellule
                        #   fusionnée commencée sur une ligne précédente.
                        cell_region = (
                            row.cells[region_cell_idx]
                            if region_cell_idx < len(row.cells) else None
                        )
                        cell_locality = (
                            row.cells[locality_cell_idx]
                            if locality_cell_idx < len(row.cells) else None
                        )

                        region_raw = await extract_region_locality_by_prevent_rotation(
                            row, region_idx, page
                        )
                        locality_raw = await extract_region_locality_by_prevent_rotation(
                            row,  locality_idx, page
                        )

                        # ── Skip : ligne de total sur région ──
                        # Les totaux de région (ligne globale) doivent être ignorés
                        # partout dans le document.
                        if region_raw and re.search(
                            r"\b(total|pourcentage|%)\b", region_raw, flags=re.IGNORECASE
                        ):
                            print("\tline total skip")
                            continue

                        # ── Skip : ligne de total sur localité ──
                        # Lignes de sous-total par localité ou lignes purement
                        # numériques (ex: numéro de page parasite).
                        if locality_raw and (
                            re.search(
                                r"\b(total|pourcentage|%)\b",
                                locality_raw, flags=re.IGNORECASE
                            )
                            or re.search(r"^\s*\d+[\s\d]*$", locality_raw)
                        ):
                            print("line total skip locality")
                            continue

                        # Détecter changement de région via les séparateurs de page.rects
                        # Un séparateur entre last_row_y et row_box[1] = nouvelle région
                        region_sep_crossed = any(
                            last_row_y < sep <= row_box[1] + 2
                            for sep in region_separators
                        )

                        # Détecter changement de localité via les séparateurs
                        locality_sep_crossed = any(
                            last_row_y < sep <= row_box[1] + 2
                            for sep in locality_separators
                        )

                        # Mise à jour du curseur Y
                        last_row_y = row_box[1]

                        if region_sep_crossed:
                            # Nouvelle région — fermer la localité courante
                            print("Nouvelle region avec region_sep_crossed")
                            if last_locality["value"] is not None:
                                _consolidate_bbox(last_locality["cords"],
                                                  page_index)
                                extracted_locality.append(last_locality)
                            last_locality = {
                                "value": None,
                                "cords": {},
                                "stage": {"region": None},
                                "candidates": [],
                                "winner": None
                            }
                            last_region = None

                        elif locality_sep_crossed:
                            print("Nouvelle locality avec locality_sep_crossed")
                            # Nouvelle localité — sera confirmée quand locality_raw sera non vide
                            if last_locality["value"] is not None:
                                _consolidate_bbox(last_locality["cords"],
                                                  page_index)
                                extracted_locality.append(last_locality)
                            last_locality = {
                                "value": None,
                                "cords": {},
                                "stage": {"region": last_region},
                                "candidates": [],
                                "winner": None
                            }
                        # ── Skip : aucun contexte actif du tout ──
                        # Lignes de total global en tout début de tableau, avant
                        # que la première vraie région/localité soit apparue.
                        # if (
                        #     not last_region
                        #     and not last_locality["value"]
                        #     and not extracted_locality
                        # ):
                        #     print("on skip car on n'a pas de contexte")
                        #     continue

                        # ── Traiter le changement de RÉGION ──
                        # cell_region non-None + r non vide → vraie nouvelle région.
                        #   → implique forcément une nouvelle localité.
                        # cell_region non-None + r vide     → saut de page, la région
                        #   continue depuis la page précédente : on garde last_region.
                        if cell_region is not None and region_raw:
                            print("On est sur une nouvelle zone de region")
                            _is_region, rr = await _to_async(is_region, region_raw)
                            if _is_region:

                                # Nouvelle région → forcément nouvelle localité :
                                # fermer la localité courante si elle a une valeur.
                                if last_region is not None and last_region != rr:
                                    print("On est sur une nouvelle zone de region\n\tRegion=", rr)
                                    if last_locality["value"] is not None:
                                        print("on ferme la locality:", repr(last_locality["value"][:10]), "...")
                                        _consolidate_bbox(last_locality["cords"], page_index)
                                        extracted_locality.append(last_locality)

                                    # Réinitialiser last_locality en attente du nom
                                    print("on est sur une nouvelle locality ")
                                    last_locality = {
                                        "value":      None,
                                        "cords":      {},
                                        "stage":      {"region": rr},
                                        "candidates": [],
                                        "winner":     None
                                    }
                                else:
                                    if last_region != rr:
                                        print(
                                            "On vient de trouver le nom de "
                                            "current Region-->", rr
                                        )
                                        last_locality["stage"]["region"] = rr

                                last_region = rr

                                # Fill back : propager last_region aux localités
                                # extraites dont la région était encore None
                                # (localité traitée avant que son nom de région
                                # soit apparu dans le flux).
                                i = len(extracted_locality) - 1
                                while i >= 0:
                                    prev = extracted_locality[i]
                                    if prev["stage"].get("region") is None:
                                        prev["stage"]["region"] = last_region
                                    else:
                                        break
                                    i -= 1

                        # ── Traiter le changement de LOCALITÉ ──
                        #
                        # cell_locality non-None = signal de nouvelle cellule
                        # physique localité. Trois sous-cas :
                        #
                        # 1. locality_raw vide :
                        #    Fin de la localité précédente qui déborde sur une
                        #    ligne supplémentaire (cas ligne 11 page 2). On ne
                        #    fait rien — on attend la prochaine ligne avec un
                        #    vrai contenu.
                        #
                        # 2. locality_raw non vide + last_locality["value"] None :
                        #    Fill forward — on vient de créer last_locality sans
                        #    valeur (après un changement de région ou saut de page).
                        #    On renseigne juste la valeur sans toucher aux cords
                        #    ni aux candidates déjà accumulés.
                        #
                        # 3. locality_raw non vide + last_locality["value"] non None
                        #    + différent :
                        #    Vraie nouvelle localité — fermer la précédente,
                        #    ouvrir une nouvelle.
                        #
                        # 4. locality_raw == last_locality["value"] :
                        #    Même localité (ex: saut de page avec répétition du
                        #    nom) — rien à faire.
                        if cell_locality is not None and locality_raw:
                            if last_locality["value"] is None:
                                print("\ton vient de trouver le nom de la localite=", repr(locality_raw[:20]), "...")

                                # Cas 2 : fill forward
                                last_locality["value"] = locality_raw
                                last_locality["stage"]["region"] = last_region
                            elif locality_raw != last_locality["value"]:
                                # Cas 3 : vraie nouvelle localité
                                print("on ferme la locality:",
                                      repr(last_locality["value"][:10]), "...")
                                _consolidate_bbox(last_locality["cords"], page_index)
                                extracted_locality.append(last_locality)
                                print("on est sur une nouvelle locality", repr(locality_raw[:10]), "...")
                                last_locality = {
                                    "value":      locality_raw,
                                    "cords":      {page_index: []},
                                    "stage":      {"region": last_region},
                                    "candidates": [],
                                    "winner":     None
                                }
                            # Cas 4 (locality_raw == last_locality["value"]) :
                            # même localité, rien à faire.

                        # ── Remplir les métadonnées de la localité ──
                        # Premier passage uniquement (stage.get(k) is None).
                        # Les lignes candidats suivantes ne doivent pas écraser
                        # les valeurs déjà renseignées.
                        for k, i in idxs.items():
                            if k in ("region", "locality"):
                                continue
                            if i in (None, [None], -1, [-1]):
                                continue
                            if last_locality["stage"].get(k) is not None:
                                continue
                            s = get_row_content_at_idx(row_content, i)
                            if not s:
                                continue
                            print("\t", repr(k), "-->", s)
                            last_locality["stage"][k] = s

                        # ── Accumuler le bbox de cette ligne ──
                        if page_index not in last_locality["cords"]:
                            last_locality["cords"][page_index] = []
                        last_locality["cords"][page_index].append(row_box)

                        # ── Extraire les données candidat ──
                        if candidate_results_format == "row":
                            # Un candidat par ligne du tableau
                            cand = {}

                            pty_idx = candidate_results_idx.get("party_idx")
                            if pty_idx is not None and pty_idx != -1:
                                cand["party_ticker"] = get_row_content_at_idx(
                                    row_content, pty_idx
                                )

                            name_idx = candidate_results_idx.get("candidate_name_idx")
                            if name_idx is not None and name_idx != -1:
                                cand["full_name"] = get_row_content_at_idx(
                                    row_content, name_idx
                                )

                            score_idx = candidate_results_idx.get("score_idx")
                            if score_idx is not None and score_idx != -1:
                                cand["raw_value"] = get_row_content_at_idx(
                                    row_content, score_idx
                                )

                            cand["bbox_json"] = [{page_index: row_box}]
                            print("\t\tajout du candidat:", str(cand)[:30])
                            last_locality["candidates"].append(cand)
                            status_idx = candidate_results_idx.get("status_idx")
                            if status_idx not in (-1, None):
                                cand["winner"] = is_candidate_winner(
                                    get_row_content_at_idx(
                                        row_content, status_idx
                                    )
                                )
                                if cand["winner"]:
                                    last_locality["winner"] = cand

                        else:
                            # Plusieurs candidats par ligne (format colonne)
                            for c in candidate_results_idx:
                                cand = {
                                    "full_name": c["candidate_name"],
                                    "raw_value": get_row_content_at_idx(
                                        row_content, c["score_idx"]
                                    ),
                                    "bbox_json": [{page_index: row_box}]
                                }
                                if "party_ticker" in c:
                                    cand["party_ticker"] = c["party_ticker"]
                                print("\t\tajout du candidat:", str(cand)[:30])

                                last_locality["candidates"].append(cand)

                    if table_data:
                        # voir sl'il ya des donnee residuel [EDAN page 20 example]
                        last_row_bottom = table.rows[-1].bbox[3]
                        table_bottom = table.bbox[3]

                        if table_bottom - last_row_bottom > 5:
                            locality_seps_above = [
                                r['top'] for r in page.rects
                                if r['height'] < 3
                                   and locality_x0 - 5 <= r[
                                       'x0'] <= locality_x0 + 5
                                   and r['width'] > page.width * 0.3
                                   and r['top'] < last_row_bottom
                            ]
                            crop_top = max(
                                locality_seps_above
                            ) if locality_seps_above else last_row_bottom

                            residual_row = []
                            for idx in range(len(table.rows[0].cells)):
                                bounds = col_x_bounds.get(idx)
                                if bounds is None:
                                    residual_row.append(None)
                                    continue
                                col_x0, col_x1 = bounds
                                text = (
                                        page.within_bbox(
                                            (col_x0, crop_top, col_x1,
                                             table_bottom))
                                        .extract_text() or ""
                                ).replace("\n", " ").strip()
                                residual_row.append(text if text else None)

                            print(f"[{page_index + 1}page - line[residuel] {index+1}]",
                                  table_data[index])

                    # ── Fin de page : consolider le bbox de cette page ──
                    # La localité peut continuer sur la page suivante.
                    # On ne ferme PAS last_locality et on ne touche PAS
                    # aux candidates — on consolide uniquement les cords.
                    _consolidate_bbox(last_locality["cords"], page_index)

                    # Un seul tableau pertinent par page
                    break

            # ── Fin du document : fermer la dernière localité en cours ──
            if last_locality["value"]:
                _consolidate_bbox(last_locality["cords"], page_index)
                extracted_locality.append(last_locality)

            # ── Émettre une erreur si les colonnes n'ont pas été identifiées ──
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
                # Traitement final des localités extraites
                with open("tmp.json", "w", encoding="utf-8") as f:
                    f.write(json.dumps(extracted_locality))
                await self.election_service.add_extracted_archive_data(
                    extracted_locality, election
                )
        return extracted_locality

    async def archive_processing(self):
        async for message in self.mr.subscribe(
            MessageBrokerChannel.PROCESSING_ELECTION_RAPPORT
        ):

            print("on vient de recevoir un messqge")
            data        = message["data"]
            sid         = data["sid"]
            election_id = data["election_id"]
            task = asyncio.create_task(
                    self._processing_archive_task(sid, election_id)
                )
            _id = uuid.uuid4()
            self._tasks[str(_id)] = task
            print("la tache est tague avec id=", _id)

            task.add_done_callback(partial(self.task_callback, _id=_id))
            await asyncio.sleep(0)

    def task_callback(self, task, _id):
        try:
            task.result()
        except:
            print("exception caught --> task", _id)
            traceback.print_exc()
        finally:
            self._tasks.pop(str(_id), None)

    async def run(self):
        print("Start process")
        await asyncio.gather(
            self.archive_processing(),
        )