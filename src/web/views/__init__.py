import os
import uuid

from asgiref.wsgi import WsgiToAsgi

from socketio import ASGIApp, AsyncRedisManager, AsyncServer

from flask import Flask, session
from flask.sessions import SecureCookieSessionInterface
from flask_jwt_extended import JWTManager

from src.core.config import WORK_DIR
from src.core import config


from src.web.views.api.v1.socket_api import init_socket


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

    messager_redis = AsyncRedisManager(
        'redis://{host}:{port}'.format(**config.REDIS_CONFIG)
    )

    socketio = AsyncServer(
        async_mode='asgi',
        client_manager=messager_redis,
        cors_allowed_origins="*",
        cors_credentials=True
    )
    decoder = SecureCookieSessionInterface().get_signing_serializer(app)
    init_socket(socketio, decoder)

    flask_app_asgi = WsgiToAsgi(app)

    # On wrap l'application Flask pour Hypercorn
    asgi_app = ASGIApp(socketio, flask_app_asgi)


    @app.before_request
    def make_session_permanent():
        if 'user_room' not in session:
            session['user_room'] = str(uuid.uuid4())
            session.permanent = True


    return asgi_app