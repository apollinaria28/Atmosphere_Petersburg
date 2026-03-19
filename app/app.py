from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import psycopg2
import psycopg2.extras
import json
import os
import traceback
from functools import wraps
import uuid
import re

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here-change-in-production'


UPLOAD_FOLDER = os.path.join(app.root_path, 'static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 10MB

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Путь к статическим файлам
STATIC_FOLDER = 'static'
app.config['STATIC_FOLDER'] = STATIC_FOLDER

# Игнорируем запросы от Chrome DevTools
@app.route('/.well-known/appspecific/<path:dummy>')
def ignore_chrome_requests(dummy):
    return '', 204

from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from test_logic import TestLogic
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login_page'  # Куда перенаправлять неавторизованных
login_manager.login_message = 'Пожалуйста, войдите в систему для доступа к этой странице'
login_manager.login_message_category = 'info'


# Модель пользователя для Flask-Login
class User(UserMixin):
    def __init__(self, user_data):
        self.id = str(user_data['id'])

        self.email = user_data['email']
        self.username = user_data.get('username')
        self.display_name = user_data.get('display_name')
        self.role = user_data['role']
        self.avatar_url = user_data.get('avatar_url')

        # Сохраняем is_active как приватный атрибут
        self._active = bool(user_data.get('is_active', True))

    # Flask-Login ожидает свойство is_active
    @property
    def is_active(self):
        return self._active

    # Flask-Login ожидает свойство is_authenticated (по умолчанию True для зарегистрированных)
    @property
    def is_authenticated(self):
        return True

    # Flask-Login ожидает свойство is_anonymous (по умолчанию False для зарегистрированных)
    @property
    def is_anonymous(self):
        return False

    def get_display_name(self):
        """Возвращает отображаемое имя в приоритете"""
        return self.display_name or self.username or self.email.split('@')[0]

    def get_id(self):
        """Возвращает ID пользователя как строку"""
        return str(self.id)

# Загрузчик пользователя для Flask-Login
@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        user_data = cur.fetchone()
        if user_data:
            return User(user_data)
        return None
    except Exception as e:
        print(f"Ошибка при загрузке пользователя: {e}")
        return None
    finally:
        cur.close()
        conn.close()

# Декоратор для проверки роли администратора
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            return jsonify({'success': False, 'error': 'Требуются права администратора'}), 403
        return f(*args, **kwargs)
    return decorated_function

# Функция проверки email
def is_valid_email(email):
    """Простая валидация email"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def is_valid_name(user_name):
    # Регулярка: буквы (RU/EN), цифры, от 3 до 30 символов
    if not user_name or len(user_name) > 30:
        return False
    # Разрешены буквы (включая Ё), пробелы и дефисы (для двойных имён)
    pattern = r'^[a-zA-Zа-яА-ЯёЁ\s\-]+$'
    return re.match(pattern, user_name) is not None

def is_strong_password(password):
    """Проверяет, что пароль содержит хотя бы одну заглавную и одну строчную латинскую букву."""
    if len(password) < 6:
        return False
    has_upper = re.search(r'[A-ZА-ЯЁ]', password) is not None  # заглавные
    has_lower = re.search(r'[a-zа-яё]', password) is not None  # строчные
    return has_upper and has_lower

DB_CONFIG = {
    'host': 'localhost',
    'port': 5433,
    'database': 'spb_places',
    'user': 'apollinaria',
    'password': 'love*betty28'
}

test_logic = TestLogic(DB_CONFIG)

def get_db_connection():
    """Функция для получения соединения с БД"""
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    return conn

def get_categories_safe():
    """Безопасное получение категорий """
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


def process_categories(categories):
    """Обработка категорий из разных форматов"""
    if not categories:
        return []
    try:
        if isinstance(categories, list):
            return categories
        elif isinstance(categories, str):
            return json.loads(categories)
        else:
            return []
    except:
        return []

def process_place_row(row):
    """Обработка строки с местом"""
    place = dict(row)

    # Сериализуем даты
    for key, value in place.items():
        if hasattr(value, 'isoformat'):
            place[key] = value.isoformat()

    # Обработка категорий
    place['categories_list'] = process_categories(place.get('categories'))

    # ОБНОВЛЕННАЯ ЛОГИКА ДЛЯ PHOTO_URL - ПРОЩЕ!
    photo_url = place.get('photo_url') or place.get('main_photo_url')

    # Если photo_url не пустая строка и не None
    if photo_url and isinstance(photo_url, str) and photo_url.strip():
        place['photo_url'] = photo_url.strip()
    else:
        place['photo_url'] = None

    # ГАРАНТИРУЕМ, что title всегда есть
    if not place.get('title') and place.get('user_title'):
        place['title'] = place['user_title']

    if place.get('description'):
        import re
        # Удаляем все HTML теги, оставляем только текст
        clean_desc = re.sub(r'<[^>]+>', '', place['description'])
        # Убираем лишние пробелы
        clean_desc = ' '.join(clean_desc.split())
        # Обрезаем если слишком длинное
        if len(clean_desc) > 200:
            clean_desc = clean_desc[:197] + '...'
        place['description'] = clean_desc
    return place

# Контекстный процессор для определения активной страницы
@app.context_processor
def inject_navbar_vars():
    """Автоматически определяет активную страницу для подчеркивания"""
    def get_active_page():
        if request.endpoint == 'index':
            return 'index'
        elif request.endpoint == 'places_page':
            return 'places'
        elif request.endpoint == 'favorites_page':
            return 'favorites'
        elif request.endpoint == 'suggest_page':
            return 'suggest'
        elif request.endpoint == 'profile_page':
            return 'profile'
        elif request.endpoint == 'test_page':
            return 'test'
        elif request.endpoint == 'place_detail':
            return 'places'
        elif request.endpoint == 'visited_page':
            return 'visited'
        return None

    return {
        'active_page': get_active_page()
    }


@app.route('/')
def index():
    """Главная страница"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    if current_user.is_authenticated and current_user.role == 'admin':
        return redirect(url_for('admin_dashboard'))

    try:
        # 1. 4 случайных мест
        cur.execute("""
                    SELECT id, title, slug, categories,
                           COALESCE(main_photo_url, '') as photo_url,
                           COALESCE(description, '') as description,
                           COALESCE(address, '') as address,
                           COALESCE(timetable, '') as timetable
                    FROM places
                    WHERE NOT is_closed
                      AND main_photo_url IS NOT NULL
                    ORDER BY RANDOM()
                    LIMIT 3
                    """)
        random_places = [process_place_row(row) for row in cur.fetchall()]

        # 2. Все настроения
        cur.execute("SELECT id, name FROM moods ORDER BY id")
        moods = cur.fetchall()

        # 3. Первые 10 мест
        cur.execute("""
                    SELECT id, title, slug, categories,
                           COALESCE(main_photo_url, '') as photo_url,
                           COALESCE(description, '') as description,
                           COALESCE(address, '') as address,
                           COALESCE(timetable, '') as timetable
                    FROM places
                    WHERE NOT is_closed
                    ORDER BY RANDOM()
                    LIMIT 10
                    """)
        all_places = [process_place_row(row) for row in cur.fetchall()]

        cur.close()
        conn.close()

        return render_template('index.html',
                               random_places=random_places,
                               moods=moods,
                               all_places=all_places)

    except Exception as e:
        print(f"Ошибка в index(): {e}")
        traceback.print_exc()
        return "Ошибка сервера", 500

@app.route('/api/random-places')
def get_random_places():
    """API для получения случайных мест"""
    limit = request.args.get('limit', 5, type=int)

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        cur.execute("""
                    SELECT id, title, slug, categories,
                           COALESCE(main_photo_url, '') as photo_url,
                           COALESCE(description, '') as description,
                           COALESCE(address, '') as address,
                           COALESCE(timetable, '') as timetable
                    FROM places
                    WHERE NOT is_closed
                      AND main_photo_url IS NOT NULL
                    ORDER BY RANDOM()
                    LIMIT %s
                    """, (limit,))

        places = [process_place_row(row) for row in cur.fetchall()]

        return jsonify({'success': True, 'places': places})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()

@app.route('/api/all-places')
def get_all_places():
    """API для получения всех мест с пагинацией"""
    limit = request.args.get('limit', 10, type=int)
    offset = request.args.get('offset', 0, type=int)

    # Получаем список уже загруженных ID из запроса
    exclude_ids_str = request.args.get('exclude_ids', '')
    exclude_ids = []
    if exclude_ids_str:
        exclude_ids = [int(id.strip()) for id in exclude_ids_str.split(',') if id.strip()]

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        # Общее количество мест
        cur.execute("SELECT COUNT(*) as total FROM places WHERE NOT is_closed")
        total_count = cur.fetchone()['total']

        # Если есть исключаемые ID, строим запрос с условием
        if exclude_ids:
            # Преобразуем список ID в строку для SQL
            exclude_ids_str = ','.join(map(str, exclude_ids))
            cur.execute(f"""
                        SELECT id, title, slug, categories,
                               COALESCE(main_photo_url, '') as photo_url,
                               COALESCE(description, '') as description,
                               COALESCE(address, '') as address,
                               COALESCE(timetable, '') as timetable
                        FROM places
                        WHERE NOT is_closed
                          AND id NOT IN ({exclude_ids_str})
                        ORDER BY RANDOM()
                        LIMIT %s
                        """, (limit,))
        else:
            # Простой случайный запрос без исключений
            cur.execute("""
                        SELECT id, title, slug, categories,
                               COALESCE(main_photo_url, '') as photo_url,
                               COALESCE(description, '') as description,
                               COALESCE(address, '') as address,
                               COALESCE(timetable, '') as timetable
                        FROM places
                        WHERE NOT is_closed
                        ORDER BY RANDOM()
                        LIMIT %s
                        """, (limit,))

        places = [process_place_row(row) for row in cur.fetchall()]

        # Определяем, есть ли еще места для загрузки
        if exclude_ids:
            # Количество оставшихся мест (без уже показанных)
            cur.execute(f"""
                        SELECT COUNT(*) as remaining 
                        FROM places 
                        WHERE NOT is_closed 
                          AND id NOT IN ({exclude_ids_str})
                        """)
        else:
            cur.execute("SELECT COUNT(*) as remaining FROM places WHERE NOT is_closed")

        remaining_count = cur.fetchone()['remaining']
        has_more = remaining_count > len(places)

        return jsonify({
            'success': True,
            'places': places,
            'total': total_count,
            'remaining': remaining_count,
            'has_more': has_more
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()


@app.route('/api/filter-by-mood')
def filter_by_mood():
    """Фильтрация по настроению (случайный порядок)"""
    mood_id = request.args.get('mood_id', type=int)
    limit = request.args.get('limit', 10, type=int)

    cache_key = request.args.get('cache_key')

    # Получаем исключаемые ID (уже показанные места)
    exclude_ids_str = request.args.get('exclude_ids', '')
    exclude_ids = []
    if exclude_ids_str:
        exclude_ids = [int(id.strip()) for id in exclude_ids_str.split(',') if id.strip()]

    print(f"DEBUG: Фильтрация по настроению {mood_id}, limit={limit}, exclude_ids={exclude_ids}")

    if not mood_id:
        return jsonify({'success': False, 'error': 'Не указано настроение'})

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        # Общее количество мест для этого настроения
        cur.execute("""
                    SELECT COUNT(*) as total
                    FROM find_places_by_mood(%s)
                    """, (mood_id,))
        total_info = cur.fetchone()
        total_count = total_info['total'] if total_info else 0

        # Если есть ID для исключения, строим запрос с условием NOT IN
        if exclude_ids:
            # Преобразуем список ID в строку для SQL
            exclude_ids_str = ','.join(map(str, exclude_ids))

            # Оставшееся количество мест (без исключенных)
            cur.execute(f"""
                        SELECT COUNT(*) as remaining 
                        FROM find_places_by_mood(%s)
                        WHERE place_id NOT IN ({exclude_ids_str})
                        """, (mood_id,))
            remaining_info = cur.fetchone()
            remaining_count = remaining_info['remaining'] if remaining_info else 0

            # Получаем места с исключением уже показанных и в случайном порядке
            cur.execute(f"""
                        SELECT place_id, title, slug, categories,
                               match_score, match_type,
                               COALESCE(
                                       (SELECT main_photo_url
                                        FROM places p2
                                        WHERE p2.id = place_id AND NOT p2.is_closed
                                       ), ''
                               ) as photo_url,
                               COALESCE(
                                       (SELECT address
                                        FROM places p2
                                        WHERE p2.id = place_id AND NOT p2.is_closed
                                       ), ''
                               ) as address,
                               COALESCE(
                                       (SELECT timetable
                                        FROM places p2
                                        WHERE p2.id = place_id AND NOT p2.is_closed
                                       ), ''
                               ) as timetable,
                               COALESCE(
                                       (SELECT description
                                        FROM places p2
                                        WHERE p2.id = place_id AND NOT p2.is_closed
                                       ), ''
                               ) as description
                        FROM find_places_by_mood(%s)
                        WHERE place_id NOT IN ({exclude_ids_str})
                        ORDER BY RANDOM()  -- Случайный порядок
                        LIMIT %s
                        """, (mood_id, limit))
        else:
            # Если исключений нет, просто случайный порядок
            remaining_count = total_count

            cur.execute("""
                        SELECT place_id, title, slug, categories,
                               match_score, match_type,
                               COALESCE(
                                       (SELECT main_photo_url
                                        FROM places p2
                                        WHERE p2.id = place_id AND NOT p2.is_closed
                                       ), ''
                               ) as photo_url,
                               COALESCE(
                                       (SELECT address
                                        FROM places p2
                                        WHERE p2.id = place_id AND NOT p2.is_closed
                                       ), ''
                               ) as address,
                               COALESCE(
                                       (SELECT timetable
                                        FROM places p2
                                        WHERE p2.id = place_id AND NOT p2.is_closed
                                       ), ''
                               ) as timetable,
                               COALESCE(
                                       (SELECT description
                                        FROM places p2
                                        WHERE p2.id = place_id AND NOT p2.is_closed
                                       ), ''
                               ) as description
                        FROM find_places_by_mood(%s)
                        ORDER BY RANDOM()  -- Случайный порядок
                        LIMIT %s
                        """, (mood_id, limit))

        results = cur.fetchall()
        print(f"DEBUG: Найдено {len(results)} мест")

        places = []
        for row in results:
            place = dict(row)
            # Переименовываем place_id в id для единообразия
            place['id'] = place.pop('place_id')
            places.append(process_place_row(place))

        # Получаем информацию о настроении
        cur.execute("SELECT name FROM moods WHERE id = %s", (mood_id,))
        mood_info = cur.fetchone()

        # Определяем, есть ли еще места для загрузки
        has_more = remaining_count > len(places)

        return jsonify({
            'success': True,
            'mood_id': mood_id,
            'mood_name': mood_info['name'] if mood_info else f'Настроение {mood_id}',
            'places': places,
            'total': total_count,
            'remaining': remaining_count,
            'has_more': has_more
        })

    except Exception as e:
        print(f"Ошибка в filter_by_mood: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()

@app.route('/place/<int:place_id>')
def place_detail(place_id):
    """Детальная страница места"""

    from_page = request.args.get('from', 'places')

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        # Получаем полную информацию о месте
        cur.execute("""
                    SELECT *
                    FROM places
                    WHERE id = %s
                    """, (place_id,))

        place = cur.fetchone()

        if not place:
            return "Место не найдено", 404

        place_dict = dict(place)

        # ============ ОБНОВЛЕННЫЙ КОД ДЛЯ ВСЕХ ФОТОГРАФИЙ ============

        # 1. Собираем ВСЕ фотографии из разных источников
        all_photos = []

        # 1.1 Главная фотография (если есть)
        if place_dict.get('main_photo_url'):
            all_photos.append({
                'url': place_dict['main_photo_url'],
                'type': 'main',
                'description': 'Главное фото'
            })


        # 1.2 Фотографии из поля photos
        if place_dict.get('photos'):
            try:
                photos_data = place_dict['photos']

                # Если это JSON-строка
                if isinstance(photos_data, str):
                    try:
                        photos_data = json.loads(photos_data)
                    except:
                        pass

                # Если это список
                if isinstance(photos_data, list):
                    for i, item in enumerate(photos_data):
                        if isinstance(item, str) and item.strip():  # любая непустая строка
                            all_photos.append({
                                'url': item,
                                'type': 'gallery',
                                'description': f'Фото {i+1}'
                            })
                        elif isinstance(item, dict) and item.get('url'):
                            all_photos.append({
                                'url': item['url'],
                                'type': 'gallery',
                                'description': item.get('description', f'Фото {i+1}')
                            })

                # Если это одна строка с URL (не список)
                elif isinstance(photos_data, str) and photos_data.strip():
                    all_photos.append({
                        'url': photos_data,
                        'type': 'gallery',
                        'description': 'Дополнительное фото'
                    })

            except Exception as e:
                print(f"Ошибка при обработке поля photos: {e}")

        # 1.3 Извлекаем фотографии из текста описания (body_text)
        clean_body_text = place_dict.get('body_text', '')
        if clean_body_text:
            try:
                # Извлекаем фотографии из текста
                import re
                img_pattern = r'<img[^>]+src="([^">]+)"'
                img_matches = re.findall(img_pattern, clean_body_text)

                for img_url in img_matches:
                    if img_url.startswith('http') and img_url not in [p['url'] for p in all_photos]:
                        all_photos.append({
                            'url': img_url,
                            'type': 'from_text',
                            'description': 'Фото из описания'
                        })

                # УДАЛЯЕМ ВСЕ ТЕГИ <img> ИЗ ТЕКСТА
                clean_body_text = re.sub(r'<img[^>]*>', '', clean_body_text)

                # Также удаляем пустые параграфы, которые могли остаться после удаления img
                clean_body_text = re.sub(r'<p>\s*</p>', '', clean_body_text)
                clean_body_text = re.sub(r'<div>\s*</div>', '', clean_body_text)

            except Exception as e:
                print(f"Ошибка при очистке текста от фотографий: {e}")

        # 2. Обрабатываем категории
        category_names = []
        if place_dict.get('categories'):
            try:
                categories_list = process_categories(place_dict['categories'])
                if categories_list:
                    for slug in categories_list:
                        if isinstance(slug, str):
                            cur.execute("SELECT name FROM categories_api WHERE slug = %s", (slug,))
                            cat_row = cur.fetchone()
                            if cat_row:
                                category_names.append(cat_row['name'])
            except Exception as e:
                print(f"Ошибка при обработке категорий: {e}")

        # СОЗДАЕМ gallery_photos - все фото КРОМЕ главного
        gallery_photos = []
        if all_photos and len(all_photos) > 0:
            # Ищем главное фото (тип 'main')
            main_photo = None
            for photo in all_photos:
                if photo.get('type') == 'main':
                    main_photo = photo
                else:
                    gallery_photos.append(photo)

            # Если главное фото не найдено, но есть фото, берем первое для шапки
            if not main_photo and all_photos:
                main_photo = all_photos[0]
                # Убираем его из галереи, если он там есть
                gallery_photos = [p for p in gallery_photos if p['url'] != main_photo['url']]

        # 3. Обрабатываем subway
        subway_info = []
        if place_dict.get('subway'):
            try:
                subway_data = place_dict['subway']
                if isinstance(subway_data, str):
                    subway_data = json.loads(subway_data)

                if isinstance(subway_data, list):
                    for station in subway_data[:5]:
                        if isinstance(station, dict):
                            subway_info.append({
                                'name': station.get('name', ''),
                                'color': station.get('color', '#cccccc'),
                                'distance': station.get('distance_km')
                            })
            except:
                pass

        # 4. Обрабатываем координаты
        coords_info = {}
        if place_dict.get('coords'):
            try:
                coords_data = place_dict['coords']
                if isinstance(coords_data, str):
                    coords_data = json.loads(coords_data)

                if isinstance(coords_data, dict):
                    coords_info = coords_data
            except:
                pass

        # 5. Обрабатываем текст описания (убираем HTML теги для чистого текста)
        clean_description = ""
        if place_dict.get('description'):
            # Убираем HTML теги, оставляем чистый текст
            import re
            clean_description = re.sub(r'<[^>]+>', '', place_dict['description'])

        cur.close()
        conn.close()

        return render_template('place_detail.html',
                               place=place_dict,
                               all_photos=all_photos,
                               gallery_photos=gallery_photos,
                               category_names=category_names,
                               subway_info=subway_info,
                               coords_info=coords_info,
                               clean_body_text=clean_body_text,
                               from_page=from_page)

    except Exception as e:
        print(f"Ошибка в place_detail: {e}")
        traceback.print_exc()
        return "Ошибка сервера", 500

# Добавим новый маршрут для страницы теста
@app.route('/test')
def test_page():
    """Страница прохождения теста"""
    return render_template('test.html')

# API для начала теста
@app.route('/api/test/start')
def start_test():
    """Начинает новый тест и возвращает первый вопрос"""
    conn = get_db_connection()
    try:
        # Инициализируем состояние
        state = test_logic.get_initial_state()

        # Получаем первый вопрос
        next_q = test_logic.get_next_question(state)
        if not next_q:
            return jsonify({'success': False, 'error': 'No active paths'})

        # Загружаем вопрос
        question = test_logic.load_question(conn, 'mood_flow_v1', next_q['question_seq'])
        if not question:
            return jsonify({'success': False, 'error': 'Question not found'})

        # Загружаем варианты
        options = test_logic.load_options_for_question(conn, question['id'])

        # Сериализуем состояние
        serializable_state = {
            'active_paths': [
                {
                    'id': path['id'],
                    'current_question_seq': path['current_question_seq'],
                    'mood_ids': list(path['mood_ids']),
                    'primary_slugs': list(path['primary_slugs']),
                    'secondary_conditions': path['secondary_conditions'],
                    'negative_keywords': list(path['negative_keywords']),
                    'answers': path['answers'],
                    'parent_path_id': path.get('parent_path_id')
                }
                for path in state['active_paths']
            ],
            'completed_paths': [],  # Начальное состояние - нет завершенных путей
            'next_path_id': state['next_path_id']
        }

        return jsonify({
            'success': True,
            'state': serializable_state,
            'question': {
                'path_id': next_q['path_id'],
                'question': question,
                'options': options
            }
        })

    except Exception as e:
        print(f"ERROR in start_test: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()

# API для обработки ответа
@app.route('/api/test/answer', methods=['POST'])
@login_required
def process_test_answer():
    """Обрабатывает ответ пользователя и возвращает следующий вопрос или результаты"""
    conn = get_db_connection()
    try:
        data = request.json
        print(f"DEBUG: Received answer data: {data}")

        # Восстанавливаем состояние
        state = {
            'active_paths': [],
            'completed_paths': data.get('state', {}).get('completed_paths', []),
            'next_path_id': data.get('state', {}).get('next_path_id', 2)
        }

        # Восстанавливаем активные пути с множествами
        for path_data in data.get('state', {}).get('active_paths', []):
            path = {
                'id': path_data['id'],
                'current_question_seq': path_data['current_question_seq'],
                'mood_ids': set(path_data['mood_ids']),
                'primary_slugs': set(path_data['primary_slugs']),
                'secondary_conditions': path_data['secondary_conditions'],
                'negative_keywords': set(path_data['negative_keywords']),
                'answers': path_data['answers'],
                'parent_path_id': path_data.get('parent_path_id')
            }
            state['active_paths'].append(path)

        # Обрабатываем ответ
        updated_state = test_logic.process_answer(
            conn,
            state,
            data.get('path_id'),
            data.get('question_id'),
            data.get('option_ids', [])
        )

        # Проверяем, завершен ли тест
        if test_logic.is_test_completed(updated_state):
            # Получаем все результаты
            all_places = test_logic.get_all_results(updated_state)

            # Обрабатываем каждое место с учетом сериализации дат
            processed_places = []
            for place in all_places:
                # Конвертируем Row/Dict в dict и обрабатываем даты
                place_dict = dict(place)

                # Сериализуем даты, если они есть
                for key, value in place_dict.items():
                    if hasattr(value, 'isoformat'):  # Для datetime объектов
                        place_dict[key] = value.isoformat()

                processed_place = process_place_row(place_dict)
                processed_place['path_id'] = place.get('path_id')
                processed_places.append(processed_place)

            # Сериализуем состояние - для завершенных путей структура другая
            serializable_state = {
                'active_paths': [],
                'completed_paths': [
                    {
                        'id': path['id'],
                        'parent_path_id': path.get('parent_path_id'),
                        'criteria': path.get('criteria', {}),
                        'places': path.get('places', []),
                        'answers': path.get('answers', [])
                    }
                    for path in updated_state['completed_paths']
                ],
                'next_path_id': updated_state['next_path_id']
            }

            return jsonify({
                'success': True,
                'finished': True,
                'places': processed_places,
                'state': serializable_state
            })

        else:
            # Получаем следующий вопрос
            next_q = test_logic.get_next_question(updated_state)
            if not next_q:
                return jsonify({'success': False, 'error': 'No next question found'})

            # Загружаем вопрос
            question = test_logic.load_question(conn, 'mood_flow_v1', next_q['question_seq'])
            options = test_logic.load_options_for_question(conn, question['id'])

            # Сериализуем состояние - для активных путей есть current_question_seq
            serializable_state = {
                'active_paths': [
                    {
                        'id': path['id'],
                        'current_question_seq': path['current_question_seq'],
                        'mood_ids': list(path['mood_ids']) if path.get('mood_ids') else [],
                        'primary_slugs': list(path['primary_slugs']) if path.get('primary_slugs') else [],
                        'secondary_conditions': path['secondary_conditions'],
                        'negative_keywords': list(path['negative_keywords']) if path.get('negative_keywords') else [],
                        'answers': path['answers'],
                        'parent_path_id': path.get('parent_path_id')
                    }
                    for path in updated_state['active_paths']
                ],
                'completed_paths': [
                    {
                        'id': path['id'],
                        'parent_path_id': path.get('parent_path_id'),
                        'criteria': path.get('criteria', {}),
                        'places': path.get('places', []),
                        'answers': path.get('answers', [])
                    }
                    for path in updated_state['completed_paths']
                ],
                'next_path_id': updated_state['next_path_id']
            }

            return jsonify({
                'success': True,
                'finished': False,
                'state': serializable_state,
                'question': {
                    'path_id': next_q['path_id'],
                    'question': question,
                    'options': options
                }
            })

    except Exception as e:
        print(f"ERROR in process_test_answer: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()

@app.route('/api/debug/test-search')
def debug_test_search():
    """Диагностический поиск мест по критериям теста"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        # Критерии из лога
        primary_slugs = ['bar', 'clubs', 'concert-hall']
        mood_id = 4
        secondary_conditions = [{
            'slug': 'amusement',
            'keywords': [
                {'kw': 'ночн', 'in_title': True, 'is_negative': False, 'in_description': False},
                {'kw': 'вечеринка', 'in_title': True, 'is_negative': False, 'in_description': False}
            ]
        }]

        # 1. Проверяем места по каждой категории отдельно
        category_stats = {}
        for slug in primary_slugs:
            cur.execute("""
                        SELECT COUNT(*) as count
                        FROM places
                        WHERE NOT is_closed
                          AND categories @> %s::jsonb
                        """, (json.dumps([slug]),))
            result = cur.fetchone()
            category_stats[slug] = result['count'] if result else 0

        # 2. Проверяем места по ключевым словам
        keyword_stats = {}
        for keyword in ['ночн', 'вечеринка']:
            cur.execute("""
                        SELECT COUNT(*) as count
                        FROM places
                        WHERE NOT is_closed
                          AND title ILIKE %s
                        """, (f'%{keyword}%',))
            result = cur.fetchone()
            keyword_stats[keyword] = result['count'] if result else 0

        # 3. Проверяем функцию find_places_by_mood
        cur.execute("SELECT * FROM find_places_by_mood(%s)", (mood_id,))
        mood_results = cur.fetchall()

        # 4. Проверяем вручную поиск по категориям и ключевым словам
        cur.execute("""
                    SELECT p.id, p.title, p.slug, p.categories
                    FROM places p
                    WHERE NOT p.is_closed
                      AND (
                        EXISTS (
                            SELECT 1 FROM jsonb_array_elements_text(p.categories) cat
                            WHERE cat IN ('bar', 'clubs', 'concert-hall')
                        )
                            OR p.title ILIKE '%ночн%'
                            OR p.title ILIKE '%вечеринка%'
                        )
                    ORDER BY RANDOM()
                    LIMIT 20
                    """)
        manual_results = [dict(row) for row in cur.fetchall()]

        # 5. Проверяем структуру категорий в базе
        cur.execute("""
                    SELECT DISTINCT jsonb_array_elements_text(categories) as category
                    FROM places
                    WHERE NOT is_closed
                    ORDER BY category
                    """)
        all_categories = [row['category'] for row in cur.fetchall()]

        # 6. Ищем места с категорией amusement
        cur.execute("""
                    SELECT COUNT(*) as count
                    FROM places
                    WHERE NOT is_closed
                      AND categories @> '["amusement"]'::jsonb
                    """)
        amusement_count = cur.fetchone()['count']

        # 7. Ищем конкретные места с категориями бар/клубы
        cur.execute("""
                    SELECT p.id, p.title, p.slug, p.categories
                    FROM places p
                    WHERE NOT p.is_closed
                      AND (
                        EXISTS (
                            SELECT 1 FROM jsonb_array_elements_text(p.categories) cat
                            WHERE cat IN ('bar', 'clubs', 'concert-hall')
                        )
                        )
                    LIMIT 10
                    """)
        bar_club_places = [dict(row) for row in cur.fetchall()]

        return jsonify({
            'success': True,
            'category_stats': category_stats,
            'keyword_stats': keyword_stats,
            'mood_results_count': len(mood_results),
            'manual_results_count': len(manual_results),
            'manual_results': manual_results,
            'all_categories_count': len(all_categories),
            'all_categories_sample': all_categories[:20],  # первые 20
            'amusement_category_count': amusement_count,
            'bar_club_places': bar_club_places,
            'debug_info': {
                'primary_slugs': primary_slugs,
                'mood_id': mood_id,
                'secondary_conditions': secondary_conditions
            }
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()})
    finally:
        cur.close()
        conn.close()


# ============ МАРШРУТЫ ДЛЯ СТРАНИЦ ============

@app.route('/register')
def register_page():
    """Страница регистрации"""
    if current_user.is_authenticated:
        return redirect(url_for('profile_page'))
    return render_template('auth/register.html')

@app.route('/login')
def login_page():
    """Страница входа"""
    if current_user.is_authenticated:
        return redirect(url_for('profile_page'))
    return render_template('auth/login.html')

@app.route('/profile')
@login_required
def profile_page():
    """Личный кабинет пользователя"""
    return render_template('user_profile/profile.html', current_user=current_user)

@app.route('/logout')
@login_required
def logout():
    """Выход из системы"""
    logout_user()
    return redirect(url_for('index'))

# Страница со всеми предложениями пользователя
@app.route('/profile/suggestions')
@login_required
def profile_suggestions_page():
    return render_template('user_profile/profile_suggestions.html')

# Страница со всеми сообщениями об ошибках пользователя
@app.route('/profile/reports')
@login_required
def profile_reports_page():
    return render_template('user_profile/profile_reports.html')

# Детальная страница предложения
@app.route('/suggestion/<int:suggestion_id>')
@login_required
def suggestion_detail_page(suggestion_id):
    return render_template('user_profile/suggestion_detail.html',
                           suggestion_id=suggestion_id)

# Страница редактирования предложения
@app.route('/suggestion/<int:suggestion_id>/edit')
@login_required
def suggestion_edit_page(suggestion_id):
    return render_template('user_profile/suggestion_edit.html',
                           suggestion_id=suggestion_id)

# Детальная страница сообщения об ошибке
@app.route('/report/<int:report_id>')
@login_required
def report_detail_page(report_id):
    return render_template('user_profile/report_detail.html',
                           report_id=report_id)


@app.route('/admin/suggestions/<int:suggestion_id>')
@login_required
@admin_required
def admin_suggestion_detail(suggestion_id):
    """Страница модерации конкретного предложения"""
    return render_template('admin/suggestion_detail.html', suggestion_id=suggestion_id)

@app.route('/admin/reports/<int:report_id>')
@login_required
@admin_required
def admin_report_detail(report_id):
    """Страница модерации конкретного сообщения об ошибке"""
    return render_template('admin/report_detail.html', report_id=report_id)

# ============ API МАРШРУТЫ ============

@app.route('/api/register', methods=['POST'])
def register():
    """Регистрация нового пользователя"""
    conn = get_db_connection()
    try:
        data = request.json

        # Проверяем обязательные поля
        if not data.get('email') or not data.get('password') or not data.get('username'):
            return jsonify({'success': False, 'error': 'Заполните все обязательные поля'})

        # Валидация email
        email = data['email'].lower().strip()
        if not is_valid_email(email):
            return jsonify({'success': False, 'error': 'Введите корректный email'})

        # Валидация имени (username)
        username = data['username'].strip()
        if not is_valid_name(username):
            return jsonify({'success': False, 'error': 'Имя должно содержать только русские или английские буквы и не превышать 30 символов'})

        # Валидация пароля
        password = data['password']
        if not is_strong_password(password):
            return jsonify({'success': False, 'error': 'Пароль должен содержать минимум 6 символов, включая хотя бы одну заглавную и одну строчную букву (латиницу или кириллицу)'})

        # Хешируем пароль
        password_hash = generate_password_hash(password)

        # Проверяем, существует ли пользователь с таким email
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cur.fetchone():
            return jsonify({'success': False, 'error': 'Пользователь с таким email уже существует'})

        # Проверяем, не занят ли username
        cur.execute("SELECT id FROM users WHERE username = %s", (username,))
        if cur.fetchone():
            return jsonify({'success': False, 'error': 'Это имя пользователя уже занято'})

        # Создаем пользователя
        cur.execute("""
                    INSERT INTO users (email, username, password_hash, role)
                    VALUES (%s, %s, %s, 'user')
                    RETURNING id, email, username, role, avatar_url, is_active
                    """, (email, username, password_hash))

        user_data = cur.fetchone()
        user = User(user_data)
        login_user(user, remember=True)

        conn.commit()
        return jsonify({
            'success': True,
            'message': 'Регистрация успешна! Добро пожаловать!'
        })

    except Exception as e:
        conn.rollback()
        print(f"Ошибка при регистрации: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': 'Внутренняя ошибка сервера. Попробуйте позже.'})
    finally:
        conn.close()

@app.route('/api/login', methods=['POST'])
def login():
    """Вход в систему"""
    conn = get_db_connection()
    try:
        data = request.json

        if not data.get('email') or not data.get('password'):
            return jsonify({'success': False, 'error': 'Заполните email и пароль'})

        email = data['email'].lower().strip()

        # Ищем пользователя
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("""
                    SELECT * FROM users
                    WHERE email = %s AND is_active = true
                    """, (email,))

        user_data = cur.fetchone()

        if not user_data:
            return jsonify({'success': False, 'error': 'Пользователь не найден или аккаунт деактивирован'})

        # Проверяем пароль
        if not check_password_hash(user_data['password_hash'], data['password']):
            return jsonify({'success': False, 'error': 'Неверный пароль'})

        # Создаем объект пользователя для Flask-Login
        user = User(user_data)
        login_user(user, remember=data.get('remember', False))

        # Если пользователь - админ, редирект на админ-панель
        if user_data['role'] == 'admin':
            return jsonify({
                'success': True,
                'message': 'Вход выполнен успешно',
                'redirect': '/admin'  # Добавляем редирект
            })
        else:
            return jsonify({
                'success': True,
                'message': 'Вход выполнен успешно'
            })

    except Exception as e:
        print(f"Ошибка при входе: {e}")
        return jsonify({'success': False, 'error': 'Внутренняя ошибка сервера. Попробуйте позже.'})
    finally:
        conn.close()

@app.route('/api/forgot-password', methods=['POST'])
def forgot_password():
    """Запрос на восстановление пароля"""
    # Пока просто заглушка
    data = request.json
    email = data.get('email', '')

    return jsonify({
        'success': True,
        'message': f'Инструкции по восстановлению пароля отправлены на {email} (функция в разработке)'
    })

@app.route('/api/profile/data')
@login_required
def get_profile_data():
    """Получение данных профиля пользователя"""
    conn = get_db_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("""
                    SELECT created_at, updated_at
                    FROM users
                    WHERE id = %s
                    """, (current_user.id,))

        user_data = cur.fetchone()

        if user_data:
            return jsonify({
                'success': True,
                'registration_date': user_data['created_at'].isoformat() if user_data['created_at'] else None,
                'last_updated': user_data['updated_at'].isoformat() if user_data['updated_at'] else None
            })
        else:
            return jsonify({'success': False, 'error': 'Пользователь не найден'})

    except Exception as e:
        print(f"Ошибка при получении данных профиля: {e}")
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()

# GET /api/user/suggestions — список предложений текущего пользователя
@app.route('/api/user/suggestions')
@login_required
def get_user_suggestions():
    """Получение списка предложений текущего пользователя"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        status = request.args.get('status', 'all')
        limit = request.args.get('limit', per_page)  # для блока "последние" без пагинации
        offset = (page - 1) * per_page

        query = """
                SELECT
                    ps.id, ps.user_title, ps.status, ps.created_at,
                    ps.admin_comment, ps.created_place_id,
                    p.title as place_title, p.slug as place_slug
                FROM place_suggestions ps
                         LEFT JOIN places p ON ps.created_place_id = p.id
                WHERE ps.user_id = %s \
                """
        params = [current_user.id]

        if status != 'all':
            query += " AND ps.status = %s"
            params.append(status)

        # Подсчёт общего количества
        count_query = f"SELECT COUNT(*) as total FROM ({query}) as t"
        cur.execute(count_query, params)
        total = cur.fetchone()['total']

        # Добавляем сортировку и лимит
        query += " ORDER BY ps.created_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        cur.execute(query, params)
        suggestions = []
        for row in cur.fetchall():
            s = dict(row)
            s['created_at'] = s['created_at'].isoformat() if s['created_at'] else None
            suggestions.append(s)

        total_pages = (total + per_page - 1) // per_page if per_page > 0 else 1

        return jsonify({
            'success': True,
            'suggestions': suggestions,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'total_pages': total_pages,
                'has_next': page < total_pages,
                'has_prev': page > 1
            }
        })
    except Exception as e:
        print(f"Ошибка при получении предложений пользователя: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()

# GET /api/suggestions/<id> — детальная информация о предложении (для владельца или админа)
@app.route('/api/suggestions/<int:suggestion_id>')
@login_required
def get_suggestion_detail_user(suggestion_id):
    """Детальная информация о предложении для владельца или админа"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        cur.execute("""
                    SELECT
                        ps.*,
                        u.username as user_username,
                        u.email as user_email,
                        p.title as place_title,
                        p.slug as place_slug,
                        p.id as place_id,
                        array_agg(DISTINCT c.name) as user_category_names
                    FROM place_suggestions ps
                             LEFT JOIN users u ON ps.user_id = u.id
                             LEFT JOIN place_suggestion_user_categories psuc ON ps.id = psuc.suggestion_id
                             LEFT JOIN categories_api c ON psuc.category_id = c.id
                             LEFT JOIN places p ON ps.created_place_id = p.id
                    WHERE ps.id = %s
                    GROUP BY ps.id, u.id, p.id
                    """, (suggestion_id,))

        suggestion = cur.fetchone()
        if not suggestion:
            return jsonify({'success': False, 'error': 'Предложение не найдено'}), 404

        # Проверка прав: либо владелец, либо админ
        if suggestion['user_id'] != current_user.id and current_user.role != 'admin':
            return jsonify({'success': False, 'error': 'Доступ запрещён'}), 403

        suggestion_dict = dict(suggestion)

        # Обработка JSON полей
        for field in ['user_photos', 'moderated_photos', 'moderated_coords']:
            if suggestion_dict.get(field):
                try:
                    if isinstance(suggestion_dict[field], str):
                        suggestion_dict[field] = json.loads(suggestion_dict[field])
                except:
                    suggestion_dict[field] = []

        # Преобразование дат
        for date_field in ['created_at', 'updated_at']:
            if suggestion_dict.get(date_field):
                suggestion_dict[date_field] = suggestion_dict[date_field].isoformat()

        return jsonify({'success': True, 'suggestion': suggestion_dict})
    except Exception as e:
        print(f"Ошибка при получении деталей предложения: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()


# PUT /api/suggestions/<id> — обновление пользовательских данных предложения (только pending и владелец)
@app.route('/api/suggestions/<int:suggestion_id>', methods=['PUT'])
@login_required
def update_user_suggestion(suggestion_id):
    """Обновление пользовательских данных предложения (только для статуса pending)"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        # Проверяем существование и статус
        cur.execute("SELECT user_id, status FROM place_suggestions WHERE id = %s", (suggestion_id,))
        suggestion = cur.fetchone()
        if not suggestion:
            return jsonify({'success': False, 'error': 'Предложение не найдено'}), 404
        if suggestion['user_id'] != current_user.id:
            return jsonify({'success': False, 'error': 'Доступ запрещён'}), 403
        if suggestion['status'] != 'pending':
            return jsonify({'success': False, 'error': 'Редактирование доступно только для заявок на модерации'}), 400

        data = request.json

        # Поля, которые может редактировать пользователь
        updatable_fields = [
            'user_title', 'user_description', 'user_address',
            'user_timetable', 'user_phone', 'user_foreign_url'
        ]

        update_fields = []
        update_values = []

        for field in updatable_fields:
            if field in data:
                update_fields.append(f"{field} = %s")
                update_values.append(data[field])

        # Обновление фотографий: если передали новый список, заменяем
        if 'user_photos' in data:
            update_fields.append("user_photos = %s::jsonb")
            update_values.append(json.dumps(data['user_photos']))
            # Если есть новое главное фото (первое в списке)
            if data['user_photos']:
                update_fields.append("user_main_photo_url = %s")
                update_values.append(data['user_photos'][0])
            else:
                update_fields.append("user_main_photo_url = %s")
                update_values.append(None)

        if update_fields:
            update_query = f"""
                UPDATE place_suggestions
                SET {', '.join(update_fields)}, updated_at = NOW()
                WHERE id = %s
            """
            update_values.append(suggestion_id)
            cur.execute(update_query, tuple(update_values))

        # Обновление категорий пользователя
        if 'category_ids' in data:
            # Удаляем старые
            cur.execute("DELETE FROM place_suggestion_user_categories WHERE suggestion_id = %s", (suggestion_id,))
            # Добавляем новые
            for cat_id in data['category_ids']:
                cur.execute("""
                            INSERT INTO place_suggestion_user_categories (suggestion_id, category_id)
                            VALUES (%s, %s) ON CONFLICT DO NOTHING
                            """, (suggestion_id, cat_id))

        conn.commit()
        return jsonify({'success': True, 'message': 'Предложение успешно обновлено'})
    except Exception as e:
        conn.rollback()
        print(f"Ошибка при обновлении предложения: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()


@app.route('/api/suggestions/<int:suggestion_id>/photo', methods=['POST'])
@login_required
def add_suggestion_photo(suggestion_id):
    """Добавление фотографии к предложению (файл или URL)"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        # Проверка прав и статуса
        cur.execute("SELECT user_id, status, user_photos FROM place_suggestions WHERE id = %s", (suggestion_id,))
        suggestion = cur.fetchone()
        if not suggestion:
            return jsonify({'success': False, 'error': 'Предложение не найдено'}), 404
        if suggestion['user_id'] != current_user.id and current_user.role != 'admin':
            return jsonify({'success': False, 'error': 'Доступ запрещён'}), 403
        if suggestion['status'] != 'pending':
            return jsonify({'success': False, 'error': 'Фото можно добавлять только к заявкам на модерации'}), 400

        # Текущий список фото
        current_photos = suggestion['user_photos']
        if current_photos is None:
            current_photos = []
        elif isinstance(current_photos, str):
            try:
                current_photos = json.loads(current_photos)
            except:
                current_photos = []

        new_photo_url = None

        # Случай 1: загружен файл
        if 'photo' in request.files:
            file = request.files['photo']
            if file and file.filename:
                photo_url = save_uploaded_file(file, 'suggestions')
                if not photo_url:
                    return jsonify({'success': False, 'error': 'Не удалось сохранить файл'})
                new_photo_url = photo_url

        # Случай 2: передан URL в JSON
        elif request.is_json:
            data = request.get_json()
            if data and 'photo_url' in data:
                url = data['photo_url'].strip()
                if url:
                    new_photo_url = url

        if not new_photo_url:
            return jsonify({'success': False, 'error': 'Не передано фото (файл или URL)'})

        # Добавляем, если ещё нет
        if new_photo_url not in current_photos:
            current_photos.append(new_photo_url)

            cur.execute("""
                UPDATE place_suggestions
                SET user_photos = %s::jsonb,
                    user_main_photo_url = COALESCE(user_main_photo_url, %s),
                    updated_at = NOW()
                WHERE id = %s
            """, (json.dumps(current_photos), new_photo_url, suggestion_id))

            conn.commit()
            return jsonify({'success': True, 'message': 'Фото добавлено', 'photo_url': new_photo_url})
        else:
            return jsonify({'success': False, 'error': 'Это фото уже есть в списке'})

    except Exception as e:
        conn.rollback()
        print(f"Ошибка при добавлении фото: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()

@app.route('/api/suggestions/<int:suggestion_id>/photo', methods=['DELETE'])
@login_required
def delete_suggestion_photo(suggestion_id):
    """Удаление фотографии из предложения (удаляет запись в БД и сам файл)"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        data = request.get_json()
        if not data or 'photo_url' not in data:
            return jsonify({'success': False, 'error': 'Не указан URL фото'}), 400

        photo_url = data['photo_url'].strip()

        cur.execute("SELECT user_id, status, user_photos FROM place_suggestions WHERE id = %s", (suggestion_id,))
        suggestion = cur.fetchone()
        if not suggestion:
            return jsonify({'success': False, 'error': 'Предложение не найдено'}), 404
        if suggestion['user_id'] != current_user.id and current_user.role != 'admin':
            return jsonify({'success': False, 'error': 'Доступ запрещён'}), 403
        if suggestion['status'] != 'pending':
            return jsonify({'success': False, 'error': 'Фото можно удалять только из заявок на модерации'}), 400

        current_photos = suggestion['user_photos']
        if current_photos is None:
            current_photos = []
        elif isinstance(current_photos, str):
            try:
                current_photos = json.loads(current_photos)
            except:
                current_photos = []

        if photo_url not in current_photos:
            return jsonify({'success': False, 'error': 'Фото не найдено в списке'}), 404

        current_photos.remove(photo_url)

        # Обновляем главное фото, если удалили его
        new_main = None
        if current_photos:
            cur.execute("SELECT user_main_photo_url FROM place_suggestions WHERE id = %s", (suggestion_id,))
            old_main = cur.fetchone()['user_main_photo_url']
            if old_main == photo_url:
                new_main = current_photos[0]
        else:
            new_main = None

        cur.execute("""
            UPDATE place_suggestions
            SET user_photos = %s::jsonb,
                user_main_photo_url = %s,
                updated_at = NOW()
            WHERE id = %s
        """, (json.dumps(current_photos), new_main, suggestion_id))

        # Физически удаляем файл, если это локальный файл
        if photo_url.startswith('/static/uploads/'):
            file_path = os.path.join(app.root_path, photo_url.lstrip('/'))
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception as e:
                    print(f"Не удалось удалить файл {file_path}: {e}")

        conn.commit()
        return jsonify({'success': True, 'message': 'Фото удалено'})

    except Exception as e:
        conn.rollback()
        print(f"Ошибка при удалении фото: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()


#  GET /api/reports/<id> — детальная информация о сообщении об ошибке (для владельца или админа)
@app.route('/api/reports/<int:report_id>')
@login_required
def get_report_detail_user(report_id):
    """Детальная информация о сообщении об ошибке для владельца или админа"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        cur.execute("""
                    SELECT
                        pr.*,
                        p.title as place_title,
                        p.slug as place_slug,
                        p.address as place_address,
                        u_mod.username as resolved_by_username
                    FROM place_reports pr
                             JOIN places p ON pr.place_id = p.id
                             LEFT JOIN users u_mod ON pr.resolved_by = u_mod.id
                    WHERE pr.id = %s
                    """, (report_id,))

        report = cur.fetchone()
        if not report:
            return jsonify({'success': False, 'error': 'Сообщение не найдено'}), 404

        # Проверка прав: владелец или админ
        if report['user_id'] != current_user.id and current_user.role != 'admin':
            return jsonify({'success': False, 'error': 'Доступ запрещён'}), 403

        report_dict = dict(report)
        for date_field in ['created_at', 'updated_at']:
            if report_dict.get(date_field):
                report_dict[date_field] = report_dict[date_field].isoformat()

        return jsonify({'success': True, 'report': report_dict})
    except Exception as e:
        print(f"Ошибка при получении деталей сообщения: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()

# PUT /api/reports/<id> — редактирование сообщения об ошибке пользователем (только pending)
@app.route('/api/reports/<int:report_id>', methods=['PUT'])
@login_required
def update_user_report(report_id):
    """Редактирование сообщения об ошибке (только для статуса pending)"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        cur.execute("SELECT user_id, status FROM place_reports WHERE id = %s", (report_id,))
        report = cur.fetchone()
        if not report:
            return jsonify({'success': False, 'error': 'Сообщение не найдено'}), 404
        if report['user_id'] != current_user.id:
            return jsonify({'success': False, 'error': 'Доступ запрещён'}), 403
        if report['status'] != 'pending':
            return jsonify({'success': False, 'error': 'Редактирование доступно только для сообщений на рассмотрении'}), 400

        data = request.json
        update_fields = []
        update_values = []

        if 'subject' in data:
            update_fields.append("subject = %s")
            update_values.append(data['subject'].strip()[:200])
        if 'message' in data:
            update_fields.append("message = %s")
            update_values.append(data['message'].strip()[:2000])

        if update_fields:
            update_fields.append("updated_at = NOW()")
            update_query = f"UPDATE place_reports SET {', '.join(update_fields)} WHERE id = %s"
            update_values.append(report_id)
            cur.execute(update_query, tuple(update_values))
            conn.commit()
            return jsonify({'success': True, 'message': 'Сообщение обновлено'})
        else:
            return jsonify({'success': False, 'error': 'Нет данных для обновления'})
    except Exception as e:
        conn.rollback()
        print(f"Ошибка при обновлении сообщения: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()

# GET /api/user/reports/stats — статистика по сообщениям об ошибках
@app.route('/api/user/reports/stats')
@login_required
def get_user_reports_stats():
    """Статистика сообщений об ошибках текущего пользователя"""
    conn = get_db_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("""
                    SELECT
                        COUNT(*) as total,
                        COUNT(*) FILTER (WHERE status = 'pending') as pending,
                        COUNT(*) FILTER (WHERE status = 'resolved') as resolved
                    FROM place_reports
                    WHERE user_id = %s
                    """, (current_user.id,))
        stats = cur.fetchone()
        return jsonify({
            'success': True,
            'total': stats['total'],
            'pending': stats['pending'],
            'resolved': stats['resolved']
        })
    except Exception as e:
        print(f"Ошибка получения статистики сообщений: {e}")
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()



@app.route('/api/profile/suggestions/stats')
@login_required
def get_suggestions_stats():
    """Получение статистики предложений пользователя"""
    conn = get_db_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Считаем предложения по статусам
        cur.execute("""
                    SELECT
                        COUNT(*) FILTER (WHERE status = 'pending') as pending,
                        COUNT(*) FILTER (WHERE status = 'approved') as approved,
                        COUNT(*) FILTER (WHERE status = 'rejected') as rejected,
                        COUNT(*) as total
                    FROM place_suggestions
                    WHERE user_id = %s
                    """, (current_user.id,))

        stats = cur.fetchone()

        return jsonify({
            'success': True,
            'pending': stats['pending'] if stats else 0,
            'approved': stats['approved'] if stats else 0,
            'rejected': stats['rejected'] if stats else 0,
            'total': stats['total'] if stats else 0
        })

    except Exception as e:
        print(f"Ошибка при получении статистики предложений: {e}")
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()


# API для получения списка доступных аватаров
@app.route('/api/avatars')
@login_required
def get_available_avatars():
    """Получение списка доступных аватаров"""
    # Предполагаем, что у вас есть папка static/avatars с изображениями
    import os

    avatars = []
    avatars_folder = os.path.join(app.root_path, 'static', 'avatars')

    # Проверяем существование папки
    if not os.path.exists(avatars_folder):
        # Создаем папку, если её нет
        os.makedirs(avatars_folder, exist_ok=True)
        print(f"Создана папка для аватаров: {avatars_folder}")

    # Ищем файлы аватаров
    allowed_extensions = ['.png', '.jpg', '.jpeg', '.gif', '.webp']

    try:
        for filename in os.listdir(avatars_folder):
            if any(filename.lower().endswith(ext) for ext in allowed_extensions):
                # Удаляем расширение файла для получения id
                avatar_id = os.path.splitext(filename)[0]
                avatars.append({
                    'id': avatar_id,
                    'url': f'/static/avatars/{filename}',
                    'name': avatar_id.replace('_', ' ').title()
                })
    except Exception as e:
        print(f"Ошибка при чтении папки аватаров: {e}")
        # Возвращаем дефолтные аватары, если папки нет
        for i in range(1, 7):
            avatars.append({
                'id': f'avatar{i}',
                'url': f'/static/avatars/avatar{i}.png',
                'name': f'Аватар {i}'
            })

    # Если аватаров нет, создаем список по умолчанию
    if not avatars:
        for i in range(1, 7):
            avatars.append({
                'id': f'avatar{i}',
                'url': f'/static/avatars/avatar{i}.png',
                'name': f'Аватар {i}'
            })

    return jsonify({'success': True, 'avatars': avatars})
@app.route('/api/profile/update', methods=['POST'])
@login_required
def update_profile():
    """Обновление данных профиля пользователя"""
    conn = get_db_connection()
    try:
        data = request.json

        if not data.get('username'):
            return jsonify({'success': False, 'error': 'Имя пользователя обязательно'})

        username = data['username'].strip()
        avatar_url = data.get('avatar_url')

        # Проверяем, не занят ли username другим пользователем
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("""
                    SELECT id FROM users
                    WHERE username = %s AND id != %s
                    """, (username, current_user.id))

        if cur.fetchone():
            return jsonify({'success': False, 'error': 'Это имя пользователя уже занято'})

        # Обновляем данные пользователя
        cur.execute("""
                    UPDATE users
                    SET username = %s, avatar_url = %s, updated_at = NOW()
                    WHERE id = %s
                    RETURNING id, email, username, avatar_url, role, is_active
                    """, (username, avatar_url, current_user.id))

        updated_user = cur.fetchone()
        conn.commit()

        # Обновляем данные в сессии Flask-Login
        if updated_user:
            # Создаем нового пользователя для обновления сессии
            user = User(updated_user)
            login_user(user)  # Обновляем сессию

            return jsonify({
                'success': True,
                'message': 'Профиль успешно обновлен',
                'user': {
                    'id': str(updated_user['id']),
                    'username': updated_user['username'],
                    'email': updated_user['email'],
                    'avatar_url': updated_user['avatar_url'],
                    'role': updated_user['role']
                }
            })
        else:
            return jsonify({'success': False, 'error': 'Пользователь не найден'})

    except Exception as e:
        conn.rollback()
        print(f"Ошибка при обновлении профиля: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': 'Внутренняя ошибка сервера'})
    finally:
        conn.close()

# ============ ИЗБРАННОЕ ============

@app.route('/api/favorites/toggle', methods=['POST'])
@login_required
def toggle_favorite():
    """Добавление/удаление места в избранное"""
    conn = get_db_connection()
    try:
        data = request.json
        place_id = data.get('place_id')

        if not place_id:
            return jsonify({'success': False, 'error': 'Не указано место'})

        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Проверяем, существует ли место
        cur.execute("SELECT id FROM places WHERE id = %s", (place_id,))
        if not cur.fetchone():
            return jsonify({'success': False, 'error': 'Место не найдено'})

        # Проверяем, есть ли уже в избранном
        cur.execute("""
                    SELECT id FROM favorites
                    WHERE user_id = %s AND place_id = %s
                    """, (current_user.id, place_id))

        existing = cur.fetchone()

        if existing:
            # Удаляем из избранного
            cur.execute("""
                        DELETE FROM favorites
                        WHERE user_id = %s AND place_id = %s
                        """, (current_user.id, place_id))
            action = 'removed'
        else:
            # Добавляем в избранное
            cur.execute("""
                        INSERT INTO favorites (user_id, place_id)
                        VALUES (%s, %s)
                        """, (current_user.id, place_id))
            action = 'added'

        conn.commit()

        # Получаем обновленное количество избранных
        cur.execute("""
                    SELECT COUNT(*) as count FROM favorites
                    WHERE user_id = %s
                    """, (current_user.id,))

        count = cur.fetchone()['count']

        return jsonify({
            'success': True,
            'action': action,
            'favorites_count': count,
            'message': 'Место добавлено в избранное' if action == 'added' else 'Место удалено из избранного'
        })

    except Exception as e:
        conn.rollback()
        print(f"Ошибка при работе с избранным: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()

@app.route('/api/favorites/status')
@login_required
def check_favorite_status():
    """Проверка статуса избранного для нескольких мест"""
    conn = get_db_connection()
    try:
        place_ids = request.args.get('place_ids', '')
        if not place_ids:
            return jsonify({'success': False, 'error': 'Не указаны места'})

        # Преобразуем строку в список чисел
        try:
            ids_list = [int(id.strip()) for id in place_ids.split(',') if id.strip()]
        except:
            return jsonify({'success': False, 'error': 'Неверный формат ID'})

        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Получаем статус избранного для каждого места
        cur.execute("""
                    SELECT place_id FROM favorites
                    WHERE user_id = %s AND place_id = ANY(%s)
                    """, (current_user.id, ids_list))

        favorites = {row['place_id'] for row in cur.fetchall()}

        return jsonify({
            'success': True,
            'favorites': list(favorites)
        })

    except Exception as e:
        print(f"Ошибка при проверке статуса избранного: {e}")
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()

@app.route('/api/favorites/list')
@login_required
def get_favorites_list():
    """Получение списка избранных мест"""
    conn = get_db_connection()
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 12, type=int)
        offset = (page - 1) * per_page

        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Получаем избранные места с пагинацией
        cur.execute("""
                    SELECT
                        p.id, p.title, p.slug, p.categories,
                        COALESCE(p.main_photo_url, '') as photo_url,
                        COALESCE(p.description, '') as description,
                        COALESCE(p.address, '') as address,
                        COALESCE(p.timetable, '') as timetable,
                        f.created_at as favorited_at
                    FROM places p
                             INNER JOIN favorites f ON p.id = f.place_id
                    WHERE f.user_id = %s AND NOT p.is_closed
                    ORDER BY f.created_at DESC
                    LIMIT %s OFFSET %s
                    """, (current_user.id, per_page, offset))

        places = [process_place_row(row) for row in cur.fetchall()]

        # Получаем общее количество
        cur.execute("""
                    SELECT COUNT(*) as total
                    FROM favorites f
                             INNER JOIN places p ON p.id = f.place_id
                    WHERE f.user_id = %s AND NOT p.is_closed
                    """, (current_user.id,))

        total = cur.fetchone()['total']
        total_pages = (total + per_page - 1) // per_page

        return jsonify({
            'success': True,
            'places': places,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'total_pages': total_pages,
                'has_next': page < total_pages,
                'has_prev': page > 1
            }
        })

    except Exception as e:
        print(f"Ошибка при получении избранного: {e}")
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()

@app.route('/api/favorites/count')
@login_required
def get_favorites_count():
    """Получение количества избранных мест"""
    conn = get_db_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        cur.execute("""
                    SELECT COUNT(*) as count FROM favorites
                    WHERE user_id = %s
                    """, (current_user.id,))

        count = cur.fetchone()['count']

        return jsonify({
            'success': True,
            'count': count
        })

    except Exception as e:
        print(f"Ошибка при получении количества избранного: {e}")
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()


@app.route('/favorites')
@login_required
def favorites_page():
    """Страница избранного"""
    return render_template('favorites.html')

# ============ ПОСЕЩЕННЫЕ МЕСТА ============

@app.route('/api/visited/toggle', methods=['POST'])
@login_required
def toggle_visited():
    """Добавление/удаление места в посещенные"""
    conn = get_db_connection()
    try:
        data = request.json
        place_id = data.get('place_id')

        if not place_id:
            return jsonify({'success': False, 'error': 'Не указано место'})

        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Проверяем, существует ли место
        cur.execute("SELECT id FROM places WHERE id = %s", (place_id,))
        if not cur.fetchone():
            return jsonify({'success': False, 'error': 'Место не найдено'})

        # Проверяем, есть ли уже в посещенных
        cur.execute("""
                    SELECT id FROM visited_places
                    WHERE user_id = %s AND place_id = %s
                    """, (current_user.id, place_id))

        existing = cur.fetchone()

        if existing:
            # Удаляем из посещенных
            cur.execute("""
                        DELETE FROM visited_places
                        WHERE user_id = %s AND place_id = %s
                        """, (current_user.id, place_id))
            action = 'removed'
        else:
            # Добавляем в посещенные
            cur.execute("""
                        INSERT INTO visited_places (user_id, place_id)
                        VALUES (%s, %s)
                        """, (current_user.id, place_id))
            action = 'added'

        conn.commit()

        # Получаем обновленное количество посещенных
        cur.execute("""
                    SELECT COUNT(*) as count FROM visited_places
                    WHERE user_id = %s
                    """, (current_user.id,))

        count = cur.fetchone()['count']

        return jsonify({
            'success': True,
            'action': action,
            'visited_count': count,
            'message': 'Место отмечено как посещенное' if action == 'added' else 'Место удалено из посещенных'
        })

    except Exception as e:
        conn.rollback()
        print(f"Ошибка при работе с посещенными местами: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()

@app.route('/api/visited/status')
@login_required
def check_visited_status():
    """Проверка статуса посещенных мест"""
    conn = get_db_connection()
    try:
        place_ids = request.args.get('place_ids', '')
        if not place_ids:
            return jsonify({'success': False, 'error': 'Не указаны места'})

        # Преобразуем строку в список чисел
        try:
            ids_list = [int(id.strip()) for id in place_ids.split(',') if id.strip()]
        except:
            return jsonify({'success': False, 'error': 'Неверный формат ID'})

        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Получаем статус посещенных для каждого места
        cur.execute("""
                    SELECT place_id FROM visited_places
                    WHERE user_id = %s AND place_id = ANY(%s)
                    """, (current_user.id, ids_list))

        visited = {row['place_id'] for row in cur.fetchall()}

        return jsonify({
            'success': True,
            'visited': list(visited)
        })

    except Exception as e:
        print(f"Ошибка при проверке статуса посещенных мест: {e}")
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()

@app.route('/api/visited/list')
@login_required
def get_visited_list():
    """Получение списка посещенных мест"""
    conn = get_db_connection()
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 12, type=int)
        offset = (page - 1) * per_page

        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Получаем посещенные места с пагинацией
        cur.execute("""
                    SELECT
                        p.id, p.title, p.slug, p.categories,
                        COALESCE(p.main_photo_url, '') as photo_url,
                        COALESCE(p.description, '') as description,
                        COALESCE(p.address, '') as address,
                        COALESCE(p.timetable, '') as timetable,
                        v.visited_at
                    FROM places p
                             INNER JOIN visited_places v ON p.id = v.place_id
                    WHERE v.user_id = %s AND NOT p.is_closed
                    ORDER BY v.visited_at DESC
                    LIMIT %s OFFSET %s
                    """, (current_user.id, per_page, offset))

        places = [process_place_row(row) for row in cur.fetchall()]

        # Получаем общее количество
        cur.execute("""
                    SELECT COUNT(*) as total
                    FROM visited_places v
                             INNER JOIN places p ON p.id = v.place_id
                    WHERE v.user_id = %s AND NOT p.is_closed
                    """, (current_user.id,))

        total = cur.fetchone()['total']
        total_pages = (total + per_page - 1) // per_page

        return jsonify({
            'success': True,
            'places': places,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'total_pages': total_pages,
                'has_next': page < total_pages,
                'has_prev': page > 1
            }
        })

    except Exception as e:
        print(f"Ошибка при получении посещенных мест: {e}")
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()

@app.route('/api/visited/count')
@login_required
def get_visited_count():
    """Получение количества посещенных мест"""
    conn = get_db_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        cur.execute("""
                    SELECT COUNT(*) as count FROM visited_places
                    WHERE user_id = %s
                    """, (current_user.id,))

        count = cur.fetchone()['count']

        return jsonify({
            'success': True,
            'count': count
        })

    except Exception as e:
        print(f"Ошибка при получении количества посещенных мест: {e}")
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()


@app.route('/visited')
@login_required
def visited_page():
    """Страница посещенных мест"""
    return render_template('visited.html')

# ============ ПРЕДЛОЖЕНИЕ МЕСТ ============
#@app.route('/suggest')
#@login_required
#def suggest_page():
    """Единая страница для предложения места и сообщения об ошибке"""
    #return render_template('user_suggestions.html', current_user=current_user)

@app.route('/suggest')
@login_required
def suggest_page():
    active_tab = request.args.get('tab', 'suggest')
    if active_tab not in ['suggest', 'report']:
        active_tab = 'suggest'
    return render_template('user_profile/user_suggestions.html',
                           current_user=current_user,
                           active_tab=active_tab)


# СТРАНИЦА ДЛЯ ПРЕДЛОЖЕНИЯ МЕСТ
@app.route('/suggest-place')
@login_required
def suggest_place_page():
    # Перенаправляем на /suggest?tab=suggest
    return redirect(url_for('suggest_page'))

# Для пользователя (предложение места)
#GET /api/categories - получение списка категорий для формы
@app.route('/api/categories')
@login_required
def get_categories():
    """Получение списка всех категорий для формы предложения места"""
    try:
        categories = get_categories_safe()
        return jsonify({
            'success': True,
            'categories': categories
        })
    except Exception as e:
        print(f"Ошибка при получении категорий: {e}")
        return jsonify({'success': False, 'error': str(e)})


# POST /api/suggest-place - отправка предложения нового места

@app.route('/api/suggest-place', methods=['POST'])
@login_required
def submit_suggestion():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        # Инициализируем переменные
        data = {}
        uploaded_photos = []

        # Проверяем, пришли ли данные как form-data (с файлами) или как JSON
        if request.content_type and 'multipart/form-data' in request.content_type:
            # Получаем данные из формы
            data = {
                'user_title': request.form.get('user_title', '').strip(),
                'user_description': request.form.get('user_description', '').strip(),
                'user_address': request.form.get('user_address', '').strip(),
                'user_timetable': request.form.get('user_timetable', '').strip(),
                'user_phone': request.form.get('user_phone', '').strip(),
                'user_foreign_url': request.form.get('user_foreign_url', '').strip(),
                'user_photos_url': request.form.get('user_photos_url', '').strip(),
            }

            # Получаем категории
            category_ids_str = request.form.get('category_ids', '')
            if category_ids_str:
                data['category_ids'] = [int(id.strip()) for id in category_ids_str.split(',') if id.strip()]
            else:
                data['category_ids'] = []

            # Обрабатываем загруженные файлы
            if 'user_photos' in request.files:
                files = request.files.getlist('user_photos')
                for file in files:
                    if file.filename and file.filename != '':  # Проверяем, что файл был выбран
                        photo_url = save_uploaded_file(file, 'suggestions')
                        if photo_url:
                            uploaded_photos.append(photo_url)
        else:
            # Получаем данные как JSON (старый способ)
            try:
                data = request.get_json()  # Используем get_json вместо прямого .json
                if data is None:
                    return jsonify({'success': False, 'error': 'Invalid JSON data'})
                data['category_ids'] = data.get('category_ids', [])
                uploaded_photos = []
            except Exception as json_error:
                print(f"JSON parsing error: {json_error}")
                return jsonify({'success': False, 'error': 'Invalid JSON format'})

        # Проверяем обязательные поля
        required_fields = ['user_title', 'user_description', 'user_address']
        missing_fields = [field for field in required_fields if not data.get(field)]

        if missing_fields:
            return jsonify({
                'success': False,
                'error': f'Заполните обязательные поля: {", ".join(missing_fields)}'
            })

        # Проверяем категории
        category_ids = data.get('category_ids', [])
        if not category_ids:
            return jsonify({'success': False, 'error': 'Выберите хотя бы одну категорию'})

        # Проверяем, что все категории существуют
        if category_ids:
            placeholders = ','.join(['%s'] * len(category_ids))
            cur.execute(f"""
                SELECT COUNT(*) as count 
                FROM categories_api 
                WHERE id IN ({placeholders})
            """, tuple(category_ids))

            count = cur.fetchone()['count']
            if count != len(category_ids):
                return jsonify({'success': False, 'error': 'Некоторые категории не существуют'})

        # Обрабатываем фотографии
        all_photos = []

        # Добавляем загруженные фото
        all_photos.extend(uploaded_photos)

        # Добавляем фото по URL (если есть)
        if 'user_photos_url' in data:
            photos_url = data.get('user_photos_url', '')
            if photos_url:
                url_photos = [url.strip() for url in photos_url.split(',') if url.strip()]
                all_photos.extend(url_photos)

        # Главное фото (берем первое, если есть)
        user_main_photo_url = all_photos[0] if all_photos else None

        # Сохраняем предложение в БД
        cur.execute("""
                    INSERT INTO place_suggestions
                    (
                        user_id,
                        user_title, user_description, user_address,
                        user_timetable, user_phone, user_foreign_url,
                        user_photos, user_main_photo_url,
                        status, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, 'pending', NOW(), NOW())
                    RETURNING id
                    """, (
                        current_user.id,
                        data['user_title'],
                        data['user_description'],
                        data['user_address'],
                        data.get('user_timetable', ''),
                        data.get('user_phone', ''),
                        data.get('user_foreign_url', ''),
                        json.dumps(all_photos),
                        user_main_photo_url
                    ))

        suggestion_id = cur.fetchone()['id']

        # Сохраняем выбранные категории пользователя
        for category_id in category_ids:
            cur.execute("""
                        INSERT INTO place_suggestion_user_categories (suggestion_id, category_id)
                        VALUES (%s, %s)
                        """, (suggestion_id, category_id))

        conn.commit()

        print(f"Получено файлов: {len(request.files.getlist('user_photos'))}")
        for f in request.files.getlist('user_photos'):
            print(f" - файл: {f.filename}, размер: {f.content_length}")


        return jsonify({
            'success': True,
            'message': 'Спасибо! Ваше предложение отправлено на модерацию.',
            'suggestion_id': suggestion_id,
            'uploaded_photos': len(uploaded_photos)
        })

    except Exception as e:
        conn.rollback()
        print(f"Ошибка при сохранении предложения: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': 'Внутренняя ошибка сервера'})
    finally:
        cur.close()
        conn.close()

# СТРАНИЦА С СООБЩЕНИЕМ ПОЛЬЗОВАТЕЛЯ ОБ ОШИБКЕ
@app.route('/report-error')
@login_required
def report_error_page():
    # Перенаправляем на /suggest?tab=report
    return redirect(url_for('suggest_page'))

# GET /api/places/search - поиск мест для формы сообщения об ошибке
@app.route('/api/places/search')
@login_required
def search_places():
    """Поиск мест по названию для формы сообщения об ошибке"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        query = request.args.get('q', '').strip()
        limit = request.args.get('limit', 10, type=int)

        if not query or len(query) < 2:
            return jsonify({
                'success': True,
                'places': [],
                'message': 'Введите минимум 2 символа для поиска'
            })

        # Ищем места по названию
        search_term = f"%{query}%"
        cur.execute("""
                    SELECT id, title, slug, address, main_photo_url
                    FROM places
                    WHERE NOT is_closed
                      AND (title ILIKE %s OR address ILIKE %s)
                    ORDER BY
                        CASE
                            WHEN title ILIKE %s THEN 1
                            WHEN address ILIKE %s THEN 2
                            ELSE 3
                            END,
                        title
                    LIMIT %s
                    """, (search_term, search_term, f"{query}%", f"{query}%", limit))

        places = []
        for row in cur.fetchall():
            place = dict(row)
            # Добавляем URL фото, если есть
            place['photo_url'] = place.get('main_photo_url', '')
            places.append(place)

        return jsonify({
            'success': True,
            'places': places,
            'count': len(places)
        })

    except Exception as e:
        print(f"Ошибка при поиске мест: {e}")
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()

# POST /api/report-error - отправка сообщения об ошибке в существующем месте
@app.route('/api/report-error', methods=['POST'])
@login_required
def submit_report():
    """Отправка сообщения об ошибке в существующем месте"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        data = request.json

        # Проверяем обязательные поля
        required_fields = ['place_id', 'subject', 'message']
        missing_fields = [field for field in required_fields if not data.get(field)]

        if missing_fields:
            return jsonify({
                'success': False,
                'error': f'Заполните обязательные поля: {", ".join(missing_fields)}'
            })

        place_id = data['place_id']
        subject = data['subject'].strip()
        message = data['message'].strip()

        # Проверяем, существует ли место
        cur.execute("SELECT id FROM places WHERE id = %s AND NOT is_closed", (place_id,))
        if not cur.fetchone():
            return jsonify({'success': False, 'error': 'Место не найдено или закрыто'})

        # Проверяем длину темы и сообщения
        if len(subject) > 200:
            return jsonify({'success': False, 'error': 'Тема слишком длинная (максимум 200 символов)'})

        if len(message) > 2000:
            return jsonify({'success': False, 'error': 'Сообщение слишком длинное (максимум 2000 символов)'})

        # Сохраняем сообщение об ошибке
        cur.execute("""
                    INSERT INTO place_reports
                        (place_id, user_id, subject, message, status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, 'pending', NOW(), NOW())
                    RETURNING id
                    """, (place_id, current_user.id, subject, message))

        report_id = cur.fetchone()['id']
        conn.commit()

        return jsonify({
            'success': True,
            'message': 'Спасибо! Ваше сообщение об ошибке отправлено на рассмотрение.',
            'report_id': report_id
        })

    except Exception as e:
        conn.rollback()
        print(f"Ошибка при сохранении сообщения об ошибке: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': 'Внутренняя ошибка сервера'})
    finally:
        cur.close()
        conn.close()

# GET /api/user/reports - получение сообщений об ошибках пользователя
@app.route('/api/user/reports')
@login_required
def get_user_reports():
    """Получение сообщений об ошибках пользователя"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        status = request.args.get('status', 'all')
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        offset = (page - 1) * per_page

        # Базовый запрос
        query = """
                SELECT
                    pr.*,
                    p.title as place_title,
                    p.slug as place_slug,
                    p.main_photo_url as place_photo,
                    u_mod.username as resolved_by_username
                FROM place_reports pr
                         JOIN places p ON pr.place_id = p.id
                         LEFT JOIN users u_mod ON pr.resolved_by = u_mod.id
                WHERE pr.user_id = %s \
                """

        params = [current_user.id]

        # Фильтр по статусу
        if status != 'all':
            query += " AND pr.status = %s"
            params.append(status)

        # Добавляем сортировку и пагинацию
        query += " ORDER BY pr.created_at DESC LIMIT %s OFFSET %s"
        params.extend([per_page, offset])

        cur.execute(query, params)

        reports = []
        for row in cur.fetchall():
            report = dict(row)
            # Преобразуем даты
            for date_field in ['created_at', 'updated_at']:
                if report.get(date_field):
                    report[date_field] = report[date_field].isoformat()
            reports.append(report)

        # Получаем общее количество
        count_query = """
                      SELECT COUNT(*) as total
                      FROM place_reports pr
                      WHERE pr.user_id = %s \
                      """
        count_params = [current_user.id]

        if status != 'all':
            count_query += " AND pr.status = %s"
            count_params.append(status)

        cur.execute(count_query, count_params)
        total = cur.fetchone()['total']
        total_pages = (total + per_page - 1) // per_page

        # Статистика по статусам
        cur.execute("""
                    SELECT
                        status,
                        COUNT(*) as count
                    FROM place_reports
                    WHERE user_id = %s
                    GROUP BY status
                    """, (current_user.id,))

        stats = {row['status']: row['count'] for row in cur.fetchall()}

        return jsonify({
            'success': True,
            'reports': reports,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'total_pages': total_pages,
                'has_next': page < total_pages,
                'has_prev': page > 1
            },
            'stats': stats
        })

    except Exception as e:
        print(f"Ошибка при получении сообщений пользователя: {e}")
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()



## ФУНКЦИОНАЛ ДЛЯ МОДЕРАТОРА - РАБОТА С ПРЕДЛОЖЕННЫМИ МЕСТАМИ
# ============ АДМИН-ПАНЕЛЬ ============

# Главная страница админки
@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    """Главная страница панели администратора"""
    return render_template('admin/dashboard.html', active_page='dashboard')


# Страница модерации предложений мест
@app.route('/admin/suggestions')
@login_required
@admin_required
def admin_suggestions():
    """Страница модерации предложений мест"""
    return render_template('admin/suggestions.html', active_page='suggestions')

# Страница модерации сообщений об ошибках
@app.route('/admin/reports')
@login_required
@admin_required
def admin_reports():
    """Страница модерации сообщений об ошибках"""
    return render_template('admin/reports.html', active_page='reports')




# 1. GET /api/admin/suggestions - получение списка предложений для модерации
@app.route('/api/admin/suggestions')
@login_required
@admin_required
def get_admin_suggestions():
    """Получение списка предложений для модерации (обновленная версия)"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        status = request.args.get('status', 'pending')
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        offset = (page - 1) * per_page

        # Базовый запрос с JOIN для получения категорий пользователя
        query = """
                SELECT
                    ps.*,
                    u.username as user_username,
                    u.email as user_email,
                    array_agg(DISTINCT c.name) as user_category_names,
                    COUNT(DISTINCT c.id) as user_categories_count,
                    p.title as created_place_title,
                    p.slug as created_place_slug
                FROM place_suggestions ps
                         LEFT JOIN users u ON ps.user_id = u.id
                         LEFT JOIN place_suggestion_user_categories psuc ON ps.id = psuc.suggestion_id
                         LEFT JOIN categories_api c ON psuc.category_id = c.id
                         LEFT JOIN places p ON ps.created_place_id = p.id
                WHERE 1=1 \
                """

        params = []

        # Фильтр по статусу
        if status != 'all':
            query += " AND ps.status = %s"
            params.append(status)

        # Группировка и сортировка
        query += """
            GROUP BY ps.id, u.id, p.id
            ORDER BY ps.created_at DESC
            LIMIT %s OFFSET %s
        """
        params.extend([per_page, offset])

        cur.execute(query, params)

        suggestions = []
        for row in cur.fetchall():
            suggestion = dict(row)

            # Обработка дат
            for date_field in ['created_at', 'updated_at']:
                if suggestion.get(date_field):
                    suggestion[date_field] = suggestion[date_field].isoformat()

            # Обработка JSON полей
            for json_field in ['user_photos', 'moderated_photos', 'moderated_coords']:
                if suggestion.get(json_field):
                    try:
                        if isinstance(suggestion[json_field], str):
                            suggestion[json_field] = json.loads(suggestion[json_field])
                    except:
                        suggestion[json_field] = []

            suggestions.append(suggestion)

        # Получаем общее количество
        count_query = """
                      SELECT COUNT(*) as total
                      FROM place_suggestions ps
                      WHERE 1=1 \
                      """
        count_params = []

        if status != 'all':
            count_query += " AND ps.status = %s"
            count_params.append(status)

        cur.execute(count_query, count_params)
        total = cur.fetchone()['total']
        total_pages = (total + per_page - 1) // per_page

        # Статистика по статусам
        cur.execute("""
                    SELECT
                        status,
                        COUNT(*) as count
                    FROM place_suggestions
                    GROUP BY status
                    ORDER BY status
                    """)

        stats = {row['status']: row['count'] for row in cur.fetchall()}

        return jsonify({
            'success': True,
            'suggestions': suggestions,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'total_pages': total_pages,
                'has_next': page < total_pages,
                'has_prev': page > 1
            },
            'stats': stats
        })

    except Exception as e:
        print(f"Ошибка при получении предложений: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()


# 2. GET /api/admin/suggestions/<id> - детальная информация о предложении
@app.route('/api/admin/suggestions/<int:suggestion_id>')
@login_required
@admin_required
def get_suggestion_detail(suggestion_id):
    """Получение детальной информации о предложении"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        # Основная информация о предложении
        cur.execute("""
                    SELECT
                        ps.*,
                        u.username as user_username,
                        u.email as user_email,
                        p.title as created_place_title,
                        p.slug as created_place_slug,
                        u_mod.username as moderator_username
                    FROM place_suggestions ps
                             LEFT JOIN users u ON ps.user_id = u.id
                             LEFT JOIN places p ON ps.created_place_id = p.id
                             LEFT JOIN users u_mod ON ps.moderated_by = u_mod.id
                    WHERE ps.id = %s
                    """, (suggestion_id,))

        suggestion = cur.fetchone()

        if not suggestion:
            return jsonify({'success': False, 'error': 'Предложение не найдено'})

        suggestion_dict = dict(suggestion)

        # Обработка дат
        for date_field in ['created_at', 'updated_at']:
            if suggestion_dict.get(date_field):
                suggestion_dict[date_field] = suggestion_dict[date_field].isoformat()

        # Обработка JSON полей
        json_fields = ['user_photos', 'moderated_photos', 'moderated_coords']
        for field in json_fields:
            if suggestion_dict.get(field):
                try:
                    if isinstance(suggestion_dict[field], str):
                        suggestion_dict[field] = json.loads(suggestion_dict[field])
                except:
                    suggestion_dict[field] = []


        # ========== ДОБАВИТЬ ЭТОТ БЛОК ==========
        # Обрабатываем фотографии, определяя их тип (внешняя ссылка или файл)
        for photo_field in ['user_photos', 'moderated_photos']:
            if suggestion_dict.get(photo_field):
                processed_photos = []
                for photo in suggestion_dict[photo_field]:
                    if isinstance(photo, str) and photo.strip():
                        # Определяем тип фотографии
                        is_external = photo.strip().startswith('http')
                        processed_photos.append({
                            'url': photo.strip(),
                            'is_external': is_external,
                            'type': 'external' if is_external else 'upload'
                        })
                suggestion_dict[f'{photo_field}_processed'] = processed_photos
            # Получаем категории пользователя
        cur.execute("""
                    SELECT
                        c.id, c.slug, c.name
                    FROM place_suggestion_user_categories psuc
                             JOIN categories_api c ON psuc.category_id = c.id
                    WHERE psuc.suggestion_id = %s
                    ORDER BY c.name
                    """, (suggestion_id,))

        user_categories = [dict(row) for row in cur.fetchall()]
        suggestion_dict['user_categories'] = user_categories

        # Получаем категории модератора
        cur.execute("""
                    SELECT
                        c.id, c.slug, c.name
                    FROM place_suggestion_moderated_categories psmc
                             JOIN categories_api c ON psmc.category_id = c.id
                    WHERE psmc.suggestion_id = %s
                    ORDER BY c.name
                    """, (suggestion_id,))

        moderated_categories = [dict(row) for row in cur.fetchall()]
        suggestion_dict['moderated_categories'] = moderated_categories

        # Получаем информацию о месте, если оно было создано
        if suggestion_dict.get('created_place_id'):
            cur.execute("""
                        SELECT title, slug, main_photo_url, address
                        FROM places
                        WHERE id = %s
                        """, (suggestion_dict['created_place_id'],))

            place_info = cur.fetchone()
            if place_info:
                suggestion_dict['place_info'] = dict(place_info)

        return jsonify({
            'success': True,
            'suggestion': suggestion_dict
        })

    except Exception as e:
        print(f"Ошибка при получении деталей предложения: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()


# 3. PUT /api/admin/suggestions/<id> - обновление данных модератором
@app.route('/api/admin/suggestions/<int:suggestion_id>', methods=['PUT'])
@login_required
@admin_required
def update_suggestion(suggestion_id):
    """Обновление данных предложения модератором"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        data = request.json

        # Проверяем, существует ли предложение
        cur.execute("SELECT id, status FROM place_suggestions WHERE id = %s", (suggestion_id,))
        suggestion = cur.fetchone()

        if not suggestion:
            return jsonify({'success': False, 'error': 'Предложение не найдено'})

        # Можно обновлять только предложения со статусом pending
        if suggestion['status'] != 'pending':
            return jsonify({'success': False, 'error': 'Можно редактировать только предложения на модерации'})

        # Подготавливаем данные для обновления
        update_fields = []
        update_values = []

        # Основные поля для обновления
        moderated_fields = [
            'title', 'short_title', 'slug', 'address', 'timetable', 'phone',
            'description', 'body_text', 'foreign_url', 'coords',
            'photos', 'main_photo_url'   # is_closed убрали
        ]

        for field in moderated_fields:
            field_name = f'moderated_{field}'
            if field_name in data:
                update_fields.append(f"{field_name} = %s")

                # Обработка JSON полей
                if field in ['coords', 'subway', 'photos'] and data[field_name]:
                    update_values.append(json.dumps(data[field_name]))
                else:
                    update_values.append(data[field_name])

        # Обработка is_closed
        if 'moderated_is_closed' in data:
            update_fields.append("moderated_is_closed = %s")
            update_values.append(bool(data['moderated_is_closed']))

        # Если есть что обновлять
        if update_fields:
            update_query = f"""
                UPDATE place_suggestions
                SET {', '.join(update_fields)}, updated_at = NOW()
                WHERE id = %s
            """
            update_values.append(suggestion_id)

            cur.execute(update_query, tuple(update_values))

        # Обновляем категории модератора
        if 'moderated_category_ids' in data:
            # Удаляем старые категории модератора
            cur.execute("DELETE FROM place_suggestion_moderated_categories WHERE suggestion_id = %s",
                        (suggestion_id,))

            # Добавляем новые категории
            category_ids = data['moderated_category_ids']
            for category_id in category_ids:
                # Проверяем существование категории
                cur.execute("SELECT id FROM categories_api WHERE id = %s", (category_id,))
                if cur.fetchone():
                    cur.execute("""
                                INSERT INTO place_suggestion_moderated_categories (suggestion_id, category_id)
                                VALUES (%s, %s)
                                ON CONFLICT DO NOTHING
                                """, (suggestion_id, category_id))

        conn.commit()

        return jsonify({
            'success': True,
            'message': 'Данные успешно обновлены'
        })

    except Exception as e:
        conn.rollback()
        print(f"Ошибка при обновлении предложения: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()

@app.route('/api/admin/suggestions/upload-photo', methods=['POST'])
@login_required
@admin_required
def upload_moderator_photo():
    """Загрузка фотографии модератором для предложения"""
    try:
        if 'photo' not in request.files:
            return jsonify({'success': False, 'error': 'Нет файла'})

        file = request.files['photo']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'Пустой файл'})

        # Сохраняем файл в папку suggestions
        photo_url = save_uploaded_file(file, 'suggestions')

        if photo_url:
            return jsonify({
                'success': True,
                'url': photo_url,
                'message': 'Фото загружено'
            })
        else:
            return jsonify({'success': False, 'error': 'Ошибка сохранения файла'})

    except Exception as e:
        print(f"Ошибка загрузки фото модератором: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})


# 4. POST /api/admin/suggestions/<id>/approve - одобрение предложения
@app.route('/api/admin/suggestions/<int:suggestion_id>/approve', methods=['POST'])
@login_required
@admin_required
def approve_suggestion(suggestion_id):
    """Одобрение предложения и создание места"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        data = request.json
        admin_comment = data.get('admin_comment', '')

        # Проверяем, существует ли предложение и его статус
        cur.execute("""
                    SELECT * FROM place_suggestions
                    WHERE id = %s AND status = 'pending'
                    """, (suggestion_id,))

        suggestion = cur.fetchone()
        if not suggestion:
            return jsonify({'success': False, 'error': 'Предложение не найдено или уже рассмотрено'})

        suggestion_dict = dict(suggestion)

        # Проверяем обязательные поля модератора
        required_moderated_fields = ['moderated_title', 'moderated_slug']
        for field in required_moderated_fields:
            if not suggestion_dict.get(field):
                return jsonify({
                    'success': False,
                    'error': f'Заполните поле: {field.replace("moderated_", "")}'
                })

        # Проверяем уникальность slug
        cur.execute("SELECT id FROM places WHERE slug = %s", (suggestion_dict['moderated_slug'],))
        if cur.fetchone():
            return jsonify({'success': False, 'error': 'Такой URL-адрес уже существует'})

        # --- Основные поля места ---
        title = suggestion_dict.get('moderated_title') or suggestion_dict['user_title']
        short_title = suggestion_dict.get('moderated_short_title') or suggestion_dict.get('user_title', '')[:200]
        slug = suggestion_dict['moderated_slug']

        # --- Категории (приоритет: модератор → пользователь) ---
        cur.execute("""
                    SELECT c.slug
                    FROM place_suggestion_moderated_categories psmc
                             JOIN categories_api c ON psmc.category_id = c.id
                    WHERE psmc.suggestion_id = %s
                    """, (suggestion_id,))
        moderated_categories = [row['slug'] for row in cur.fetchall()]

        if moderated_categories:
            categories_json = json.dumps(moderated_categories)
        else:
            cur.execute("""
                        SELECT c.slug
                        FROM place_suggestion_user_categories psuc
                                 JOIN categories_api c ON psuc.category_id = c.id
                        WHERE psuc.suggestion_id = %s
                        """, (suggestion_id,))
            user_categories = [row['slug'] for row in cur.fetchall()]
            categories_json = json.dumps(user_categories) if user_categories else '[]'

        # --- Остальные поля ---
        address = suggestion_dict.get('moderated_address') or suggestion_dict.get('user_address', '')
        timetable = suggestion_dict.get('moderated_timetable') or suggestion_dict.get('user_timetable', '')
        phone = suggestion_dict.get('moderated_phone') or suggestion_dict.get('user_phone', '')
        description = suggestion_dict.get('moderated_description') or suggestion_dict.get('user_description', '')
        body_text = suggestion_dict.get('moderated_body_text', '')
        foreign_url = suggestion_dict.get('moderated_foreign_url') or suggestion_dict.get('user_foreign_url', '')
        is_closed = bool(suggestion_dict.get('moderated_is_closed', False))

        # --- Координаты ---
        coords = suggestion_dict.get('moderated_coords') or '{}'
        if isinstance(coords, (dict, list)):
            coords = json.dumps(coords)

        # --- Метро ---
        subway = '[]'
        if isinstance(subway, list):
            subway = json.dumps(subway)

        # ========== ОБРАБОТКА ФОТОГРАФИЙ ==========
        # Функция безопасного парсинга JSON
        def parse_json_field(data):
            if not data:
                return []
            if isinstance(data, list):
                return data
            if isinstance(data, str):
                try:
                    return json.loads(data)
                except:
                    return []
            return []

        mod_photos_raw = suggestion_dict.get('moderated_photos')
        user_photos_raw = suggestion_dict.get('user_photos', [])

        mod_photos = parse_json_field(mod_photos_raw)
        user_photos = parse_json_field(user_photos_raw)

        # Приоритет: moderated_photos (если есть и не пустой) → user_photos
        if mod_photos and len(mod_photos) > 0:
            photos_list = mod_photos
        else:
            photos_list = user_photos if len(user_photos) > 0 else []

        # Сериализуем в JSON-строку для вставки в БД
        photos_json = json.dumps(photos_list)

        # ========== ГЛАВНОЕ ФОТО ==========
        # Приоритет: moderated_main_photo_url → первое фото из moderated_photos → user_main_photo_url → первое фото из user_photos
        main_photo_url = suggestion_dict.get('moderated_main_photo_url')
        if not main_photo_url and mod_photos and len(mod_photos) > 0:
            main_photo_url = mod_photos[0]
        if not main_photo_url:
            main_photo_url = suggestion_dict.get('user_main_photo_url')
        if not main_photo_url and user_photos and len(user_photos) > 0:
            main_photo_url = user_photos[0]
        if not main_photo_url:
            main_photo_url = ''

        # --- Вставка нового места в таблицу places ---
        cur.execute("""
                    INSERT INTO places (
                        title, short_title, slug, categories, address,
                        timetable, phone, description, body_text, foreign_url,
                        coords, subway, photos, main_photo_url,
                        is_closed, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                    RETURNING id
                    """, (
                        title, short_title, slug, categories_json, address,
                        timetable, phone, description, body_text, foreign_url,
                        coords, subway, photos_json, main_photo_url,
                        is_closed
                    ))

        place_id = cur.fetchone()['id']

        # --- Обновляем предложение ---
        cur.execute("""
                    UPDATE place_suggestions
                    SET
                        status = 'approved',
                        created_place_id = %s,
                        moderated_by = %s,
                        admin_comment = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """, (place_id, current_user.id, admin_comment, suggestion_id))

        conn.commit()

        return jsonify({
            'success': True,
            'message': 'Предложение одобрено! Место добавлено в базу.',
            'place_id': place_id,
            'place_slug': slug
        })

    except Exception as e:
        conn.rollback()
        print(f"Ошибка при одобрении предложения: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()


# 5. POST /api/admin/suggestions/<id>/reject - отклонение предложения
@app.route('/api/admin/suggestions/<int:suggestion_id>/reject', methods=['POST'])
@login_required
@admin_required
def reject_suggestion(suggestion_id):
    """Отклонение предложения"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        data = request.json
        admin_comment = data.get('admin_comment', '')

        # Проверяем, существует ли предложение и его статус
        cur.execute("""
                    SELECT id FROM place_suggestions
                    WHERE id = %s AND status = 'pending'
                    """, (suggestion_id,))

        if not cur.fetchone():
            return jsonify({'success': False, 'error': 'Предложение не найдено или уже рассмотрено'})

        # Обновляем статус предложения
        cur.execute("""
                    UPDATE place_suggestions
                    SET
                        status = 'rejected',
                        moderated_by = %s,
                        admin_comment = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """, (current_user.id, admin_comment, suggestion_id))

        conn.commit()

        return jsonify({
            'success': True,
            'message': 'Предложение отклонено.'
        })

    except Exception as e:
        conn.rollback()
        print(f"Ошибка при отклонении предложения: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()

# 6. GET /api/admin/categories - получение категорий для модератора
@app.route('/api/admin/categories')
@login_required
@admin_required
def get_admin_categories():
    """Получение списка категорий для модератора"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        cur.execute("""
                    SELECT
                        c.id, c.slug, c.name,
                        COUNT(DISTINCT p.id) as places_count,
                        COUNT(DISTINCT ps.id) as suggestions_count
                    FROM categories_api c
                             LEFT JOIN places p ON p.categories @> to_jsonb(ARRAY[c.slug])
                             LEFT JOIN place_suggestions ps ON EXISTS (
                        SELECT 1 FROM place_suggestion_user_categories psuc
                        WHERE psuc.suggestion_id = ps.id AND psuc.category_id = c.id
                    )
                    GROUP BY c.id, c.slug, c.name
                    ORDER BY c.name
                    """)

        categories = []
        for row in cur.fetchall():
            category = dict(row)
            category['places_count'] = int(category['places_count']) if category['places_count'] else 0
            category['suggestions_count'] = int(category['suggestions_count']) if category['suggestions_count'] else 0
            categories.append(category)

        return jsonify({'success': True, 'categories': categories})

    except Exception as e:
        print(f"Ошибка при получении категорий для модератора: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()

# ФУНКЦИОНАЛ МОДЕРАТОРА - РАБОТА С ОБРАЩЕНИЯМИ О НЕКОРРЕКТНЫХ ДАННЫХ В СУЩЕСТВУЮЩИХ МЕСТАХ
# 1. GET /api/admin/reports - получение списка сообщений об ошибках для модерации
@app.route('/api/admin/reports')
@login_required
@admin_required
def get_admin_reports():
    """Получение списка сообщений об ошибках для модерации"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        status = request.args.get('status', 'pending')
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        offset = (page - 1) * per_page

        # Базовый запрос
        query = """
                SELECT
                    pr.*,
                    p.title as place_title,
                    p.slug as place_slug,
                    p.main_photo_url as place_photo,
                    u.username as user_username,
                    u.email as user_email,
                    u_res.username as resolved_by_username,
                    p.address as place_address,
                    p.description as place_description,
                    p.timetable as place_timetable,
                    p.phone as place_phone
                FROM place_reports pr
                         JOIN places p ON pr.place_id = p.id
                         LEFT JOIN users u ON pr.user_id = u.id
                         LEFT JOIN users u_res ON pr.resolved_by = u_res.id
                WHERE 1=1 \
                """

        params = []

        # Фильтр по статусу
        if status != 'all':
            query += " AND pr.status = %s"
            params.append(status)

        # Добавляем сортировку и пагинацию
        query += " ORDER BY pr.created_at DESC LIMIT %s OFFSET %s"
        params.extend([per_page, offset])

        cur.execute(query, params)

        reports = []
        for row in cur.fetchall():
            report = dict(row)
            # Преобразуем даты
            for date_field in ['created_at', 'updated_at']:
                if report.get(date_field):
                    report[date_field] = report[date_field].isoformat()
            reports.append(report)

        # Получаем общее количество
        count_query = """
                      SELECT COUNT(*) as total
                      FROM place_reports pr
                      WHERE 1=1 \
                      """
        count_params = []

        if status != 'all':
            count_query += " AND pr.status = %s"
            count_params.append(status)

        cur.execute(count_query, count_params)
        total = cur.fetchone()['total']
        total_pages = (total + per_page - 1) // per_page

        # Статистика по статусам
        cur.execute("""
                    SELECT
                        status,
                        COUNT(*) as count
                    FROM place_reports
                    GROUP BY status
                    ORDER BY status
                    """)

        stats = {row['status']: row['count'] for row in cur.fetchall()}

        # Статистика по темам
        cur.execute("""
                    SELECT
                        subject,
                        COUNT(*) as count
                    FROM place_reports
                    GROUP BY subject
                    ORDER BY count DESC
                    LIMIT 10
                    """)

        subjects_stats = [dict(row) for row in cur.fetchall()]

        return jsonify({
            'success': True,
            'reports': reports,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'total_pages': total_pages,
                'has_next': page < total_pages,
                'has_prev': page > 1
            },
            'stats': stats,
            'subjects_stats': subjects_stats
        })

    except Exception as e:
        print(f"Ошибка при получении сообщений об ошибках: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()


# 2. GET /api/admin/reports/<id> - детальная информация о сообщении об ошибке
@app.route('/api/admin/reports/<int:report_id>')
@login_required
@admin_required
def get_report_detail(report_id):
    """Получение детальной информации о сообщении об ошибке"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        # Получаем основную информацию о сообщении
        cur.execute("""
                    SELECT
                        pr.*,
                        p.title as place_title,
                        p.slug as place_slug,
                        p.short_title as place_short_title,      
                        p.body_text as place_body_text,          
                        p.photos as place_photos,               
                        p.main_photo_url as place_photo,
                        p.address as place_address,
                        p.description as place_description,
                        p.timetable as place_timetable,
                        p.phone as place_phone,
                        p.foreign_url as place_foreign_url,
                        p.coords as place_coords,
                        p.subway as place_subway,
                        p.categories as place_categories,
                        p.is_closed as place_is_closed,        
                        u.username as user_username,
                        u.email as user_email,
                        u_res.username as resolved_by_username
                    FROM place_reports pr
                             JOIN places p ON pr.place_id = p.id
                             LEFT JOIN users u ON pr.user_id = u.id
                             LEFT JOIN users u_res ON pr.resolved_by = u_res.id
                    WHERE pr.id = %s
                    """, (report_id,))

        report = cur.fetchone()

        if not report:
            return jsonify({'success': False, 'error': 'Сообщение не найдено'})

        report_dict = dict(report)

        # Обработка дат
        for date_field in ['created_at', 'updated_at']:
            if report_dict.get(date_field):
                report_dict[date_field] = report_dict[date_field].isoformat()

        # Обработка JSON полей места
        json_fields = ['place_coords', 'place_subway', 'place_categories']
        for field in json_fields:
            if report_dict.get(field):
                try:
                    if isinstance(report_dict[field], str):
                        report_dict[field] = json.loads(report_dict[field])
                except:
                    report_dict[field] = []

        # Если есть координаты, преобразуем их в удобный формат
        if report_dict.get('place_coords') and isinstance(report_dict['place_coords'], dict):
            coords = report_dict['place_coords']
            report_dict['place_lat'] = coords.get('lat')
            report_dict['place_lon'] = coords.get('lon')

        # Получаем историю изменений места (если есть)
        # (Это можно реализовать позже, если будет таблица history)

        return jsonify({
            'success': True,
            'report': report_dict
        })

    except Exception as e:
        print(f"Ошибка при получении деталей сообщения: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()

# 3. POST /api/admin/reports/<id>/resolve - отметка сообщения как решенного
@app.route('/api/admin/reports/<int:report_id>/resolve', methods=['POST'])
@login_required
@admin_required
def resolve_report(report_id):
    """Отметка сообщения об ошибке как решенного"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        data = request.json
        resolution_comment = data.get('resolution_comment', '')
        update_place = data.get('update_place', False)  # Обновлять ли место
        place_updates = data.get('place_updates', {})   # Обновления для места

        # Проверяем, существует ли сообщение
        cur.execute("""
                    SELECT * FROM place_reports
                    WHERE id = %s AND status = 'pending'
                    """, (report_id,))

        report = cur.fetchone()
        if not report:
            return jsonify({'success': False, 'error': 'Сообщение не найдено или уже обработано'})

        report_dict = dict(report)
        place_id = report_dict['place_id']

        # Если нужно обновить место
        if update_place and place_updates:
            # Получаем текущие данные места
            cur.execute("SELECT * FROM places WHERE id = %s", (place_id,))
            current_place = dict(cur.fetchone())

            # Подготавливаем обновления
            update_fields = []
            update_values = []

            # Маппинг полей из формы в поля таблицы places
            field_mapping = {
                'title': 'title',
                'short_title': 'short_title',
                'address': 'address',
                'timetable': 'timetable',
                'phone': 'phone',
                'description': 'description',
                'body_text': 'body_text',
                'foreign_url': 'foreign_url',
                'coords': 'coords',
                'subway': 'subway',
                'photos': 'photos',
                'main_photo_url': 'main_photo_url',
                'is_closed': 'is_closed'
            }

            for form_field, db_field in field_mapping.items():
                if form_field in place_updates:
                    update_fields.append(f"{db_field} = %s")

                    # Обработка JSON полей
                    if form_field in ['coords', 'subway', 'photos']:
                        value = place_updates[form_field]
                        if value is not None:
                            update_values.append(json.dumps(value))
                        else:
                            # Если значение None, записываем пустой JSON объект/массив
                            if form_field == 'coords':
                                update_values.append(json.dumps({}))
                            elif form_field in ['subway', 'photos']:
                                update_values.append(json.dumps([]))
                            else:
                                update_values.append(None)
                    elif form_field == 'is_closed':
                        update_values.append(bool(place_updates[form_field]))
                    else:
                        update_values.append(place_updates[form_field])

            # Если есть категории для обновления
            if 'categories' in place_updates:
                # Преобразуем категории в JSON
                categories_json = json.dumps(place_updates['categories'])
                update_fields.append("categories = %s")
                update_values.append(categories_json)

            if update_fields:
                update_query = f"""
                    UPDATE places
                    SET {', '.join(update_fields)}, updated_at = NOW()
                    WHERE id = %s
                """
                update_values.append(place_id)

                cur.execute(update_query, tuple(update_values))

        # Обновляем статус сообщения
        cur.execute("""
                    UPDATE place_reports
                    SET
                        status = 'resolved',
                        resolved_by = %s,
                        resolution_comment = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """, (current_user.id, resolution_comment, report_id))

        conn.commit()

        return jsonify({
            'success': True,
            'message': 'Сообщение отмечено как решенное' +
                       (' и место обновлено' if update_place else '')
        })

    except Exception as e:
        conn.rollback()
        print(f"Ошибка при обработке сообщения об ошибке: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()


# 4. POST /api/admin/reports/<id>/update-place - обновление места на основе сообщения об ошибке
@app.route('/api/admin/reports/<int:report_id>/update-place', methods=['POST'])
@login_required
@admin_required
def update_place_from_report(report_id):
    """Обновление места на основе сообщения об ошибке (без изменения статуса обращения)"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        data = request.json
        updates = data.get('updates', {})

        # Проверяем существование сообщения
        cur.execute("SELECT place_id FROM place_reports WHERE id = %s", (report_id,))
        report = cur.fetchone()
        if not report:
            return jsonify({'success': False, 'error': 'Сообщение не найдено'})

        place_id = report['place_id']

        # Маппинг полей формы → поля таблицы places
        field_mapping = {
            'title': 'title',
            'short_title': 'short_title',
            'slug': 'slug',
            'address': 'address',
            'timetable': 'timetable',
            'phone': 'phone',
            'description': 'description',
            'body_text': 'body_text',
            'foreign_url': 'foreign_url',
            'coords': 'coords',
            'subway': 'subway',
            'photos': 'photos',
            'main_photo_url': 'main_photo_url',
            'is_closed': 'is_closed',
            'categories': 'categories'
        }

        update_fields = []
        update_values = []

        for form_field, db_field in field_mapping.items():
            if form_field in updates:
                update_fields.append(f"{db_field} = %s")
                value = updates[form_field]

                # Обработка JSON-полей
                if form_field in ['coords', 'subway', 'photos', 'categories']:
                    if value is not None:
                        # Если value уже строка (JSON) – используем как есть
                        if isinstance(value, str):
                            update_values.append(value)
                        else:
                            update_values.append(json.dumps(value))
                    else:
                        # Пустые значения: координаты -> {}, остальное -> []
                        if form_field == 'coords':
                            update_values.append(json.dumps({}))
                        else:
                            update_values.append(json.dumps([]))
                elif form_field == 'is_closed':
                    update_values.append(bool(value))
                else:
                    update_values.append(value)

        if not update_fields:
            return jsonify({'success': False, 'error': 'Нет данных для обновления'})

        # Обновляем место
        update_query = f"""
            UPDATE places
            SET {', '.join(update_fields)}, updated_at = NOW()
            WHERE id = %s
            RETURNING id, title, slug
        """
        update_values.append(place_id)

        cur.execute(update_query, tuple(update_values))
        updated_place = cur.fetchone()

        conn.commit()

        return jsonify({
            'success': True,
            'message': 'Место успешно обновлено',
            'place': {
                'id': updated_place['id'],
                'title': updated_place['title'],
                'slug': updated_place['slug']
            }
        })

    except Exception as e:
        conn.rollback()
        print(f"Ошибка при обновлении места: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()



# API для проверки дубликатов
@app.route('/api/admin/suggestions/<int:suggestion_id>/check-duplicates', methods=['POST'])
@login_required
@admin_required
def check_suggestion_duplicates(suggestion_id):
    """Проверка дубликатов по данным из предложения или переданным параметрам"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        data = request.json
        title = data.get('title', '').strip()
        address = data.get('address', '').strip()
        coords = data.get('coords', {})

        # Если данные не переданы, берём из предложения
        if not title:
            cur.execute("SELECT user_title, moderated_title FROM place_suggestions WHERE id = %s", (suggestion_id,))
            s = cur.fetchone()
            if s:
                title = s['moderated_title'] or s['user_title'] or ''

        # Ищем похожие места
        duplicates = []
        if title:
            # Простой поиск по названию (ILIKE)
            cur.execute("""
                        SELECT id, title, slug, address, main_photo_url
                        FROM places
                        WHERE NOT is_closed
                          AND title ILIKE %s
                        LIMIT 10
                        """, (f'%{title}%',))
            duplicates = [dict(row) for row in cur.fetchall()]

        # Можно добавить поиск по адресу, координатам и т.д.

        return jsonify({'success': True, 'duplicates': duplicates})
    except Exception as e:
        print(f"Ошибка при проверке дубликатов: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()

# ============ API ДЛЯ АДМИН-ПАНЕЛИ ============

@app.route('/api/admin/dashboard/stats')
@login_required
@admin_required
def get_admin_dashboard_stats():
    """Получение статистики для главной страницы админки"""
    conn = get_db_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Предложения на модерации
        cur.execute("""
                    SELECT COUNT(*) as count
                    FROM place_suggestions
                    WHERE status = 'pending'
                    """)
        pending_suggestions = cur.fetchone()['count']

        # Сообщения об ошибках на рассмотрении
        cur.execute("""
                    SELECT COUNT(*) as count
                    FROM place_reports
                    WHERE status = 'pending'
                    """)
        pending_reports = cur.fetchone()['count']

        # Всего мест в базе
        cur.execute("SELECT COUNT(*) as count FROM places")
        total_places = cur.fetchone()['count']

        return jsonify({
            'success': True,
            'pending_suggestions': pending_suggestions,
            'pending_reports': pending_reports,
            'total_places': total_places
        })

    except Exception as e:
        print(f"Ошибка при получении статистики: {e}")
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()

@app.route('/api/admin/dashboard/activities')
@login_required
@admin_required
def get_admin_dashboard_activities():
    """Получение последних активностей"""
    conn = get_db_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Собираем активности из разных источников
        activities = []

        # 1. Последние предложения
        cur.execute("""
                    SELECT
                        id, user_title as title,
                        'Предложение нового места' as description,
                        'suggestion' as type,
                        created_at
                    FROM place_suggestions
                    WHERE status = 'pending'
                    ORDER BY created_at DESC
                    LIMIT 5
                    """)

        for row in cur.fetchall():
            activities.append(dict(row))

        # 2. Последние сообщения об ошибках
        cur.execute("""
                    SELECT
                        pr.id,
                        CONCAT('Сообщение: ', pr.subject) as title,
                        CONCAT('Место: ', p.title) as description,
                        'report' as type,
                        pr.created_at
                    FROM place_reports pr
                             JOIN places p ON pr.place_id = p.id
                    WHERE pr.status = 'pending'
                    ORDER BY pr.created_at DESC
                    LIMIT 5
                    """)

        for row in cur.fetchall():
            activities.append(dict(row))

        # 3. Недавно обработанные предложения
        cur.execute("""
                    SELECT
                        id, user_title as title,
                        CASE
                            WHEN status = 'approved' THEN 'Предложение одобрено'
                            ELSE 'Предложение отклонено'
                            END as description,
                        CASE
                            WHEN status = 'approved' THEN 'approval'
                            ELSE 'rejection'
                            END as type,
                        updated_at as created_at
                    FROM place_suggestions
                    WHERE status IN ('approved', 'rejected')
                    ORDER BY updated_at DESC
                    LIMIT 3
                    """)

        for row in cur.fetchall():
            activities.append(dict(row))

        # Сортируем по дате (новые сверху)
        activities.sort(key=lambda x: x['created_at'], reverse=True)

        # Ограничиваем 10 последними
        activities = activities[:10]

        # Преобразуем даты в строки
        for activity in activities:
            if activity['created_at']:
                activity['created_at'] = activity['created_at'].isoformat()

        return jsonify({
            'success': True,
            'activities': activities
        })

    except Exception as e:
        print(f"Ошибка при получении активностей: {e}")
        return jsonify({'success': True, 'activities': []})
    finally:
        conn.close()

# РАБОТА С ФОТОГРАФИЯМИ
def allowed_file(filename):
    """Проверяем, разрешено ли расширение файла"""
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_uploaded_file(file, folder='photos'):
    """
    Сохраняет загруженный файл в папку static/uploads/{folder}
    и возвращает URL для доступа к файлу.
    """
    if file and allowed_file(file.filename):
        # Получаем расширение файла
        ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
        # Генерируем уникальное имя (UUID + расширение)
        unique_filename = f"{uuid.uuid4().hex}.{ext}" if ext else uuid.uuid4().hex
        # Полный путь к папке назначения
        upload_path = os.path.join(app.config['UPLOAD_FOLDER'], folder)
        os.makedirs(upload_path, exist_ok=True)  # создаём, если нет
        file_path = os.path.join(upload_path, unique_filename)
        try:
            file.save(file_path)
            print(f"[SAVE] Файл сохранён: {file_path}")
            # Возвращаем URL для доступа через статику
            return f'/static/uploads/{folder}/{unique_filename}'
        except Exception as e:
            print(f"[SAVE] Ошибка сохранения {unique_filename}: {e}")
            return None
    else:
        print(f"[SAVE] Недопустимый файл: {file.filename if file else 'None'}")
        return None


# ============ СТРАНИЦА МЕСТ ============
# ============ СТРАНИЦА ВСЕХ МЕСТ ============

@app.route('/places')
def places_page():
    """Страница со всеми местами с поиском и фильтрацией"""
    return render_template('places.html')


@app.route('/api/places/search-filter')
def search_filter_places():
    """API для поиска и фильтрации мест"""
    search_query = request.args.get('q', '').strip()
    category_filter = request.args.get('category', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 12, type=int)
    offset = (page - 1) * per_page

    # Получаем список уже загруженных ID из запроса
    exclude_ids_str = request.args.get('exclude_ids', '')
    exclude_ids = []
    if exclude_ids_str:
        exclude_ids = [int(id.strip()) for id in exclude_ids_str.split(',') if id.strip()]

    # Если переданы несколько категорий через запятую
    categories_filter = []
    if category_filter:
        categories_filter = [cat.strip() for cat in category_filter.split(',')]

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        # Базовый запрос
        sql = """
              SELECT id, title, slug, categories,
                     COALESCE(main_photo_url, '') as photo_url,
                     COALESCE(description, '') as description,
                     COALESCE(address, '') as address,
                     COALESCE(timetable, '') as timetable
              FROM places
              WHERE NOT is_closed
              """

        params = []

        # Добавляем условия поиска
        conditions = []

        if search_query:
            # ПОЛНОТЕКСТОВЫЙ ПОИСК по нескольким полям
            conditions.append("""
                (title ILIKE %s OR 
                 description ILIKE %s OR 
                 address ILIKE %s OR
                 EXISTS (
                     SELECT 1 FROM jsonb_array_elements_text(categories) cat
                     WHERE cat ILIKE %s
                 ))
            """)
            search_pattern = f"%{search_query}%"
            params.extend([search_pattern, search_pattern, search_pattern, search_pattern])

        if categories_filter:
            # Создаем условие для каждой категории
            category_conditions = []
            for category in categories_filter:
                category_conditions.append("categories::jsonb @> %s::jsonb")
                params.append(json.dumps([category]))

            if category_conditions:
                conditions.append(f"({' OR '.join(category_conditions)})")

        # Добавляем условие для исключения уже загруженных ID
        if exclude_ids:
            exclude_ids_str = ','.join(map(str, exclude_ids))
            conditions.append(f"id NOT IN ({exclude_ids_str})")

        # Объединяем условия
        if conditions:
            sql += " AND " + " AND ".join(conditions)

        # ВАЖНО: Выбираем порядок в зависимости от наличия поиска/фильтров
        if search_query or categories_filter:
            # ПРИ ПОИСКЕ ИЛИ ФИЛЬТРАЦИИ: сортируем по релевантности
            if search_query:
                # Сначала места, где поисковый запрос в начале названия
                # Затем - где в середине названия
                # Затем - в описании
                # Затем - в адресе
                # Затем - по алфавиту
                sql += """
                    ORDER BY 
                        CASE 
                            WHEN title ILIKE %s THEN 1  -- Начинается с запроса
                            WHEN title ILIKE %s THEN 2  -- Содержит запрос в названии
                            WHEN description ILIKE %s THEN 3  -- В описании
                            WHEN address ILIKE %s THEN 4  -- В адресе
                            ELSE 5
                        END,
                        title ASC  -- Затем по алфавиту
                """
                start_pattern = f"{search_query}%"
                contains_pattern = f"%{search_query}%"
                params.extend([start_pattern, contains_pattern, contains_pattern, contains_pattern])
            else:
                # Только фильтрация по категориям без поиска - сортируем по алфавиту
                sql += " ORDER BY title ASC"
        else:
            # БЕЗ ПОИСКА И ФИЛЬТРАЦИИ: случайный порядок (только при начальной загрузке)
            sql += " ORDER BY RANDOM()"

        sql += " LIMIT %s OFFSET %s"
        params.extend([per_page, offset])

        # Выполняем запрос
        cur.execute(sql, params)
        places = [process_place_row(row) for row in cur.fetchall()]

        # Получаем общее количество для пагинации
        count_sql = "SELECT COUNT(*) as total FROM places WHERE NOT is_closed"
        count_params = []

        if conditions:
            count_sql += " AND " + " AND ".join(conditions)
            # Копируем параметры, но без последних 4 (для сортировки) и без LIMIT/OFFSET
            if search_query:
                # Убираем последние 4 параметра сортировки + 2 параметра пагинации
                count_params = params[:-6]
            else:
                # Убираем только параметры пагинации
                count_params = params[:-2]

        cur.execute(count_sql, count_params)
        total_count = cur.fetchone()['total']

        # Получаем все категории для фильтра
        cur.execute("""
                    SELECT DISTINCT ca.slug, ca.name
                    FROM categories_api ca
                    WHERE EXISTS (
                        SELECT 1
                        FROM places p
                        WHERE NOT p.is_closed
                          AND p.categories::jsonb @> jsonb_build_array(ca.slug)
                    )
                    ORDER BY ca.name
                    """)

        all_categories = []
        for row in cur.fetchall():
            all_categories.append({
                'slug': row['slug'],
                'name': row['name']
            })

        # Определяем, есть ли еще места для загрузки
        has_more = (offset + len(places)) < total_count

        return jsonify({
            'success': True,
            'places': places,
            'total': total_count,
            'page': page,
            'per_page': per_page,
            'has_more': has_more,
            'all_categories': all_categories,
            'search_query': search_query,
            'category_filter': category_filter,
            'is_search_mode': bool(search_query or categories_filter)  # Добавляем флаг режима
        })

    except Exception as e:
        print(f"Ошибка в search_filter_places: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()



# ============ АДМИН-ПАНЕЛЬ: РЕДАКТИРОВАНИЕ МЕСТ ============
# ============ АДМИН-ПАНЕЛЬ: СПИСОК МЕСТ ============

@app.route('/admin/places')
@login_required
@admin_required
def admin_places_list():
    """Страница со списком всех мест для администратора"""
    return render_template('admin/places_list.html', active_page='places')

@app.route('/api/admin/places')
@login_required
@admin_required
def get_admin_places():
    """Получение списка мест для админ-панели (с поиском и пагинацией)"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        search = request.args.get('search', '').strip()
        offset = (page - 1) * per_page

        query = """
                SELECT id, title, slug, address, main_photo_url,
                       is_closed, updated_at
                FROM places
                WHERE 1=1 \
                """
        params = []

        if search:
            query += " AND (title ILIKE %s OR address ILIKE %s)"
            params.extend([f'%{search}%', f'%{search}%'])

        query += " ORDER BY id ASC LIMIT %s OFFSET %s"
        params.extend([per_page, offset])

        cur.execute(query, params)
        places = [dict(row) for row in cur.fetchall()]

        for p in places:
            if p.get('updated_at'):
                p['updated_at'] = p['updated_at'].isoformat()

        # Общее количество
        count_query = "SELECT COUNT(*) as total FROM places WHERE 1=1"
        count_params = []
        if search:
            count_query += " AND (title ILIKE %s OR address ILIKE %s)"
            count_params.extend([f'%{search}%', f'%{search}%'])
        cur.execute(count_query, count_params)
        total = cur.fetchone()['total']

        return jsonify({
            'success': True,
            'places': places,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'total_pages': (total + per_page - 1) // per_page,
                'has_prev': page > 1,
                'has_next': page < (total + per_page - 1) // per_page
            }
        })
    except Exception as e:
        print(f"Ошибка получения списка мест: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()


@app.route('/admin/place/<int:place_id>')
@login_required
@admin_required
def admin_place_edit(place_id):
    """Страница редактирования места в админ-панели"""
    return render_template('admin/place_edit.html', place_id=place_id)

@app.route('/api/admin/place/<int:place_id>')
@login_required
@admin_required
def get_admin_place(place_id):
    """Получение полных данных места для редактирования"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        cur.execute("""
                    SELECT
                        id, title, short_title, slug, address,
                        timetable, phone, description, body_text, foreign_url,
                        coords, subway, photos, main_photo_url,
                        categories, is_closed, created_at, updated_at
                    FROM places
                    WHERE id = %s
                    """, (place_id,))
        place = cur.fetchone()
        if not place:
            return jsonify({'success': False, 'error': 'Место не найдено'}), 404

        place_dict = dict(place)

        # Сериализация дат
        for f in ['created_at', 'updated_at']:
            if place_dict.get(f):
                place_dict[f] = place_dict[f].isoformat()

        # Парсинг JSON полей
        json_fields = ['coords', 'subway', 'photos', 'categories']
        for field in json_fields:
            if place_dict.get(field):
                if isinstance(place_dict[field], str):
                    try:
                        place_dict[field] = json.loads(place_dict[field])
                    except:
                        place_dict[field] = {} if field == 'coords' else []
            else:
                place_dict[field] = {} if field == 'coords' else []

        return jsonify({'success': True, 'place': place_dict})
    except Exception as e:
        print(f"Ошибка получения места: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()

@app.route('/api/admin/place/<int:place_id>/update', methods=['POST'])
@login_required
@admin_required
def update_admin_place(place_id):
    """Сохранение изменений места (редактирование админом)"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        data = request.json
        updates = data.get('updates', {})

        # Маппинг полей
        field_mapping = {
            'title': 'title',
            'short_title': 'short_title',
            'slug': 'slug',
            'address': 'address',
            'timetable': 'timetable',
            'phone': 'phone',
            'description': 'description',
            'body_text': 'body_text',
            'foreign_url': 'foreign_url',
            'coords': 'coords',
            'subway': 'subway',
            'photos': 'photos',
            'main_photo_url': 'main_photo_url',
            'is_closed': 'is_closed',
            'categories': 'categories'
        }

        update_fields = []
        update_values = []

        for form_field, db_field in field_mapping.items():
            if form_field in updates:
                update_fields.append(f"{db_field} = %s")
                value = updates[form_field]

                # Обработка JSON-полей
                if form_field in ['coords', 'subway', 'photos', 'categories']:
                    if value is not None:
                        if isinstance(value, str):
                            update_values.append(value)
                        else:
                            update_values.append(json.dumps(value))
                    else:
                        # Пустые значения: координаты -> {}, остальное -> []
                        if form_field == 'coords':
                            update_values.append(json.dumps({}))
                        else:
                            update_values.append(json.dumps([]))
                elif form_field == 'is_closed':
                    update_values.append(bool(value))
                else:
                    update_values.append(value)

        if not update_fields:
            return jsonify({'success': False, 'error': 'Нет данных для обновления'})

        update_query = f"""
            UPDATE places
            SET {', '.join(update_fields)}, updated_at = NOW()
            WHERE id = %s
            RETURNING id, title, slug
        """
        update_values.append(place_id)

        cur.execute(update_query, tuple(update_values))
        updated_place = cur.fetchone()
        conn.commit()

        return jsonify({
            'success': True,
            'message': 'Место успешно обновлено',
            'place': {
                'id': updated_place['id'],
                'title': updated_place['title'],
                'slug': updated_place['slug']
            }
        })
    except Exception as e:
        conn.rollback()
        print(f"Ошибка обновления места: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()


if __name__ == '__main__':
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static', exist_ok=True)
    os.makedirs('static/uploads', exist_ok=True)
    os.makedirs('static/uploads/suggestions', exist_ok=True)  # Для загруженных фото предложений

    app.run(debug=True, port=5000, host='0.0.0.0')