
import traceback
import uuid
from datetime import timedelta

from flask import Blueprint, jsonify, request, session

from flask_jwt_extended import get_jwt_identity, jwt_required, \
    verify_jwt_in_request
from werkzeug.utils import secure_filename

from src.domain.election import Election
from src.domain.user import UserError
from src.infrastructure.database.pgdb import PgDB
from src.infrastructure.database.redisdb import RedisDB
from src.infrastructure.file_storage import FileStorageProtocol
from src.repository.election_repo import ElectionRepo
from src.repository.user_repo import UserRepo
from src.services.election_service import ElectionService
from src.web import db_depends


view = Blueprint('election', __name__, url_prefix="/election")


@view.get('/current')
@db_depends
async def current(storage: FileStorageProtocol, db: PgDB, rd: RedisDB):
    repo = ElectionRepo(db)
    service = ElectionService(repo, rd, storage)
    res = await service.get_current_election()
    if res:
        res = res.to_dict()
    return jsonify({
        "ok": True, "current": res
    })


@view.post('/new/archive-form-file')
@db_depends
async def archive_from_file(storage: FileStorageProtocol, db: PgDB, rd: RedisDB):
    verify_jwt_in_request()
    user = uuid.UUID(get_jwt_identity())

    repo = ElectionRepo(db)
    service = ElectionService(repo, rd, storage)

    election = Election(
        name="draft"
    )
    election = await repo.add_election(election)

    try:

        archive = request.files['archive']
        filename = secure_filename(archive.filename)

        _hash = request.form["hash"]

        await service.start_archiving_process(
            election, _hash, archive.stream, user, session["user_room"],
            filename=filename
        )
    except Exception:
        traceback.print_exc()
        await election.delete()
        return jsonify({"ok": False}), 400

    return jsonify({"ok": True, "election_id": election.id})


@view.get("/<election_id>/draft/report-file")
@db_depends
async def get_report_file_url(storage: FileStorageProtocol, db: PgDB, rd: RedisDB, election_id):
    repo = ElectionRepo(db)
    service = ElectionService(repo, rd, storage)
    return jsonify({
        "ok": True, "url": await service.get_report_url(
            election_id
        )
    })


@view.delete("/<election_id>/draft")
@db_depends
async def delete_draft(storage: FileStorageProtocol, db: PgDB, rd: RedisDB, election_id):
    verify_jwt_in_request()
    repo = ElectionRepo(db)
    service = ElectionService(repo, rd, storage)
    user = uuid.UUID(get_jwt_identity())
    await service.delete_archive(election_id)

    return jsonify({
        "ok": True
    })

