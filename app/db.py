# app/db.py

import psycopg2
import psycopg2.extras
from flask import current_app


def get_db_connection():
    """
    Возвращает соединение с базой данных, используя параметры из конфигурации приложения.
    """
    conn = psycopg2.connect(
        host=current_app.config['DB_HOST'],
        port=current_app.config['DB_PORT'],
        database=current_app.config['DB_NAME'],
        user=current_app.config['DB_USER'],
        password=current_app.config['DB_PASSWORD']
    )
    conn.autocommit = True
    return conn