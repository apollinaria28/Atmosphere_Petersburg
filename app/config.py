import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise RuntimeError(
            f"Переменная {key} не задана в .env!\n"
            f"Добавь её в файл .env и перезапусти приложение."
        )
    return value


class Config:
    # ── Flask ──────────────────────────────────────────────────
    SECRET_KEY = _require('SECRET_KEY')

    # ── База данных ────────────────────────────────────────────
    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_PORT = int(os.getenv('DB_PORT', 5433))
    DB_NAME = os.getenv('DB_NAME', 'spb_places')
    DB_USER = os.getenv('DB_USER', 'apollinaria')
    DB_PASSWORD = _require('DB_PASSWORD')  # обязательно

    # ── Загрузка файлов ────────────────────────────────────────
    MAX_CONTENT_LENGTH = int(os.getenv('MAX_CONTENT_LENGTH', 50 * 1024 * 1024))
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', 'static/uploads')
    AVATARS_FOLDER = os.getenv('AVATARS_FOLDER', 'static/avatars')

    # ── Почта ──────────────────────────────────────────────────
    MAIL_SERVER = os.getenv('MAIL_SERVER', 'smtp.mail.ru')
    MAIL_PORT = int(os.getenv('MAIL_PORT', 587))
    MAIL_USE_TLS = os.getenv('MAIL_USE_TLS', 'true').lower() == 'true'
    MAIL_USERNAME = os.getenv('MAIL_USERNAME')
    MAIL_PASSWORD = os.getenv('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.getenv('MAIL_DEFAULT_SENDER')

    # ── Сессии и безопасность ──────────────────────────────────
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = True
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)

    # ── CORS ───────────────────────────────────────────────────
    ALLOWED_ORIGIN = os.getenv('ALLOWED_ORIGIN')
