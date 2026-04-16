import functools
import os

from flask import current_app
from flask_jwt_extended import verify_jwt_in_request

from kb_tools.tools import get_func_args

from src.infrastructure.database.pgdb import PgDB
from src.infrastructure.database.redisdb import RedisDB
from src.infrastructure.file_storage import FileStorageProtocol
from src.infrastructure.file_storage.local import LocalStorageAdapter
from src.core.config import WORK_DIR
from src.infrastructure.file_storage.s3 import S3StorageAdapter


def get_file_storage(config: dict) -> FileStorageProtocol:
    if any("S3_CONFIG" in k for k in config):
        # s3
        return S3StorageAdapter(**config["S3_CONFIG"])
    else:
        return LocalStorageAdapter(
            config.get(
                "UPLOAD_FOLDER",
                    os.path.join(WORK_DIR, "data", "tmp")
                )
        )


def async_jwt_required(f):
    @functools.wraps(f)
    async def decorated_function(*args, **kwargs):
        verify_jwt_in_request()
        return await f(*args, **kwargs)
    return decorated_function

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
            if "storage" in func_args:
                kw["storage"] = get_file_storage(current_app.config)
            return await func(*args, **kwargs, **kw)
        finally:
            if "db" in kw:
                await kw["db"].close()
            if "rd" in kw:
                await kw["rd"].disconnect()

    return wrapper



