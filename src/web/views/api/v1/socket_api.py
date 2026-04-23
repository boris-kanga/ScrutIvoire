import functools

from socketio import AsyncServer

from http.cookies import SimpleCookie


# @socketio.on("*")
# async def catch_all(event, sid, data):
#     print(f"[SERVER] Event reçu: {event}, sid: {sid}, data: {data}")

def init_socket(socketio: AsyncServer, session_serializer):


    def _is_connected(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            print(args, kwargs)
            session = await socketio.get_session(args[0])
            try:
                session_serializer.loads(session["token"])
                return await func(*args, **kwargs)
            except:
                print("Session token is invalid")
                return None
        return wrapper


    @socketio.event
    async def disconnect(sid):
        print("disconnect", sid)

    @socketio.on("election-processing-watcher")
    @_is_connected
    async def election_processing(sid, election_id):
        room = f"processing-{election_id}"
        await socketio.enter_room(sid, room)
        print("Connexion a la room", room)

        await socketio.emit("election_processing-stream", "ok test")

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
                    await socketio.save_session(sid, {"token": session_cookie})

            except Exception as e:
                print(f"Erreur de décodage session : {e}")
