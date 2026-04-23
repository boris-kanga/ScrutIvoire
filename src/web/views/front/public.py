from flask import Blueprint, render_template

from src.web.views.api import API_BASE

public = Blueprint("public", __name__, url_prefix="/")


@public.get("/")
async def index():
    return render_template("public_home.html", api_base=API_BASE)


@public.get("/Chat/<id_>")
async def chat_view(id_):
    return render_template("chat.html",id_=id_, api_base=API_BASE)
