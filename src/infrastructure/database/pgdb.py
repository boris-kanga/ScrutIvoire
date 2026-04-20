from __future__ import annotations

import asyncio
import contextlib
import os.path
import queue
from typing import Union, Dict, Optional

import asyncpg
import sqlparse
from kb_tools.tools import get_buffer

from src.core.config import WORK_DIR

# for disabled sqlparse parsing limit
sqlparse.engine.grouping.MAX_GROUPING_TOKENS = None


_CONN = Optional[asyncpg.connection.Connection]

MAX_PARAMETERS_NUMBER = 32767


class PgDB:

    _instance: Dict[str, asyncpg.pool.Pool] = {}
    def __init__(self, *, as_client=False, dsn=None, host=None, user=None, password=None, database=None, port=5432, schema:str=None):
        self._host = host
        self._port = port
        self.database = database
        self._user = user
        self._password = password
        self._dsn = dsn

        self.as_client = as_client

        self._pool: Union[asyncpg.pool.Pool, None] = None

        self._pool_lock: Optional[asyncio.Lock] = None

        if schema is None:
            with open(os.path.join(WORK_DIR, "sql","schema.sql")) as f:
                schema = f.read()

        self._init_db_query = queue.Queue()
        self._need_init = False

        if isinstance(schema, str):
            self.set_init_db_query(schema)

    def set_init_db_query(self, query: str):
        self._init_db_query.put(query)
        self._need_init = True

    @staticmethod
    def _is_select_query(query: str) -> bool:
        """Analyse le SQL pour déterminer si c'est un SELECT."""
        parsed = sqlparse.parse(query)
        if not parsed:
            return False
        # Récupère le type de la première instruction
        if len(parsed) > 1:
            return False
        return parsed[0].get_type() == "SELECT"

    async def connect(self):
        _p = str(self._dsn or (self._host, self._port, self.database))
        _create = self.as_client

        if not self.as_client:
            if PgDB._instance.get(_p) is None:
                _create = True
            elif PgDB._instance[_p].is_closing():
                _create = True
            else:
                self._pool = PgDB._instance[_p]

        if self._pool_lock is None:
            self._pool_lock = asyncio.Lock()
        if _create:
            async with self._pool_lock:
                if self._pool is None:
                    self._pool = \
                        await asyncpg.create_pool(
                        dsn=self._dsn,
                        user=self._user,
                        host=self._host,
                        port=self._port,
                        password=self._password,
                        database=self.database,
                        min_size=2,  # Nombre de connexions toujours prêtes
                        max_size=10,  # Limite pour ne pas saturer ton Postgres
                        max_queries=1000,
                        # Tue et remplace la connexion après 1000 requêtes (évite les fuites de mémoire)
                        max_inactive_connection_lifetime=300
                    )


        if not self.as_client:
            PgDB._instance[_p] = self._pool
            async with self._pool_lock:
                while self._need_init:
                    if self._init_db_query.empty():
                        break
                    q = self._init_db_query.get()
                    await self._pool.execute(
                        q
                    )
                self._need_init = False
        return self

    @contextlib.asynccontextmanager
    async def multiple_query(self):
        await self._reconnect()
        tx = None
        conn: _CONN = None
        try:
            conn = await self._pool.acquire()
            tx = conn.transaction()
            await tx.start()
            yield conn
        except:
            if conn is not None:
                if tx is not None:
                    await tx.rollback()
            raise
        else:
            await tx.commit()
        finally:
            if conn:
                await self._pool.release(conn)


    async def close(self):
        if self._pool:
            await self._pool.close()

    async def _reconnect(self):
        if self._pool is None or self._pool.is_closing() or self._need_init:
            await self.connect()

    async def run_query(
            self,
            query,
            params: Union[tuple, list]=(),
            use_cursor: bool = False,
            limit=float("inf"),
            conn: _CONN = None,
    ):
        await self._reconnect()
        need_to_close = False
        try:
            if conn is None:
                need_to_close = True
                conn = await self._pool.acquire()
            if self._is_select_query(query):
                if use_cursor or limit != float("inf"):
                    results = []
                    i = 0
                    async with conn.transaction():
                        async for record in conn.cursor(query, *params):
                            if i < limit:
                                results.append(dict(record))
                            else:
                                break
                            i += 1
                    return results
                else:
                    results = await conn.fetch(query, *params)
                    return [dict(r) for r in results]
            else:
                return await conn.execute(query, *params)

        finally:
            if need_to_close:
                await conn.close()

    async def insert_many(
            self, data: list[dict],
            table_name: str,
            *,
            id_field=None,
            on_conflict_statement=None

    ) -> Union[list[int], None]:

        assert not all([id_field, on_conflict_statement]), "returning id and on_conflict was not implemented"
        if not data:
            return None if id_field is None else []
        columns = {k for l in data for k in l.keys()}
        columns = list(columns)
        data = [
            tuple(d.get(k) for k in columns)
            for d in data
        ]
        if id_field is None:
            async with self._pool.acquire() as conn:
                sql = f"""
                        INSERT INTO {table_name}({",".join(columns)})
                        VALUES ({",".join(f"${i + 1}" for i in range(len(columns)))})
                        {on_conflict_statement or ""}
                        
                    """
                await conn.executemany(sql, data)
                return None

        sql = f"""
            INSERT INTO {table_name}({",".join(columns)})
            VALUES %s
            RETURNING {id_field}
        """
        k, k_1 = len(columns), len(columns) -1
        ids = []
        max_buffer = int(MAX_PARAMETERS_NUMBER/len(columns))
        async with self.multiple_query() as conn:
            for _, buffer in get_buffer(data, max_buffer=max_buffer):
                if not buffer:
                    continue
                buffer = [
                    x for b in buffer for x in b
                ]
                placeholder = ",".join([
                    f"(${i + 1}" + (")" if k==1 else "") if i % k == 0 else
                    (f"${i + 1})" if i % k == k_1 else f"${i + 1}")
                    for i in range(len(buffer))
                ])

                results = await conn.fetch(
                    sql % placeholder, *tuple(buffer)
                )
                ids+=[dict(r) for r in results]
        return [id_[id_field] for id_ in ids]

    async def bulk_insert(
            self,
            data: list[dict],
            table_name: str,
            chunk_size=50_000,
            conn: _CONN = None
    ):
        if len(data) == 0:
            return "COPY 0"
        await self._reconnect()

        columns = {k for l in data[:chunk_size or len(data)] for k in l.keys()}
        columns = list(columns)
        data = [
            tuple(d.get(k) for k in columns)
            for d in data
        ]
        need_to_close = False
        if conn is None:
            need_to_close = True
            conn = await self._pool.acquire()
        try:
            total = 0
            for _, buffer in get_buffer(data, max_buffer=chunk_size):
                if not buffer:
                    continue
                await conn.copy_records_to_table(
                    table_name, columns=list(columns), records=buffer
                )
                total += len(buffer)
            return f"COPY {total}"
        finally:
            if need_to_close:
                await conn.close()


    async def insert(
            self, row: dict,
            table_name, id_field: str=None, conn: _CONN = None):
        await self._reconnect()
        need_to_close = False
        if conn is None:
            need_to_close = True
            conn = await self._pool.acquire()

        values = tuple(row.values())
        query = (
            f"INSERT INTO {table_name} ({','.join(row.keys())}) "
            f"VALUES "
            f"({','.join('$'+str(i+1) for i,_ in enumerate(values))}) "
            + (f"RETURNING {id_field}" if id_field else "")
        )

        try:
            generated_id = await conn.fetchval(query, *values)
            return generated_id
        finally:
            if need_to_close:
                await conn.close()

