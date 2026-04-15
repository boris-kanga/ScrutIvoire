
import traceback
from datetime import timedelta

from flask import Blueprint, jsonify, request

from flask_jwt_extended import create_access_token, set_access_cookies


from src.domain.user import UserError
from src.infrastructure.database.pgdb import PgDB
from src.infrastructure.database.redisdb import RedisDB
from src.repository.election_repo import ElectionRepo
from src.repository.user_repo import UserRepo
from src.web import db_depends


view = Blueprint('election', __name__, url_prefix="/election")


@view.get('/current')
@db_depends
async def current(db: PgDB, rd: RedisDB):
    res = await ElectionRepo(db, rd).get_current_election()
    return jsonify({
        "ok": True, "current": res
    })


@view.get('/archives')
@db_depends
async def archives(db: PgDB, rd: RedisDB):
    return "ok"

