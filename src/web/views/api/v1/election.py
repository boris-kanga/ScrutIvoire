
import traceback
import uuid

from flask import Blueprint, jsonify, request, session

from flask_jwt_extended import get_jwt_identity, \
    verify_jwt_in_request
from werkzeug.utils import secure_filename

from src.domain.election import Election
from src.infrastructure.database.pgdb import PgDB
from src.infrastructure.database.redisdb import RedisDB
from src.infrastructure.file_storage import FileStorageProtocol
from src.repository.election_repo import ElectionRepo
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
        await service.delete_archive(election.id)
        return jsonify({"ok": False}), 400

    return jsonify({"ok": True, "election_id": election.id})


@view.get("/<election_id>/draft/report-file")
@db_depends
async def get_report_file_url(storage: FileStorageProtocol, db: PgDB, rd: RedisDB, election_id):
    repo = ElectionRepo(db)
    service = ElectionService(repo, rd, storage)
    election = await service.get(election_id)

    return jsonify({
        "ok": True, "url": await service.get_report_url(
            election_id
        ),
        "state": await service.get_archive_process_state(election_id),
        "election": election.to_dict(),
        "filename": election.doc.file_name
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

@view.get("/<election_id>/confirm")
@db_depends
async def confirm_draft(storage: FileStorageProtocol, db: PgDB, rd: RedisDB, election_id):
    verify_jwt_in_request()
    repo = ElectionRepo(db)
    service = ElectionService(repo, rd, storage)

    data = await service.get_archive_process_state(election_id)
    if not data:
        return jsonify({"ok": False, "msg": "No state"}), 400
    for k, v in data.items():
        if v["state"] != "done":
            return jsonify({"ok": False, "msg": f"step {k} not done"}), 400

    election = await service.get(election_id)
    election.status = "ARCHIVED"

    await election.update()

    return jsonify({
        "ok": True
    })


@view.route('/monitoring')
@db_depends
async def monitoring(db: PgDB):
    verify_jwt_in_request()
    election_id = request.args.get('election_id')
    query = """
        SELECT id, question, ask_time, answer_time, 
               status, answer, answer_meta
        FROM chat_session
        WHERE status = 'DONE'
    """
    params = []
    if election_id:
        query += " AND election_id = $1"
        params.append(election_id)
    query += " ORDER BY ask_time DESC LIMIT 200"
    rows = await db.run_query(query, params=params)
    return jsonify([dict(r) for r in rows])

