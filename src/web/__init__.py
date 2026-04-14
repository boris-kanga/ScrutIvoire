import functools

from flask import current_app

from kb_tools.tools import get_buffer

from src.infrastructure.database.pgdb import PgDB



def db_depends(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        func_args = get_buffer(func)
        kw = {}
        if "db" in func_args:
            try:
                db_uri = current_app.config["POSTGRES_DB_URI"]
                pg_db = await PgDB(dsn=db_uri, as_client=True).connect()
                kw["db"] = pg_db
                return await func(*args, **kwargs, **kw)
            finally:
                if "db" in kw:
                    kw["db"].close()

        return await func(*args, **kwargs, **kw)
    return wrapper



