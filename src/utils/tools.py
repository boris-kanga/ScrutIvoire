import re
from datetime import datetime, date
from kb_tools.tools import remove_accent_from_text



def extract_date_from_text(text):
    text = remove_accent_from_text(text)
    f_month = (
        "janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout",
        "septembre", "octobre", "novembre", "decembre"
    )
    abr_month = (
        "janv?", "fev", "mar", "avr", "mai", "juin", "juil", "aout", "sept", "oct",
        "nov", "dec"
    )

    m = "|".join(f_month)

    res = re.search(r"(\d+)\s+("+m+")\s+(\d{4})", text, flags=re.IGNORECASE)
    if res is not None:
        d, m, y = res.groups()
        return date(int(y), f_month.index(m.lower()) + 1, int(d))

    m = "|".join(abr_month)
    res = re.search(r"(\d+)\s+("+m+")\s+(\d{4})", text, flags=re.IGNORECASE)
    if res is not None:
        d, m, y = res.groups()
        return date(int(y), f_month.index(m.lower()) + 1, int(d))
    return None
