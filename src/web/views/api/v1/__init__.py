from flask import Blueprint

from .auth import auth


v1 = Blueprint('v1', __name__, url_prefix="/api/v1")

v1.register_blueprint(auth)