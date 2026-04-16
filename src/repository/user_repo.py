import uuid
from typing import Union, List

from src.infrastructure.database.pgdb import PgDB

from src.domain.user import User, UserNotFoundError, Role


class UserRepo:
    def __init__(self, db: PgDB):
        self.db = db

    @staticmethod
    def _parse(user_dict)-> User:
        user_dict = user_dict.copy()
        _id = uuid.UUID(str(user_dict.pop("id")))
        password_hash = user_dict.pop("password_hash")
        created_at = user_dict.pop("created_at")
        created_by = user_dict.pop("created_by", None)
        if created_by is not None:
            created_by = uuid.UUID(str(created_by))
        user_dict = User(**user_dict, created_by=created_by)
        user_dict.id = _id
        user_dict._password_hash = password_hash
        user_dict.created_at = created_at
        return user_dict

    async def get_all(self, role: Role=None)->List[User]:
        users = await self.db.run_query(
            f"""
            SELECT * FROM users
            {"" if role is None else "WHERE role=$1"}
            """, params=(None if role is None else (role.value,))
        )
        us = []
        for u in users:
            us.append(self._parse(u))
        return us

    async def create_user(self, user: User):
        assert hasattr(user, "password_hash") is not None
        _id = await self.db.run_query(
            """
            INSERT INTO users (
                full_name,
                email,
                password_hash,
                role, created_by, is_active
            ) VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """, params=(
                user.full_name,
                user.email,
                user.password_hash,
                user.role.value,
                user.created_by,
                user.is_active,
            )
        )
        user.id = _id
        return user


    async def get_user_by_email(self, email, raise_=True) \
            -> Union[User, None]:
        u = await self.db.run_query(
            """
            SELECT * FROM users
            WHERE email = $1
            """, params=(email,), limit=1
        )
        if not u:
            if raise_:
                raise UserNotFoundError(email)
            return None
        return self._parse(u[0])

