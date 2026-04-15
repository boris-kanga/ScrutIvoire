from flask import Blueprint

from .auth import auth
from .election import view


v1 = Blueprint('v1', __name__, url_prefix="/api/v1")

v1.register_blueprint(auth)
v1.register_blueprint(view)