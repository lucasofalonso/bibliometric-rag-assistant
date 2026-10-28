import os

from dotenv import load_dotenv


def get_postgres_settings() -> dict:
    load_dotenv()

    # Keys match URL.create() keyword arguments
    return {
        "username": os.environ["POSTGRES_USER"],
        "password": os.environ["POSTGRES_PASSWORD"],
        "host": os.environ["POSTGRES_HOST"],
        "port": int(os.environ["POSTGRES_PORT"]),
        "database": os.environ["POSTGRES_DB"],
    }
