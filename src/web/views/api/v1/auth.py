import traceback
from datetime import timedelta

from flask import Blueprint, jsonify, request

from flask_jwt_extended import create_access_token, set_access_cookies


from src.domain.user import UserError
from src.infrastructure.database.pgdb import PgDB
from src.repository.user_repo import UserRepo
from src.web import db_depends


auth = Blueprint('auth', __name__, url_prefix="/auth")


@auth.post('/login')
@db_depends
async def login(db: PgDB):
    try:
        email = request.json['email']
        password = request.json['password']
        user = await UserRepo(db).get_user_by_email(email, raise_=True)
        user.verify_password(password, raise_=True)
    except UserError:
        traceback.print_exc()
        return jsonify({"ok": False, "msg": "Bad Password or Email"}), 401
    except Exception:
        traceback.print_exc()
        return jsonify({"ok": False}), 400

    token = create_access_token(
        str(user.id),
        expires_delta=timedelta(hours=1),
        additional_claims=user.to_dict()
    )
    response = jsonify({"token": token, "ok": True, "role": user.role.value})
    set_access_cookies(response, token)
    return response

