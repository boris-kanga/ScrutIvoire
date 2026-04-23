import sys

import contextlib
import importlib.util
import re
import time
from datetime import datetime, date
from functools import wraps

from kb_tools.tools import remove_accent_from_text, format_var_name
import hashlib
import aiofiles




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

    res = re.search(r"(\d+)\s+("+m+r")\s+(\d{4})", text, flags=re.IGNORECASE)
    if res is not None:
        d, m, y = res.groups()
        return date(int(y), f_month.index(m.lower()) + 1, int(d))

    m = "|".join(abr_month)
    res = re.search(r"(\d+)\s+("+m+r")\s+(\d{4})", text, flags=re.IGNORECASE)
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


async def calculer_hash(chemin_fichier, algorithme="sha256"):
    h = hashlib.new(algorithme)
    async with aiofiles.open(chemin_fichier, mode='rb') as f:
        while True:
            chunk = await f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


__cache = {}
def cache(timeout_minutes=5):
    def wrapper(func):
        @wraps(func)
        def inner(*args, **kwargs):
            c_t = time.time()
            got = True

            if func.__name__ in __cache:
                v, t = __cache[func.__name__]
                if c_t - t > timeout_minutes*60:
                    got = False
            else:
                got = False
            if not got:
                try:
                    v = func(*args, **kwargs)
                    __cache[func.__name__] = v, c_t
                except Exception:
                    if func.__name__ in __cache:
                        return __cache[func.__name__][0]
                    else:
                        raise
            return __cache[func.__name__][0]
        return inner
    return wrapper


def value_parser(parser_func, value, *args, **kwargs):
    try:
        return parser_func(value)
    except Exception:
        if args:
            return args[0]
        if "default" in kwargs:
            return kwargs["default"]
        raise