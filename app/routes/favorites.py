# app/routes/favorites.py
from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required, current_user
import psycopg2
import psycopg2.extras
import json
import traceback

# Импортируем вспомогательные функции из других модулей проекта
from app.utils import process_place_row
from app.db import get_db_connection 

# Создаём blueprint для функционала избранного
favorites_bp = Blueprint('favorites', __name__)

# ============ СТРАНИЦА ИЗБРАННОГО ============
@favorites_bp.route('/favorites')
@login_required
def favorites_page():
    """Страница избранного"""
    return render_template('favorites.html')

# ============ API ИЗБРАННОГО ============

@favorites_bp.route('/api/favorites/toggle', methods=['POST'])
@login_required
def toggle_favorite():
    """Добавление/удаление места в избранное"""
    conn = get_db_connection()
    try:
        data = request.json
        try:
            place_id = int(data.get('place_id'))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'Неверный формат ID'}), 400

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

        # Получаем обновлённое количество избранных
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


@favorites_bp.route('/api/favorites/status')
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


@favorites_bp.route('/api/favorites/list')
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


@favorites_bp.route('/api/favorites/count')
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