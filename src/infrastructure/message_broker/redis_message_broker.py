import asyncio
import json

from typing import Any, AsyncGenerator

from src.infrastructure.message_broker import MessageBroker
from src.infrastructure.database.redisdb import RedisDB, redis


class RedisMessageBroker(MessageBroker):
    def __init__(self, redis_db: RedisDB):
        MessageBroker.__init__(self)
        self._redis = redis_db

    async def publish(self, channel: str, payload: Any) -> int:
        conn = await self._redis.get_conn()
        persistance = self.is_persistante_channel(channel)
        if persistance:
            return await self._redis.lpush(channel, payload)
        else:
            payload = self._redis.serialize(payload)
            return await conn.publish(channel, payload)

    def subscribe(
            self,
            *channels: str,
            timeout=float("inf"),
    ) -> AsyncGenerator[dict, None]:
        async def _inner():
            p_channels = set(
                c for c in channels if self.is_persistante_channel(c))
            np_channels = set(
                c for c in channels if not self.is_persistante_channel(c))
            conn = await self._redis.get_conn()
            s = asyncio.get_event_loop().time()
            tasks = []
            queue = asyncio.Queue()
            if np_channels:
                pubsub_conn = redis.Redis(
                    connection_pool=conn.connection_pool)
                pubsub = pubsub_conn.pubsub(ignore_subscribe_messages=True)
                await pubsub.subscribe(*np_channels)
                async def non_persistante_msg():
                    try:
                        while True:
                            _t = (
                                    timeout -
                                    (asyncio.get_event_loop().time() - s)
                            )
                            if _t <= 0:
                                return
                            res = await pubsub.get_message(
                                timeout=(
                                    None if _t == float("inf") else _t
                                )
                            )
                            if res is None or _t <= 0:
                                return
                            await queue.put({
                                "channel": res["channel"].decode(),
                                "data": res["data"]
                            })
                    finally:
                        await pubsub.unsubscribe(*np_channels)
                        await pubsub.aclose()
                        await pubsub_conn.aclose()
                tasks.append(asyncio.create_task(non_persistante_msg()))

            if p_channels:
                async def persistante_msg():
                    while True:
                        _t = timeout - (asyncio.get_event_loop().time() - s)
                        if _t <= 0:
                            return
                        res = await conn.brpop(
                            list(p_channels),
                            timeout=(
                                0 if _t == float("inf") else max(1, int(_t))
                            )
                        )
                        if res is None or _t <= 0:
                            return
                        chan, val = res
                        await queue.put({
                            "channel": (
                                chan if isinstance(chan,str) else chan.decode()
                            ),
                            "data": val
                        })

                tasks.append(asyncio.create_task(persistante_msg()))
            await asyncio.sleep(0)
            try:
                age = asyncio.get_event_loop().time() - s
                while age < timeout:
                    age = asyncio.get_event_loop().time() - s
                    try:
                        raw_message = await asyncio.wait_for(
                            queue.get(), timeout=(
                                None
                                if (timeout - age) == float("inf")
                                else (timeout - age)
                            )
                        )
                        if raw_message is not None:
                            try:
                                data = json.loads(raw_message["data"])
                            except (json.JSONDecodeError, TypeError):
                                data = raw_message["data"]
                            yield {
                                "channel": raw_message["channel"],
                                "data": data,
                            }
                        else:
                            return
                    except asyncio.TimeoutError:
                        break
            finally:
                for t in tasks:
                    t.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

        return _inner()