import sys

from loguru import logger

SECRET_FIELD_NAMES = (
    "bot_token",
    "telegram_api_hash",
    "deepseek_api_key",
    "github_token",
)

LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)


def setup_logging(level: str) -> None:
    logger.remove()
    logger.add(sys.stderr, level=level.upper(), format=LOG_FORMAT, backtrace=False, diagnose=False)


def describe_secret(value: str) -> str:
    return "set" if value else "missing"
