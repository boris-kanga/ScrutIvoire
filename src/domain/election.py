import enum
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime

from typing import Callable, Awaitable, Optional, AsyncGenerator


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




