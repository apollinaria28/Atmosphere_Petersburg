import json
import os
import re
import uuid
import traceback
import io
from typing import Any, Dict, List, Optional, Union

import psycopg2.extras
from werkzeug.utils import secure_filename
from werkzeug.datastructures import FileStorage


# ---------- Валидация ----------
def is_valid_email(email: str) -> bool:
    """Простая валидация email."""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None


def is_valid_name(user_name: str) -> bool:
    """
    Проверка имени пользователя.
    Разрешены русские/английские буквы, пробелы, дефисы. Длина до 30 символов.
    """
    if not user_name or len(user_name) > 30:
        return False
    pattern = r'^[a-zA-Zа-яА-ЯёЁ\s\-]+$'
    return re.match(pattern, user_name) is not None


def is_strong_password(password: str) -> bool:
    """
    Проверка сложности пароля:
    - минимум 6 символов
    - хотя бы одна заглавная и одна строчная буква (латиница или кириллица)
    """
    if len(password) < 6:
        return False
    has_upper = re.search(r'[A-ZА-ЯЁ]', password) is not None
    has_lower = re.search(r'[a-zа-яё]', password) is not None
    return has_upper and has_lower


# ---------- Работа с файлами ----------
def allowed_file(filename: str, allowed_extensions: set) -> bool:
    """Проверяет, разрешено ли расширение файла."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions


def is_valid_image_content(file: FileStorage) -> bool:
    """
    Проверяет что файл реально является изображением через Pillow.
    Защита от загрузки вредоносных файлов правильного расширения.
    """
    try:
        from PIL import Image
        # Читаем первые 2048 байт для определения типа
        header = file.read(2048)
        file.seek(0)  # возвращаем указатель в начало
        img = Image.open(io.BytesIO(header))
        img.verify()  # проверяет что файл не повреждён и является изображением
        file.seek(0)  # возвращаем ещё раз после verify
        return True
    except Exception:
        file.seek(0)
        return False


def save_uploaded_file(
    file: FileStorage,
    folder: str,
    upload_folder: str,
    allowed_extensions: set
) -> Optional[str]:
    """
    Сохраняет загруженный файл в папку static/uploads/{folder}
    и возвращает URL для доступа к файлу.
    """
    if file and allowed_file(file.filename, allowed_extensions):
        # Проверяем содержимое файла через Pillow — защита от маскировки
        if not is_valid_image_content(file):
            print(f"[save_uploaded_file] Файл не является изображением: {file.filename}")
            return None
        # Получаем расширение файла
        ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
        # Генерируем уникальное имя (UUID + расширение)
        unique_filename = f"{uuid.uuid4().hex}.{ext}" if ext else uuid.uuid4().hex
        # Полный путь к папке назначения
        target_folder = os.path.join(upload_folder, folder)
        os.makedirs(target_folder, exist_ok=True)
        file_path = os.path.join(target_folder, unique_filename)
        try:
            file.save(file_path)
            # Возвращаем URL для доступа через статику
            return f'/static/uploads/{folder}/{unique_filename}'
        except Exception as e:
            print(f"[save_uploaded_file] Ошибка сохранения {unique_filename}: {e}")
            return None
    else:
        print(f"[save_uploaded_file] Недопустимый файл: {file.filename if file else 'None'}")
        return None


# ---------- Работа с базой данных (категории) ----------
def get_categories_safe():
    """Безопасное получение категорий из БД."""
    # Локальный импорт для избежания циклических зависимостей
    from .db import get_db_connection

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        cur.execute("SELECT id, slug, name FROM categories_api ORDER BY name")
        categories = [dict(row) for row in cur.fetchall()]
        return categories
    except Exception as e:
        print(f"Ошибка при получении категорий: {e}")
        traceback.print_exc()
        return []
    finally:
        cur.close()
        conn.close()


# ---------- Обработка данных мест ----------
def process_categories(categories: Union[str, List, None]) -> List:
    """Обработка категорий из разных форматов."""
    if not categories:
        return []
    try:
        if isinstance(categories, list):
            return categories
        elif isinstance(categories, str):
            return json.loads(categories)
        else:
            return []
    except Exception:
        return []


def process_place_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Обработка строки с местом из БД.
    - Сериализует даты.
    - Преобразует категории.
    - Очищает описание от HTML-тегов.
    - Обеспечивает наличие photo_url.
    """
    place = dict(row)

    # Сериализация дат
    for key, value in place.items():
        if hasattr(value, 'isoformat'):
            place[key] = value.isoformat()

    # Обработка категорий
    place['categories_list'] = process_categories(place.get('categories'))

    # Логика для photo_url
    photo_url = place.get('photo_url') or place.get('main_photo_url')
    if photo_url and isinstance(photo_url, str) and photo_url.strip():
        place['photo_url'] = photo_url.strip()
    else:
        place['photo_url'] = None

    # Гарантируем наличие title
    if not place.get('title') and place.get('user_title'):
        place['title'] = place['user_title']

    # Очистка описания от HTML
    if place.get('description'):
        # Удаляем все HTML-теги
        clean_desc = re.sub(r'<[^>]+>', '', place['description'])
        # Убираем лишние пробелы
        clean_desc = ' '.join(clean_desc.split())
        # Обрезаем, если слишком длинное (для превью)
        if len(clean_desc) > 200:
            clean_desc = clean_desc[:197] + '...'
        place['description'] = clean_desc

    return place