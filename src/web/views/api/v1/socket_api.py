from socketio import AsyncServer

from http.cookies import SimpleCookie


def init_socket(socketio: AsyncServer, session_serializer):

    @socketio.event
    async def disconnect(sid):
        print("disconnect", sid)

    @socketio.event
    async def connect(sid, environ, auth):
        auth_data = environ.get('pyeio.auth', {})
        token = auth_data.get('token')
        print("Connected", sid, token, auth)
        cooked = environ.get('HTTP_COOKIE')
        if isinstance(cooked, bytes):
            cooked = cooked.decode()
        cookies = SimpleCookie(cooked or "")

        if 'session' in cookies:
            session_cookie = cookies['session'].value
            try:
                decoded_session = session_serializer.loads(session_cookie)
                user_room = decoded_session.get('user_room')

                if user_room:
                    await socketio.enter_room(sid, user_room)
                    await socketio.emit(
                        'connection_ack',
                        {'status': 'success'},
                        room=user_room
                    )


            except Exception as e:
                print(f"Erreur de décodage session : {e}")
