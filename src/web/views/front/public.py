from flask import Blueprint


public = Blueprint("public", __name__, url_prefix="/")


@public.get("/")
async def index():
    return "ok"


