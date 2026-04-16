from socketio import AsyncServer


def init_socket(socketio: AsyncServer):

    @socketio.event
    async def disconnect(sid):
        print("disconnect", sid)


    @socketio.event
    async def connect(sid, environ, auth):
        #await redis_db.
        auth_data = environ.get('pyeio.auth', {})
        token = auth_data.get('token')

        print("Connected", sid, token, auth)

