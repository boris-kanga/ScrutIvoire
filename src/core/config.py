import os
from datetime import timedelta

from dotenv import load_dotenv


APP_NAME = "ScrutIvoire"


WORK_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), os.pardir, os.pardir
    )
)


load_dotenv(os.path.join(WORK_DIR, "config", ".env"))


SECRET_KEY = os.getenv("SECRET_KEY")
PERMANENT_SESSION_LIFETIME = timedelta(days=30)
SESSION_COOKIE_HTTPONLY = True


REDIS_CONFIG = {
    "host": os.environ.get("REDIS_HOST", "localhost"),
    "port": int(os.environ.get("REDIS_PORT", 6379)),
}


REDIS_DB_URI='redis://{host}:{port}'.format(**REDIS_CONFIG)


POSTGRES_DB_URI = os.environ.get("DB_URI", "postgresql://localhost/scrutivoire_db")

LLM_DB_URI = os.environ.get("LLM_DB_URI", "postgresql://localhost/scrutivoire_db")
LLM_SLIDING_WINDOW_DEEP = 3


S3_CONFIG = {
    "endpoint": os.environ.get(f"S3_ENDPOINT"),
    "access_key": os.getenv("S3_ACCESS_KEY"),
    "secret_key": os.getenv("S3_SECRET_KEY"),
    "public_url": os.getenv(
        "S3_PUBLIC_URL", "http://localhost:9000"
    )
}


# JWT
JWT_TOKEN_LOCATION = ["cookies"]

LLM_PROVIDERS = {
    "GEMINI"  : os.getenv("AISTUDIO_KEY"),
    "CEREBRAS": os.getenv("CEREBRAS_KEY"),
    "GROQ"    : os.getenv("GROQ_KEY"),
    "OPENAI"  : os.getenv("OPENAI_KEY")
}

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")


if __name__ == '__main__':
    pass