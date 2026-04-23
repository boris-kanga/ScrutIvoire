import asyncio

import click

from src.domain.user import User, Role

from src.core.logger import setup_logging


setup_logging()


@click.group()
def cli():
    pass

@cli.command(help="Run the background worker")
def worker():
    from src.worker import Worker

    asyncio.run(Worker().run())


@cli.command(help="Start web app")
def web():
    from src.web.views import create_app
    from src.infrastructure.database.pgdb import PgDB
    from src.repository.user_repo import UserRepo


    from hypercorn.config import Config
    from hypercorn.asyncio import serve

    app = create_app()
    config = Config()
    port = 5005
    config.bind = [f"0.0.0.0:{port}"]
    # ACTIVATION DU MODE DEBUG / RELOAD
    db_uri = app.other_asgi_app.wsgi_application.config["POSTGRES_DB_URI"]
    async def _init_db():
        pg = await PgDB(
            dsn=db_uri,
        ).connect()
        user_repo = UserRepo(pg)
        # await pg.run_query(
        #     """delete from users"""
        # )
        res = await user_repo.get_all(role=Role.ADMIN)
        if not res:
            user = User(
                full_name="KANGA Boris Parfait",
                email="kangaborisparfait@gmail.com",
                role=Role.ADMIN
            )
            user.password_hash = "boris"

            _ = await user_repo.create_user(
                user
            )
            user = await user_repo.get_user_by_email(user.email)
            user.verify_password("boris", True)

        await pg.close()

    asyncio.run(_init_db())

    # Optionnel : pour voir plus de détails en cas d'erreur
    config.accesslog = "-"
    config.errorlog = "-"
    config.worker_class="asyncio"
    print(f"🚀 Serveur Oracle démarré sur http://localhost:{port}")
    asyncio.run(serve(app, config))


if __name__ == '__main__':
    cli()
