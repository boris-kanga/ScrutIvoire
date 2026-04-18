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
    return [c.strip() for c in columns_concat_text], index_row


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





