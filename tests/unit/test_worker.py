import os.path
import uuid

from src.worker import Worker

from src.core.config import WORK_DIR

from src.domain.election import Election

from unittest import mock


async def test_treatment_of_an_archive():
    mock_election = Election(
        name="", type="", status="DRAFT"
    )
    mock_election.id = uuid.uuid4()

    mock_election.doc = mock.MagicMock()
    a_ctx = mock_election.doc.get.return_value
    file = os.path.join(
        WORK_DIR, "data", "doc_example", "EDAN_2025_RESULTAT_NATIONAL_DETAILS.pdf"
    )
    a_ctx.__aenter__.return_value = file


    socket_mock = mock.MagicMock()
    def _print(*a, **kw):
        print("--> in socket.emit=","args:", a, "kw:", kw)
    socket_mock.emit = mock.AsyncMock(side_effect=_print)

    llm_repo_mock = mock.MagicMock()

    llm_response = {'success': True, 'result': {
            'election_metadata': {'type': 'legislative', 'format': 'row',
                                  'confidence_score': 0.8},
            'mapping_index': {'region': 0, 'locality': 1,
                              'polling_stations_count': 3,
                              'registered_voters_total': 4, 'voters_total': 5,
                              'null_ballots': 7, 'expressed_votes': 8,
                              'blank_ballots_count': 9,
                              'blank_ballots_pct': 10,
                              'unregistered_voters_count': -1},
            'candidate_results': {
                'row_mode': {'party_idx': 11, 'candidate_name_idx': 12,
                             'score_idx': 13, 'percent_idx': 14,
                             'status_idx': -1}, 'column_mode': []}},
                    'provider': 'groq',
                    'model': 'meta-llama/llama-4-scout-17b-16e-instruct',
                    'prompt_tokens': 893, 'completion_tokens': 871,
                    'latency_ms': 5564}

    llm_repo_mock.run = mock.AsyncMock(
        side_effect=[llm_response, {"success": False}]
    )

    msg_broker = mock.MagicMock()
    service_mock = mock.MagicMock()
    service_mock.get = mock.AsyncMock(return_value=mock_election)
    worker = Worker(
        election_service=service_mock,
        msg_broker=msg_broker,
        socket=socket_mock,
        llm_repo=llm_repo_mock,
    )

    await worker._processing_archive_task("test", "test")

    pass