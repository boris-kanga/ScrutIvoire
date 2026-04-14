from flask import Blueprint, render_template

from src.web.views.api import API_BASE

admin = Blueprint("admin", __name__, url_prefix="/admin")


@admin.get("/")
async def index():
    return render_template("login.html", api_base=API_BASE)


