import os

from dotenv import load_dotenv


APP_NAME = "ScrutIvoire"


WORK_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), os.pardir, os.pardir
    )
)


load_dotenv(os.path.join(WORK_DIR, "config", ".env"))


SECRET_KEY = os.getenv("SECRET_KEY")


REDIS_CONFIG = {
    "host": os.environ.get("REDIS_HOST", "localhost"),
    "port": int(os.environ.get("REDIS_PORT", 6379)),
}


POSTGRES_DB_URI = os.environ.get("DB_URI", "postgresql://localhost/scrutivoire_db")


S3_CONFIG = {
    "endpoint": os.environ.get(f"S3_ENDPOINT"),
    "access_key": os.getenv("S3_ACCESS_KEY"),
    "secret_key": os.getenv("S3_SECRET_KEY"),
}


# JWT
JWT_TOKEN_LOCATION = ["cookies"]


if __name__ == '__main__':
    pass