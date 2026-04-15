import functools

from flask import current_app

from kb_tools.tools import get_func_args

from src.infrastructure.database.pgdb import PgDB
from src.infrastructure.database.redisdb import RedisDB


def db_depends(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        func_args = get_func_args(func)
        kw = {}
        try:
            if "db" in func_args:
                db_uri = current_app.config["POSTGRES_DB_URI"]
                pg_db = await PgDB(dsn=db_uri, as_client=True).connect()
                kw["db"] = pg_db
            if "rd" in func_args:
                redis_uri = current_app.config.get("REDIS_DB_URI")
                rd_kw = {}
                if redis_uri:
                    rd_kw["uri"] = redis_uri
                redis_db = RedisDB(**rd_kw)
                await redis_db.connect()
                kw["rd"] = redis_db
            return await func(*args, **kwargs, **kw)
        finally:
            if "db" in kw:
                await kw["db"].close()
            if "rd" in kw:
                await kw["rd"].disconnect()

    return wrapper



