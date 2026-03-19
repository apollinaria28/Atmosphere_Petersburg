# app/routes/visited.py
from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required, current_user
import psycopg2
import psycopg2.extras
import json
import traceback

# Импортируем вспомогательные функции из других модулей проекта
from app.db import get_db_connection
from app.utils import process_place_row

# Создаём blueprint для функционала посещённых мест
visited_bp = Blueprint('visited', __name__)


# ============ СТРАНИЦА ПОСЕЩЁННЫХ МЕСТ ============
@visited_bp.route('/visited')
@login_required
def visited_page():
    """Страница посещённых мест"""
    return render_template('visited.html')


# ============ API ПОСЕЩЁННЫХ МЕСТ ============

@visited_bp.route('/api/visited/toggle', methods=['POST'])
@login_required
def toggle_visited():
    """Добавление/удаление места в посещённые"""
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

        # Проверяем, есть ли уже в посещённых
        cur.execute("""
            SELECT id FROM visited_places
            WHERE user_id = %s AND place_id = %s
        """, (current_user.id, place_id))

        existing = cur.fetchone()

        if existing:
            # Удаляем из посещённых
            cur.execute("""
                DELETE FROM visited_places
                WHERE user_id = %s AND place_id = %s
            """, (current_user.id, place_id))
            action = 'removed'
        else:
            # Добавляем в посещённые
            cur.execute("""
                INSERT INTO visited_places (user_id, place_id)
                VALUES (%s, %s)
            """, (current_user.id, place_id))
            action = 'added'

        conn.commit()

        # Получаем обновлённое количество посещённых
        cur.execute("""
            SELECT COUNT(*) as count FROM visited_places
            WHERE user_id = %s
        """, (current_user.id,))

        count = cur.fetchone()['count']

        return jsonify({
            'success': True,
            'action': action,
            'visited_count': count,
            'message': 'Место отмечено как посещённое' if action == 'added' else 'Место удалено из посещённых'
        })

    except Exception as e:
        conn.rollback()
        print(f"Ошибка при работе с посещёнными местами: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()


@visited_bp.route('/api/visited/status')
@login_required
def check_visited_status():
    """Проверка статуса посещённых для нескольких мест"""
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

        # Получаем статус посещённых для каждого места
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
        print(f"Ошибка при проверке статуса посещённых мест: {e}")
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()


@visited_bp.route('/api/visited/list')
@login_required
def get_visited_list():
    """Получение списка посещённых мест с пагинацией"""
    conn = get_db_connection()
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 12, type=int)
        offset = (page - 1) * per_page

        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Получаем посещённые места с пагинацией
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
        print(f"Ошибка при получении посещённых мест: {e}")
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()


@visited_bp.route('/api/visited/count')
@login_required
def get_visited_count():
    """Получение количества посещённых мест"""
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
        print(f"Ошибка при получении количества посещённых мест: {e}")
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()