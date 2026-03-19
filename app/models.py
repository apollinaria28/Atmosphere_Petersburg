# app/models.py

import psycopg2.extras
from flask_login import UserMixin

from .db import get_db_connection  # функция получения соединения с БД


class User(UserMixin):
    """Модель пользователя для Flask-Login."""

    def __init__(self, user_data):
        self.id = str(user_data['id'])
        self.email = user_data['email']
        self.username = user_data.get('username')
        self.role = user_data['role']
        self.avatar_url = user_data.get('avatar_url')
        # Сохраняем is_active как приватный атрибут
        self._active = bool(user_data.get('is_active', True))
        self.created_at = user_data.get('created_at')
        self.updated_at = user_data.get('updated_at') 

    @property
    def is_active(self):
        return self._active

    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def get_display_name(self):
        """Возвращает отображаемое имя в приоритете."""
        return self.username or self.email.split('@')[0]

    def get_id(self):
        """Возвращает ID пользователя как строку (требование Flask-Login)."""
        return str(self.id)

# app/models.py (дополнение)

class Route:
    """Модель маршрута пользователя."""

    def __init__(self, data):
        self.id = data['id']
        self.user_id = data['user_id']
        self.name = data['name']
        self.description = data.get('description')
        self.created_at = data.get('created_at')
        self.updated_at = data.get('updated_at')

    @staticmethod
    def create(user_id, name, description=None):
        """Создать новый маршрут. Возвращает объект Route."""
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        try:
            cur.execute("""
                INSERT INTO routes (user_id, name, description)
                VALUES (%s, %s, %s)
                RETURNING *
            """, (user_id, name, description))
            conn.commit()
            row = cur.fetchone()
            return Route(row) if row else None
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cur.close()
            conn.close()

    @staticmethod
    def get_by_id(route_id):
        """Получить маршрут по ID."""
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        try:
            cur.execute("SELECT * FROM routes WHERE id = %s", (route_id,))
            row = cur.fetchone()
            return Route(row) if row else None
        finally:
            cur.close()
            conn.close()

    @staticmethod
    def get_by_user(user_id):
        """Получить все маршруты пользователя (отсортированные по дате создания)."""
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        try:
            cur.execute("""
                SELECT * FROM routes 
                WHERE user_id = %s 
                ORDER BY created_at DESC
            """, (user_id,))
            rows = cur.fetchall()
            return [Route(row) for row in rows]
        finally:
            cur.close()
            conn.close()

    def update(self, name=None, description=None):
        """Обновить название и/или описание маршрута."""
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("""
                UPDATE routes 
                SET name = COALESCE(%s, name),
                    description = COALESCE(%s, description),
                    updated_at = NOW()
                WHERE id = %s
            """, (name, description, self.id))
            conn.commit()
            if name:
                self.name = name
            if description is not None:
                self.description = description
            return True
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cur.close()
            conn.close()

    def delete(self):
        """Удалить маршрут и все связанные места (каскадно)."""
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM routes WHERE id = %s", (self.id,))
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cur.close()
            conn.close()

    def add_place(self, place_id):
        """
        Добавить место в маршрут.
        Возвращает созданную запись RoutePlace или None, если место уже есть.
        """
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        try:
            # Определяем следующий порядковый номер
            cur.execute("""
                SELECT COALESCE(MAX(order_index), 0) + 1 AS next_order
                FROM route_places
                WHERE route_id = %s
            """, (self.id,))
            next_order = cur.fetchone()['next_order']

            # Пытаемся вставить
            cur.execute("""
                INSERT INTO route_places (route_id, place_id, order_index)
                VALUES (%s, %s, %s)
                ON CONFLICT (route_id, place_id) DO NOTHING
                RETURNING *
            """, (self.id, place_id, next_order))
            conn.commit()
            row = cur.fetchone()
            return RoutePlace(row) if row else None
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cur.close()
            conn.close()

    def remove_place(self, place_id):
        """Удалить место из маршрута."""
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("""
                DELETE FROM route_places 
                WHERE route_id = %s AND place_id = %s
            """, (self.id, place_id))
            conn.commit()
            return cur.rowcount > 0
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cur.close()
            conn.close()

    def get_places(self):
        """
        Получить все места маршрута, отсортированные по order_index.
        Возвращает список словарей с данными места (из таблицы places) + порядок.
        """
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        try:
            cur.execute("""
                SELECT p.*, rp.order_index, rp.id AS route_place_id
                FROM route_places rp
                JOIN places p ON p.id = rp.place_id
                WHERE rp.route_id = %s
                ORDER BY rp.order_index
            """, (self.id,))
            return cur.fetchall()  # список dict-строк
        finally:
            cur.close()
            conn.close()

    def update_places_order(self, place_ids_in_order):
        """
        Обновить порядок мест в маршруте.
        place_ids_in_order — список ID мест в нужном порядке.
        """
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            # Начинаем транзакцию
            for idx, place_id in enumerate(place_ids_in_order, start=1):
                cur.execute("""
                    UPDATE route_places
                    SET order_index = %s
                    WHERE route_id = %s AND place_id = %s
                """, (idx, self.id, place_id))
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cur.close()
            conn.close()


