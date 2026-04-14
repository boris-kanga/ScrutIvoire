import os

from flask import Flask
from flask_jwt_extended import JWTManager

from src.core.config import WORK_DIR, APP_NAME
from src.core import config


def create_app():
    from src.web.views.front.admin import admin
    from src.web.views.front.public import public

    from src.web.views.api.v1 import v1

    app = Flask(
        __name__,
        static_folder=os.path.join(WORK_DIR, "src", "web", "static"),
        template_folder=os.path.join(WORK_DIR, "src", "web", "templates"),
    )
    app.config.from_object(config)
    app.register_blueprint(admin)
    app.register_blueprint(public)
    # register api bp.
    app.register_blueprint(v1)

    JWTManager(app)

    return app