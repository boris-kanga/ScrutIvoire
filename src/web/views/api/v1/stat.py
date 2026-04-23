import traceback
from datetime import timedelta

from flask import Blueprint, jsonify, request

from flask_jwt_extended import create_access_token, set_access_cookies, \
    verify_jwt_in_request

from src.domain.user import UserError
from src.infrastructure.database.pgdb import PgDB
from src.repository.election_repo import ElectionRepo
from src.services.election_service import ElectionService
from src.web import db_depends


view = Blueprint('stat', __name__, url_prefix="/stat")


@view.get('/')
@db_depends
async def get_stat(db: PgDB, rd, storage):
    with_integrity = False
    try:
        verify_jwt_in_request()
        with_integrity = True
    except:
        pass

    service = ElectionService(
        ElectionRepo(db), rd, storage
    )
    elections = await service.get_all(with_integrity=with_integrity)
    return jsonify({
        "ok": True, "elections": elections
    })





