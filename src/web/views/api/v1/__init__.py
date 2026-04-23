from flask import Blueprint

from .auth import auth
from .election import view as election_view
from .stat import view as stat_view
from.chat import view as chat_view


v1 = Blueprint('v1', __name__, url_prefix="/api/v1")

v1.register_blueprint(auth)
v1.register_blueprint(election_view)

v1.register_blueprint(stat_view)

v1.register_blueprint(chat_view)