from abc import abstractmethod, ABC

from typing import Any, AsyncGenerator
from src.domain.message_broker import is_persistance_channel


class MessageBroker(ABC):

    @classmethod
    def is_persistante_channel(cls, channel: str):
        return is_persistance_channel(channel)

    @abstractmethod
    async def publish(self, channel: str, payload: Any) -> int:
        """
        Publie un message sur un canal.
        Le payload est sérialisé en JSON automatiquement.
        Retourne le nombre d'abonnés qui ont reçu le message.
        """

    @abstractmethod
    def subscribe(
            self,
            channel: str,
            timeout=float("inf"),
    ) -> AsyncGenerator[dict, None]:
        """
        Générateur async — yield chaque message reçu sur les canaux.

        Usage :
            async for msg in redis.subscribe("economic_events", "market_news"):
                data   = msg["data"]    # payload désérialisé
                channel = msg["channel"]
        """
