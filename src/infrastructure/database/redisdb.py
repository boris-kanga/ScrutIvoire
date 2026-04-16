import json

from datetime import datetime, date
from typing import Any, Optional

import redis.asyncio as redis
from redis.asyncio.client import PubSub



class RedisDB:
    def __init__(self,
        url:            str   = "redis://localhost:6379",
        decode_responses: bool = True,
        max_connections: int  = 10,
        host=None,
        port=6379
    ):
        if host is not None:
            url = f"redis://{host}:{port}"
        self._url             = url
        self._decode          = decode_responses
        self._max_connections = max_connections
        self._pool:   Optional[redis.ConnectionPool] = None
        self._conn:   Optional[redis.Redis]          = None
        self._pubsub: Optional[PubSub]               = None
        self.is_connected = False

    async def connect(self, force=False):
        if not force and self._conn is not None:
            return
        if self._conn is not None:
            try:
                await self._conn.ping()
                return
            except redis.ConnectionError:
                await self.disconnect()
        self._pool = redis.ConnectionPool.from_url(
            self._url,
            decode_responses = self._decode,
            max_connections  = self._max_connections,
        )
        self._conn = redis.Redis(connection_pool=self._pool)
        # Vérifier la connexion
        await self._conn.ping()
        self.is_connected = True
        print(f"Redis connecté : {self._url}")

    async def get_conn(self) -> redis.Redis:
        await self.connect()
        return self._conn

    async def disconnect(self):
        if self._pubsub:
            try:
                await self._pubsub.unsubscribe()
                await self._pubsub.aclose()
            except redis.RedisError:
                pass
            finally:
                self._pubsub = None
        if self._conn:
            try:
                await self._conn.aclose()
            except redis.RedisError:
                pass
            finally:
                self._conn = None
        if self._pool:
            try:
                await self._pool.aclose()
            except redis.RedisError:
                pass
            finally:
                self._pool = None

    async def get(self, key: str, as_raw=False) -> Optional[Any]:
        """
        Récupère une valeur et la désérialise depuis JSON.
        Retourne None si la clé n'existe pas.
        """
        await self.connect()
        raw = await self._conn.get(key)
        if as_raw:
            return raw
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw  # retourner tel quel si pas du JSON

    async def set(
        self,
        key:     str,
        value:   Any,
        ttl_sec: Optional[int] = None,
    ) -> bool:
        """
        Sérialise en JSON et stocke.
        ttl_sec : durée de vie en secondes (None = pas d'expiration)
        """
        serialized = self.serialize(value)
        await self.connect()

        if ttl_sec:
            return await self._conn.setex(key, ttl_sec, serialized)
        return await self._conn.set(key, serialized)

    async def delete(self, *keys: str) -> int:
        """Supprime une ou plusieurs clés. Retourne le nombre supprimé."""
        await self.connect()

        return await self._conn.delete(*keys)

    async def exists(self, key: str) -> bool:
        await self.connect()

        return bool(await self._conn.exists(key))

    async def expire(self, key: str, ttl_sec: int):
        """Définit ou renouvelle le TTL d'une clé existante."""
        await self.connect()
        await self._conn.expire(key, ttl_sec)

    # --------------------------------------------------------
    # HASH — pour les structures dict en Redis
    # --------------------------------------------------------

    async def hget(self, key: str, field: str) -> Optional[Any]:
        await self.connect()
        raw = await self._conn.hget(key, field)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    async def hset(self, key: str, field: str, value: Any):
        await self.connect()

        await self._conn.hset(key, field, self.serialize(value))

    async def hgetall(self, key: str) -> dict:
        """Retourne tous les champs d'un hash, désérialisés."""
        await self.connect()

        raw = await self._conn.hgetall(key)
        result = {}
        for k, v in raw.items():
            try:
                result[k] = json.loads(v)
            except (json.JSONDecodeError, TypeError):
                result[k] = v
        return result

    async def hdel(self, key: str, *fields: str) -> int:
        await self.connect()

        return await self._conn.hdel(key, *fields)

    # --------------------------------------------------------
    # LIST — pour les structures list/tableau en Redis
    # --------------------------------------------------------

    async def lpush(self, queue: str, payload: Any):
        await self.connect()

        await self._conn.lpush(queue, self.serialize(payload))

    async def rpop(self, queue: str) -> Optional[Any]:
        await self.connect()

        raw = await self._conn.rpop(queue)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    async def queue_length(self, queue: str) -> int:
        await self.connect()

        return await self._conn.llen(queue)

    @staticmethod
    def serialize(value: Any) -> str:
        """Sérialise en JSON avec gestion des types Python courants."""
        return json.dumps(value, default=RedisDB.json_default)

    @staticmethod
    def json_default(obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if hasattr(obj, "__dict__"):
            return obj.__dict__
        raise TypeError(f"Type non sérialisable : {type(obj)}")