import re

from kb_tools.tools import remove_accent_from_text

from src.utils.tools import extract_date_from_text


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
    # TODO: https://www.cei.ci/wp-content/uploads/2020/04/Résultats-du-premier-tour.pdf
    # TODO: pour ce fichier le premier tableau n'est pas le bon pour obtenir ce qu'on veut. peut-etre utiliser un loop.
    size = None
    columns_concat_text = [""]*len(table_list[0])
    for line in table_list:
        if size is not None:
            assert len(line) == size
        else:
            size = len(line)
        if re.search(r"\d", "".join(x for x in line if x)):
            break
        prev = ""
        for i, row in enumerate(line):
            if not row:
                row = prev
            print(row)
            prev = row
            columns_concat_text[i]+=" "+row
    return columns_concat_text
