import enum
import json
import re
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime

from typing import Callable, Awaitable, Optional, AsyncGenerator, List

from src.utils.tools import value_parser


@dataclass
class Election:
    name: str                             = ""
    type: str                             = ""
    status: str                           = "DRAFT"

    id: uuid.UUID                         = field(init=False)

    delete: Callable[[], Awaitable[None]] = field(init=False)
    update: Callable[[], Awaitable[None]] = field(init=False)

    doc: "Document"                       = field(init=False)

    def to_dict(self) -> dict:
        d = {
            "name": self.name,
            "type": self.type,
            "status": self.status,
        }
        if hasattr(self, "id"):
            d["id"] = str(self.id)
        return d

    def __repr__(self):
        extra = ""
        if hasattr(self, "id"):
            extra += "id=" + str(self.id) + " "
        return "<Election {}{}>".format(extra, self.name)


class DocumentType(enum.Enum):
    PDF_ARCHIVE     = "PDF_ARCHIVE"
    SCAN_PV         = "SCAN_PV"


@dataclass
class Document:
    election_id: uuid.UUID
    file_name: str
    storage_url: str
    integrity_hash: str
    uploaded_by: uuid.UUID
    file_type: DocumentType = DocumentType.PDF_ARCHIVE

    uploaded_at: Optional[datetime] = None
    last_integrity_check: Optional[datetime] = None
    integrity_status: bool = True

    id: uuid.UUID = field(init=False)

    get: Callable[[], AsyncGenerator[str, None]] = field(init=False)

    def __post_init__(self):
        self.file_name = str(self.file_name)
        if isinstance(self.file_type, str):
            self.file_type = DocumentType(self.file_type)

    def to_dict(self) -> dict:
        d = {
            "election_id": str(self.election_id),
            "file_name": self.file_name,
            "storage_url": self.storage_url,
            "integrity_hash": self.integrity_hash,
            "file_type": self.file_type.value,
            "uploaded_by": str(self.uploaded_by),
            "last_integrity_check": self.last_integrity_check,
            "integrity_status": self.integrity_status,
        }
        if hasattr(self, "id"):
            d["id"] = str(self.id)
        if self.uploaded_at:
            d["uploaded_at"] = self.uploaded_at
        return d

    def __repr__(self):
        return "<Document {}>".format(self.file_name)


def int_parser(value):
    if isinstance(value, int):
        return value
    return int(float(re.sub(r"\s", "", value)))


def percent_parser(value):
    value = str(value).replace(",", ".").replace("%", "")
    value = float(re.sub(r"\s", "", value))
    return value / 100



@dataclass
class CandidateStagingResult:
    locality_id: int

    full_name: str
    raw_value: int

    bbox_json: dict

    is_independent: Optional[bool]

    party_ticker: str = None

    winner: Optional[bool] = None

    validated_by: Optional[uuid.UUID] = None

    validation_status: str = "PENDING"

    validated_at: Optional[datetime] = None

    created_at: datetime = field(init=False)
    id: int = field(init=False)

    def __post_init__(self):
        assert self.full_name
        self.raw_value = value_parser(int_parser, self.raw_value, 0)

    def to_dict(self, bbox_json_as_text=False, not_winner=True):
        d = {}
        for k in self.__annotations__:
            if k not in ("id", "created_at", "winner"):
                v = getattr(self, k)
                if v is not None:
                    d[k] = v
        if getattr(self, "id", None) is not None:
            d["id"] = self.id

        if not not_winner:
            d["winner"] = self.winner

        if getattr(self, "created_at", None) is not None:
            d["created_at"] = self.created_at
        if bbox_json_as_text:
            d["bbox_json"] = json.dumps(self.bbox_json)
        return d


@dataclass
class LocalityStagingResult:
    region: str
    locality: str
    election_id: uuid.UUID

    source_id: uuid.UUID

    registered_voters_total: int
    voters_total: int
    expressed_votes: int

    bbox_json: dict

    # candidates: List[CandidateStagingResult] = field(init=False)

    polling_stations_count: Optional[int] = None
    on_call_staff: Optional[int] = None

    pop_size_male: Optional[int] = None
    pop_size_female: Optional[int] = None
    pop_size: Optional[int] = None

    registered_voters_male: Optional[int] = None
    registered_voters_female: Optional[int] = None

    voters_male: Optional[int] = None
    voters_female: Optional[int] = None

    participation_rate: Optional[float] = None

    null_ballots: Optional[int] = None

    blank_ballots_pct: Optional[float] = None
    blank_ballots_count: Optional[int] = None

    unregistered_voters_count: Optional[int] = None

    validated_by: Optional[uuid.UUID] = None

    validation_status: str = "PENDING"


    validated_at: Optional[datetime] = None
    created_at: datetime = field(init=False)

    id: int = field(init=False)

    def __post_init__(self):
        assert self.locality and self.region

        self.registered_voters_total = value_parser(int_parser, self.registered_voters_total)
        self.voters_total = value_parser(int_parser, self.voters_total)
        self.expressed_votes = value_parser(int_parser, self.expressed_votes)

        self.polling_stations_count = value_parser(int_parser, self.polling_stations_count, None)
        self.on_call_staff = value_parser(int_parser, self.on_call_staff, None)

        self.pop_size_male = value_parser(int_parser, self.pop_size_male, None)
        self.pop_size_female = value_parser(int_parser, self.pop_size_female, None)
        self.pop_size = value_parser(int_parser, self.pop_size, None)

        self.registered_voters_male = value_parser(int_parser, self.registered_voters_male, None)
        self.registered_voters_female = value_parser(int_parser, self.registered_voters_female, None)

        self.voters_male = value_parser(int_parser, self.voters_male, None)
        self.voters_female = value_parser(int_parser, self.voters_female, None)

        self.participation_rate = value_parser(percent_parser, self.participation_rate, None)

        self.null_ballots = value_parser(int_parser, self.null_ballots, None)

        self.blank_ballots_pct = value_parser(percent_parser, self.blank_ballots_pct, None)
        self.blank_ballots_count = value_parser(int_parser, self.blank_ballots_count, None)

        self.unregistered_voters_count = value_parser(int_parser, self.unregistered_voters_count, None)

        self.polling_stations_count = value_parser(int_parser, self.polling_stations_count, None)

    def to_dict(self, bbox_json_as_text=False):
        d = {}
        for k in self.__annotations__:
            if k not in ("id", "created_at"):
                v = getattr(self, k)
                if v is not None:
                    d[k] = v
        if getattr(self, "id", None) is not None:
            d["id"] = self.id

        if getattr(self, "created_at", None) is not None:
            d["created_at"] = self.created_at
        if bbox_json_as_text:
            d["bbox_json"] = json.dumps(self.bbox_json)
        return d














