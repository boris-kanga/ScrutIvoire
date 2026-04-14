import enum
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

from werkzeug.security import check_password_hash, generate_password_hash


class Role(enum.Enum):
    ADMIN="ADMIN"
    FIELD_AGENT="FIELD_AGENT"
    VALIDATOR="VALIDATOR"


class UserError(Exception): pass


class UserNotFoundError(UserError):
    def __str__(self):
        return "User not found"


class UserAuthFail(UserError):
    def __str__(self) -> str:
        return "User auth failed"



@dataclass
class User:
    email: str
    full_name: str
    role: Role
    created_by: Optional[uuid.UUID] = None
    is_active: bool = True
    _password_hash: str = field(init=False)
    created_at: datetime = field(init=False)
    id: uuid.UUID = field(init=False)



    @property
    def password_hash(self) -> str:
        return self._password_hash

    @password_hash.setter
    def password_hash(self, password):
        self._password_hash = str(generate_password_hash(
            password, method='pbkdf2:sha256'
        ))

    def __post_init__(self):
        if isinstance(self.role, str):
            self.role = Role(self.role)

    def verify_password(self, password: str, raise_=False) -> bool:
        if not hasattr(self, "password_hash"):
            raise UserError
        res = check_password_hash(
            self.password_hash, password,
        )
        if raise_ and not res:
            raise UserAuthFail
        return res

    def to_dict(self) -> dict:
        u = asdict(self)
        p = u.pop("_password_hash", None)
        if p:
            u["password_hash"] = p
        u["role"] = self.role.value
        u["id"] = str(self.id)
        return u


