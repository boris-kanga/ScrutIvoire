import re



def to_persiste(channel: str):
    return channel + ":persistante"


def is_persistance_channel(channel: str):
    return re.search(r":persistante\b", channel, re.I) is not None


class MessageBrokerChannel:
    CURRENT_ELECTION = "election:current"

    PROCESSING_ELECTION_RAPPORT = "election:persistante:rapport_processing"

