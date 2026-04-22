import asyncio
import traceback
from datetime import timedelta

from flask import Blueprint, jsonify, request, session

from flask_jwt_extended import create_access_token, set_access_cookies


from src.domain.user import UserError
from src.infrastructure.database.pgdb import PgDB
from src.repository.election_repo import ElectionRepo
from src.services.election_service import ElectionService
from src.web import db_depends


view = Blueprint('chat', __name__, url_prefix="/chat")


@view.post('/<archive_id>')
@db_depends
async def ask(db: PgDB, rd, storage, archive_id):
    _input = request.json
    options = None
    question = None
    if "options" in _input:
        options = _input["options"]
    else:
        question = _input["question"]

    print("question:", question, "options:", options)
    service = ElectionService(
        ElectionRepo(db), rd, storage
    )
    await service.ask_llm(
        {"options": options, "question": question}, archive_id, session["user_room"]
    )
    return jsonify({"ok": True})


@view.get('/base-stat/<archive_id>')
@db_depends
async def stat_indiv(db: PgDB, rd, storage, archive_id):
    service = ElectionService(
        ElectionRepo(db), rd, storage
    )

    election, history = await asyncio.gather(
        service.get(archive_id),
        service.get_history(archive_id, session["user_room"])
    )
    charts = []
    if not history and election.type in ("legislative", ""):
        top_5_locality = await service.top_n_locality(
            election
        )
        charts.append([
            "table", {
                "title": "Top 5 Localités",
                "columns": ["Localité", "%Part."],
                "rows": [
                    [r["locality"], str(round(100 * r["participation_rate"], 1))+"%"]
                    for r in top_5_locality
                ]
            }
        ])
        party_ticker_repr = await service.party_ticker_repr(
            election
        )
        charts.append(["bar", [
            {"label": x[0], "value": x[1]} for x in party_ticker_repr
        ]])

    return jsonify({
        "ok": True, "election": election.to_dict(),
        "archive_file_name": election.doc.file_name,
        "charts": charts,
        "history": history
    })

