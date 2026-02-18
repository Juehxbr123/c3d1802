import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    bot_token: str = os.getenv("BOT_TOKEN", "")
    mysql_host: str = os.getenv("MYSQL_HOST", "mysql")
    mysql_port: int = int(os.getenv("MYSQL_PORT", "3306"))
    mysql_db: str = os.getenv("MYSQL_DB", "chel3d_db")
    mysql_user: str = os.getenv("MYSQL_USER", "chel3d_user")
    mysql_password: str = os.getenv("MYSQL_PASSWORD", "")


settings = Settings()
