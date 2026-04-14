from typing import Union

from src.infrastructure.database.pgdb import PgDB

from src.domain.user import User, UserNotFoundError


class UserRepo:

    def __init__(self, db: PgDB):
        self.db = db

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
        u = u[0]
        _id = u.pop("id")
        password_hash = u.pop("password_hash")
        created_at = u.pop("created_at")
        u = User(**u)
        u.id = _id
        u.password_hash = password_hash
        u.created_at = created_at
        return u