class RoutePlace:
    """Модель связи маршрута и места (используется редко, но может пригодиться)."""

    def __init__(self, data):
        self.id = data['id']
        self.route_id = data['route_id']
        self.place_id = data['place_id']
        self.order_index = data['order_index']
        self.created_at = data.get('created_at')

    @staticmethod
    def get_by_route_and_place(route_id, place_id):
        """Проверить, есть ли уже место в маршруте."""
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        try:
            cur.execute("""
                SELECT * FROM route_places
                WHERE route_id = %s AND place_id = %s
            """, (route_id, place_id))
            row = cur.fetchone()
            return RoutePlace(row) if row else None
        finally:
            cur.close()
            conn.close()

class Place:
    """Модель для работы с таблицей places."""

    def __init__(self, data):
        self.id = data['id']
        self.external_id = data.get('external_id')
        self.title = data['title']
        self.short_title = data.get('short_title')
        self.slug = data.get('slug')
        self.categories = data.get('categories')  # JSONB
        self.address = data.get('address')
        self.timetable = data.get('timetable')
        self.phone = data.get('phone')
        self.description = data.get('description')
        self.body_text = data.get('body_text')
        self.foreign_url = data.get('foreign_url')
        self.coords = data.get('coords')  # JSONB вида {"lat": ..., "lon": ...}
        self.subway = data.get('subway')
        self.is_closed = data.get('is_closed', False)
        self.photos = data.get('photos')
        self.main_photo_url = data.get('main_photo_url')
        self.created_at = data.get('created_at')

    @staticmethod
    def get_by_id(place_id):
        """Получить место по ID."""
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        try:
            cur.execute("SELECT * FROM places WHERE id = %s", (place_id,))
            row = cur.fetchone()
            return Place(row) if row else None
        finally:
            cur.close()
            conn.close()


    @staticmethod
    def get_nearby(place_id, radius=1000, limit=10):
        """
        Найти места, ближайшие к заданному.
        Возвращает список словарей с полями id, title, coords, distance,
        description, address, main_photo_url, photos.
        """
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        try:
            cur.execute("SELECT coords->>'lat' AS lat, coords->>'lon' AS lon FROM places WHERE id = %s", (place_id,))
            row = cur.fetchone()
            if not row or row['lat'] is None or row['lon'] is None:
                return []

            lat = float(row['lat'])
            lon = float(row['lon'])

            # Подзапрос для вычисления distance, затем фильтрация во внешнем запросе
            query = """
                SELECT id, title, coords, description, address, main_photo_url, photos, distance
                FROM (
                    SELECT 
                        id,
                        title,
                        coords,
                        description,
                        address,
                        main_photo_url,
                        photos,
                        6371000 * 2 * asin(
                            sqrt(
                                power(sin((radians((coords->>'lat')::float) - radians(%s)) / 2), 2) +
                                cos(radians(%s)) * cos(radians((coords->>'lat')::float)) *
                                power(sin((radians((coords->>'lon')::float) - radians(%s)) / 2), 2)
                            )
                        ) AS distance
                    FROM places
                    WHERE 
                        id != %s
                        AND coords->>'lat' IS NOT NULL
                        AND coords->>'lon' IS NOT NULL
                ) sub
                WHERE distance < %s
                ORDER BY distance
                LIMIT %s
            """
            cur.execute(query, (lat, lat, lon, place_id, radius, limit))
            results = cur.fetchall()
            nearby = []
            for row in results:
                nearby.append({
                    'id': row['id'],
                    'title': row['title'],
                    'coords': row['coords'],
                    'distance': round(row['distance'], 1),
                    'description': row['description'],
                    'address': row['address'],
                    'main_photo_url': row['main_photo_url'],
                    'photos': row['photos']
                })
            return nearby
        finally:
            cur.close()
            conn.close()
def load_user(user_id):
    """Загрузчик пользователя для Flask-Login."""
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