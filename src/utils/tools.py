import sys

import contextlib
import importlib.util
import re
from datetime import datetime, date
from kb_tools.tools import remove_accent_from_text, format_var_name



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



@contextlib.contextmanager
def load_module(module, package=None):
    if format_var_name(module, permit_char=".") != module:
        # no valide module name
        spec = importlib.util.spec_from_file_location(format_var_name(module), module)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    else:
        m = importlib.import_module(module, package)
    yield m
    name = m.__name__
    if name in globals():
        globals().pop(name)
    if name in locals():
        locals().pop(name)
    if name in sys.modules:
        sys.modules.pop(name)
    del m
