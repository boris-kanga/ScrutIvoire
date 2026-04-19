import os.path
import re

from thefuzz import process


from kb_tools.tools import remove_accent_from_text, generate_candidate

from src.core.config import WORK_DIR
from src.utils.tools import extract_date_from_text, cache


def extract_election_name_from_pdf_page_1(page1):
    lines = page1.extract_text().split("\n")[:2]
    name = None
    if len(lines) == 2:
        # first line must be the name
        # line 2 must contains the period
        name = remove_accent_from_text(lines[0])
        if "election" not in name.lower():
            name = None
        else:
            period = extract_date_from_text(lines[1])
            if period is not None:
                name += " | " + period.strftime("%d %B %Y")
        name = name.upper()
    return name

def find_pdf_utils_columns(table_list):
    size = None
    columns_concat_text = [""]*len(table_list[0])
    index_row = None
    for index_row, line in enumerate(table_list):
        if size is not None:
            assert len(line) == size
        else:
            size = len(line)
        if re.search(r"\d", "".join(x for x in line if x)):
            break
        prev = ""
        for i, row in enumerate(line):
            if not row:
                row = ""
                if i < len(line) - 1:
                    row = prev
            if i == 0:
                row = re.sub(r"regi\b", "REGION", row, flags=re.IGNORECASE)

            prev = row = re.sub(r"(?<!\w\w)\s+", "", row)
            columns_concat_text[i]+=" "+row
    res = [c.strip() for c in columns_concat_text]
    if res[-1] == "":
        res[-1] = "Résultat"
    return res, index_row


def map_columns_force(columns):
    mappings = {
        "region"                  : generate_candidate("%region%", "%district%"),
        "locality"                : generate_candidate(
            "%local%",
            "%circonscription%",
            "%commune%",
        ),
        "polling_stations_count"  : generate_candidate("%NB%BV%", "%bureau%vote%", "%n%b%b%v%"),
        "on_call_staff": generate_candidate("%pers%ASTREINT%"),

        "pop_size_male": generate_candidate("%pop%elect%hom%"),
        "pop_size_female": generate_candidate("%pop%elect%fem%"),
        "pop_size": generate_candidate("%pop%elect%"),

        "registered_voters_male": generate_candidate("%inscri%hom%"),
        "registered_voters_female": generate_candidate("%inscri%fem%"),
        "registered_voters_total": generate_candidate("%inscri%"),

        "voters_male": generate_candidate("%vot%homme%"),
        "voters_female": generate_candidate("%vot%femme%"),
        "voters_total": generate_candidate("%vot%"),

        "participation_rate": generate_candidate(
            re.compile(r".*t.*\bpart.*", flags=re.I | re.S)),

        "null_ballots": generate_candidate(
            re.compile(r".*\bnuls?\b.*", flags=re.I | re.S)),

        "expressed_votes": generate_candidate("%suff%exprim%", "%exprim%"),
        "blank_ballots_pct": generate_candidate(
            re.compile(r"^.*blanc.*(%|perc).*(blanc)?$", flags=re.I | re.S)
        ),
        "blank_ballots_count": generate_candidate("%blanc%"),
        "unregistered_voters_count": generate_candidate("%vo+t%no+n%inscri%")
    }
    res = {
        k: None
        for k in mappings.keys()
    }

    def best(i_, col):
        for k, cand in mappings.items():
            l = cand.last_index
            if cand == col:
                if l > cand.last_index:
                    if res[k]:
                        best(res[k], columns[res[k]])
                        pass
                    res[k] = i_
                    break

    for i, c in enumerate(columns):
        best(i, c)

    other_index = max(v for v in res.values() if v) + 1
    other_columns = columns[other_index:]
    print(other_columns)
    candidate_results_format = "column"
    candidate_results = None
    if re.search(r"(group|part)", " ".join(other_columns), flags=re.I):
        print("row")
        candidate_results_format = "row"

        # TODO: parse column for case each line is about an candidate
    else:
        # TODO: each other column is about candidate
        pass
    return res, candidate_results_format, candidate_results


@cache(60)
def get_regions():
    # TODO: pour les dates anterieurs a sept 2011, considerer le changement de systeme de 19 a 31
    with open(os.path.join(WORK_DIR, "data", "region_district.txt")) as fp:
        return list(filter(None, [x.strip().upper() for x in fp.readlines()]))


def is_region(r):
    regions = get_regions()
    rr, prob = process.extractOne(r, regions)
    if prob >= 95:
        return True, rr
    return False, None


def is_candidate_winner(status):
    if not status:
        return False
    return generate_candidate("%elu%", "%vain%") == status



def extract_region_locality_text(page, bbox):
    area = page.within_bbox(bbox)
    chars = area.chars
    if not chars:
        return ""

    # Détecter si texte rotatif : matrix[0] ≈ 0
    rotated = [c for c in chars if abs(c['matrix'][0]) < 0.1]
    normal  = [c for c in chars if abs(c['matrix'][0]) > 0.5]

    if not rotated or normal:
        # Texte normal
        return (area.extract_text() or "").replace("\n", " ").strip()

    # Rotation antihoraire (matrix[1] > 0) : chars de bas en haut
    # → trier par top décroissant et concaténer directement
    if rotated[0]['matrix'][1] > 0:
        rotated.sort(key=lambda c: c['top'], reverse=True)
        return "".join(c['text'] for c in rotated).strip()

    # Rotation horaire (matrix[1] < 0) : chars de haut en bas
    # → trier par top croissant
    rotated.sort(key=lambda c: c['top'])
    return "".join(c['text'] for c in rotated).strip()


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
