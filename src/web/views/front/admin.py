from flask import Blueprint, render_template, request, redirect, url_for

from src.web.views.api import API_BASE

admin = Blueprint("admin", __name__, url_prefix="/Administration")


@admin.get("/Connexion")
async def login():
    return render_template("login.html", api_base=API_BASE)


@admin.get("/")
async def index():
    if "access_token_cookie" not in request.cookies:
        return redirect(url_for("admin.login"))
    return render_template("admin.html", api_base=API_BASE)


@admin.get("/Archives")
async def archives():
    return render_template("archives.html", api_base=API_BASE)

@admin.get("/Archives/Nouveau")
async def new_archive():
    return render_template("new_archive.html", api_base=API_BASE)