import json
import logging
import traceback

import psycopg2.extras
from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user

from app.db import get_db_connection
from app.decorators import admin_required
from app.utils import process_categories, get_categories_safe, save_uploaded_file

admin_bp = Blueprint('admin', __name__)

security_logger = logging.getLogger('security')


# ---------------------------------------------------------------------------
# /api/me — защищённый эндпоинт для определения роли после логина.
# Клиент вызывает его сразу после успешного /api/login и на основе role
# решает, делать ли редирект на /admin. Роль не передаётся в ответе /api/login,
# поэтому злоумышленник, перебирая emails, не узнает, кто является администратором.
# ---------------------------------------------------------------------------
@admin_bp.route('/api/me')
@login_required
def get_current_user():
    """Возвращает базовые данные текущего пользователя, включая роль."""
    security_logger.info(
        f"/api/me | user={current_user.email} role={current_user.role} | IP: {request.remote_addr}"
    )
    return jsonify({
        'success': True,
        'user': {
            'id': current_user.id,
            'username': current_user.username,
            'email': current_user.email,
            'role': current_user.role,
            'avatar_url': getattr(current_user, 'avatar_url', None),
        }
    })


# ---------- Страницы ----------
@admin_bp.route('/admin')
@login_required
@admin_required
def dashboard():
    """Главная страница панели администратора."""
    return render_template('admin/dashboard.html', active_page='dashboard')


@admin_bp.route('/admin/suggestions')
@login_required
@admin_required
def suggestions():
    """Страница модерации предложений мест."""
    return render_template('admin/suggestions.html', active_page='suggestions')


@admin_bp.route('/admin/reports')
@login_required
@admin_required
def reports():
    """Страница модерации сообщений об ошибках."""
    return render_template('admin/reports.html', active_page='reports')


@admin_bp.route('/admin/suggestions/<int:suggestion_id>')
@login_required
@admin_required
def suggestion_detail(suggestion_id):
    """Страница модерации конкретного предложения."""
    return render_template('admin/suggestion_detail.html', suggestion_id=suggestion_id)


@admin_bp.route('/admin/reports/<int:report_id>')
@login_required
@admin_required
def report_detail(report_id):
    """Страница модерации конкретного сообщения об ошибке."""
    return render_template('admin/report_detail.html', report_id=report_id)


@admin_bp.route('/admin/places')
@login_required
@admin_required
def places_list():
    """Страница со списком всех мест для администратора."""
    return render_template('admin/places_list.html', active_page='places')


@admin_bp.route('/admin/place/<int:place_id>')
@login_required
@admin_required
def place_edit(place_id):
    """Страница редактирования места в админ-панели."""
    return render_template('admin/place_edit.html', place_id=place_id)


# ---------- API для дашборда ----------
@admin_bp.route('/api/admin/dashboard/stats')
@login_required
@admin_required
def get_dashboard_stats():
    """Получение статистики для главной страницы админки."""
    conn = get_db_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        cur.execute("SELECT COUNT(*) as count FROM place_suggestions WHERE status = 'pending'")
        pending_suggestions = cur.fetchone()['count']

        cur.execute("SELECT COUNT(*) as count FROM place_reports WHERE status = 'pending'")
        pending_reports = cur.fetchone()['count']

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


@admin_bp.route('/api/admin/dashboard/activities')
@login_required
@admin_required
def get_dashboard_activities():
    """Получение последних активностей."""
    conn = get_db_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        activities = []

        # 1. Последние предложения
        cur.execute("""
            SELECT id, user_title as title,
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
            SELECT pr.id,
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
            SELECT id, user_title as title,
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
        activities = activities[:10]

        for act in activities:
            if act['created_at']:
                act['created_at'] = act['created_at'].isoformat()

        return jsonify({'success': True, 'activities': activities})
    except Exception as e:
        print(f"Ошибка при получении активностей: {e}")
        return jsonify({'success': True, 'activities': []})
    finally:
        conn.close()


# ---------- API для предложений (модерация) ----------
@admin_bp.route('/api/admin/suggestions')
@login_required
@admin_required
def get_admin_suggestions():
    """Получение списка предложений для модерации."""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        status = request.args.get('status', 'pending')
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        offset = (page - 1) * per_page

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
            WHERE 1=1
        """
        params = []

        if status != 'all':
            query += " AND ps.status = %s"
            params.append(status)

        query += """
            GROUP BY ps.id, u.id, p.id
            ORDER BY ps.created_at DESC
            LIMIT %s OFFSET %s
        """
        params.extend([per_page, offset])

        cur.execute(query, params)
        suggestions = []
        for row in cur.fetchall():
            s = dict(row)
            for date_field in ['created_at', 'updated_at']:
                if s.get(date_field):
                    s[date_field] = s[date_field].isoformat()
            for json_field in ['user_photos', 'moderated_photos', 'moderated_coords']:
                if s.get(json_field):
                    try:
                        if isinstance(s[json_field], str):
                            s[json_field] = json.loads(s[json_field])
                    except:
                        s[json_field] = []
            suggestions.append(s)

        # Общее количество
        count_query = "SELECT COUNT(*) as total FROM place_suggestions ps WHERE 1=1"
        count_params = []
        if status != 'all':
            count_query += " AND ps.status = %s"
            count_params.append(status)
        cur.execute(count_query, count_params)
        total = cur.fetchone()['total']
        total_pages = (total + per_page - 1) // per_page

        # Статистика по статусам
        cur.execute("SELECT status, COUNT(*) as count FROM place_suggestions GROUP BY status")
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


@admin_bp.route('/api/admin/suggestions/<int:suggestion_id>')
@login_required
@admin_required
def get_suggestion_detail(suggestion_id):
    """Получение детальной информации о предложении."""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
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

        # Обработка фотографий с определением типа
        for photo_field in ['user_photos', 'moderated_photos']:
            if suggestion_dict.get(photo_field):
                processed = []
                for photo in suggestion_dict[photo_field]:
                    if isinstance(photo, str) and photo.strip():
                        is_external = photo.strip().startswith('http')
                        processed.append({
                            'url': photo.strip(),
                            'is_external': is_external,
                            'type': 'external' if is_external else 'upload'
                        })
                suggestion_dict[f'{photo_field}_processed'] = processed

        # Категории пользователя
        cur.execute("""
            SELECT c.id, c.slug, c.name
            FROM place_suggestion_user_categories psuc
            JOIN categories_api c ON psuc.category_id = c.id
            WHERE psuc.suggestion_id = %s
            ORDER BY c.name
        """, (suggestion_id,))
        suggestion_dict['user_categories'] = [dict(row) for row in cur.fetchall()]

        # Категории модератора
        cur.execute("""
            SELECT c.id, c.slug, c.name
            FROM place_suggestion_moderated_categories psmc
            JOIN categories_api c ON psmc.category_id = c.id
            WHERE psmc.suggestion_id = %s
            ORDER BY c.name
        """, (suggestion_id,))
        suggestion_dict['moderated_categories'] = [dict(row) for row in cur.fetchall()]

        # Информация о созданном месте
        if suggestion_dict.get('created_place_id'):
            cur.execute("SELECT title, slug, main_photo_url, address FROM places WHERE id = %s",
                        (suggestion_dict['created_place_id'],))
            place_info = cur.fetchone()
            if place_info:
                suggestion_dict['place_info'] = dict(place_info)

        return jsonify({'success': True, 'suggestion': suggestion_dict})
    except Exception as e:
        print(f"Ошибка при получении деталей предложения: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()


@admin_bp.route('/api/admin/suggestions/<int:suggestion_id>', methods=['PUT'])
@login_required
@admin_required
def update_suggestion(suggestion_id):
    """Обновление данных предложения модератором (без изменения статуса)."""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        data = request.json

        cur.execute("SELECT id, status FROM place_suggestions WHERE id = %s", (suggestion_id,))
        suggestion = cur.fetchone()
        if not suggestion:
            return jsonify({'success': False, 'error': 'Предложение не найдено'})
        if suggestion['status'] != 'pending':
            return jsonify({'success': False, 'error': 'Можно редактировать только предложения на модерации'})

        # Подготавливаем данные для обновления
        update_fields = []
        update_values = []

        moderated_fields = [
            'title', 'short_title', 'slug', 'address', 'timetable', 'phone',
            'description', 'body_text', 'foreign_url', 'coords',
            'photos', 'main_photo_url'
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

        if 'moderated_is_closed' in data:
            update_fields.append("moderated_is_closed = %s")
            update_values.append(bool(data['moderated_is_closed']))

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
            cur.execute("DELETE FROM place_suggestion_moderated_categories WHERE suggestion_id = %s", (suggestion_id,))
            for cat_id in data['moderated_category_ids']:
                cur.execute("""
                    INSERT INTO place_suggestion_moderated_categories (suggestion_id, category_id)
                    VALUES (%s, %s) ON CONFLICT DO NOTHING
                """, (suggestion_id, cat_id))

        conn.commit()
        return jsonify({'success': True, 'message': 'Данные успешно обновлены'})
    except Exception as e:
        conn.rollback()
        print(f"Ошибка при обновлении предложения: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()


@admin_bp.route('/api/admin/suggestions/upload-photo', methods=['POST'])
@login_required
@admin_required
def upload_moderator_photo():
    """Загрузка фотографии модератором для предложения."""
    try:
        if 'photo' not in request.files:
            return jsonify({'success': False, 'error': 'Нет файла'})
        file = request.files['photo']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'Пустой файл'})

        upload_folder = current_app.config['UPLOAD_FOLDER']
        allowed_extensions = current_app.config['ALLOWED_EXTENSIONS']
        photo_url = save_uploaded_file(file, 'suggestions', upload_folder, allowed_extensions)

        if photo_url:
            return jsonify({'success': True, 'url': photo_url, 'message': 'Фото загружено'})
        else:
            return jsonify({'success': False, 'error': 'Ошибка сохранения файла'})
    except Exception as e:
        print(f"Ошибка загрузки фото модератором: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})


@admin_bp.route('/api/admin/suggestions/<int:suggestion_id>/approve', methods=['POST'])
@login_required
@admin_required
def approve_suggestion(suggestion_id):
    """Одобрение предложения и создание места."""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        data = request.json
        admin_comment = data.get('admin_comment', '')

        cur.execute("SELECT * FROM place_suggestions WHERE id = %s AND status = 'pending'", (suggestion_id,))
        suggestion = cur.fetchone()
        if not suggestion:
            return jsonify({'success': False, 'error': 'Предложение не найдено или уже рассмотрено'})

        suggestion_dict = dict(suggestion)

        # Проверяем обязательные поля модератора
        required_fields = ['moderated_title', 'moderated_slug']
        for field in required_fields:
            if not suggestion_dict.get(field):
                return jsonify({
                    'success': False,
                    'error': f'Заполните поле: {field.replace("moderated_", "")}'
                })

        # Проверяем уникальность slug
        cur.execute("SELECT id FROM places WHERE slug = %s", (suggestion_dict['moderated_slug'],))
        if cur.fetchone():
            return jsonify({'success': False, 'error': 'Такой URL-адрес уже существует'})

        # Формируем данные для нового места
        title = suggestion_dict.get('moderated_title') or suggestion_dict['user_title']
        short_title = suggestion_dict.get('moderated_short_title') or suggestion_dict.get('user_title', '')[:200]
        slug = suggestion_dict['moderated_slug']

        # Категории (приоритет: модератор → пользователь)
        cur.execute("""
            SELECT c.slug
            FROM place_suggestion_moderated_categories psmc
            JOIN categories_api c ON psmc.category_id = c.id
            WHERE psmc.suggestion_id = %s
        """, (suggestion_id,))
        mod_cats = [row['slug'] for row in cur.fetchall()]
        if mod_cats:
            categories_json = json.dumps(mod_cats)
        else:
            cur.execute("""
                SELECT c.slug
                FROM place_suggestion_user_categories psuc
                JOIN categories_api c ON psuc.category_id = c.id
                WHERE psuc.suggestion_id = %s
            """, (suggestion_id,))
            user_cats = [row['slug'] for row in cur.fetchall()]
            categories_json = json.dumps(user_cats) if user_cats else '[]'

        address = suggestion_dict.get('moderated_address') or suggestion_dict.get('user_address', '')
        timetable = suggestion_dict.get('moderated_timetable') or suggestion_dict.get('user_timetable', '')
        phone = suggestion_dict.get('moderated_phone') or suggestion_dict.get('user_phone', '')
        description = suggestion_dict.get('moderated_description') or suggestion_dict.get('user_description', '')
        body_text = suggestion_dict.get('moderated_body_text', '')
        foreign_url = suggestion_dict.get('moderated_foreign_url') or suggestion_dict.get('user_foreign_url', '')
        is_closed = bool(suggestion_dict.get('moderated_is_closed', False))

        # Координаты
        coords = suggestion_dict.get('moderated_coords') or '{}'
        if isinstance(coords, (dict, list)):
            coords = json.dumps(coords)

        # Метро (пока пустое)
        subway = '[]'

        # Фотографии
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

        mod_photos = parse_json_field(suggestion_dict.get('moderated_photos'))
        user_photos = parse_json_field(suggestion_dict.get('user_photos', []))
        photos_list = mod_photos if mod_photos else user_photos
        photos_json = json.dumps(photos_list)

        # Главное фото
        main_photo_url = suggestion_dict.get('moderated_main_photo_url')
        if not main_photo_url and mod_photos:
            main_photo_url = mod_photos[0]
        if not main_photo_url:
            main_photo_url = suggestion_dict.get('user_main_photo_url')
        if not main_photo_url and user_photos:
            main_photo_url = user_photos[0]
        if not main_photo_url:
            main_photo_url = ''

        # Вставка нового места
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

        # Обновляем предложение
        cur.execute("""
            UPDATE place_suggestions
            SET status = 'approved',
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


@admin_bp.route('/api/admin/suggestions/<int:suggestion_id>/reject', methods=['POST'])
@login_required
@admin_required
def reject_suggestion(suggestion_id):
    """Отклонение предложения."""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        data = request.json
        admin_comment = data.get('admin_comment', '')

        cur.execute("SELECT id FROM place_suggestions WHERE id = %s AND status = 'pending'", (suggestion_id,))
        if not cur.fetchone():
            return jsonify({'success': False, 'error': 'Предложение не найдено или уже рассмотрено'})

        cur.execute("""
            UPDATE place_suggestions
            SET status = 'rejected',
                moderated_by = %s,
                admin_comment = %s,
                updated_at = NOW()
            WHERE id = %s
        """, (current_user.id, admin_comment, suggestion_id))

        conn.commit()
        return jsonify({'success': True, 'message': 'Предложение отклонено.'})
    except Exception as e:
        conn.rollback()
        print(f"Ошибка при отклонении предложения: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()


@admin_bp.route('/api/admin/suggestions/<int:suggestion_id>/check-duplicates', methods=['POST'])
@login_required
@admin_required
def check_suggestion_duplicates(suggestion_id):
    """Проверка дубликатов по данным из предложения или переданным параметрам."""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        data = request.json
        title = data.get('title', '').strip()
        address = data.get('address', '').strip()
        coords = data.get('coords', {})

        if not title:
            cur.execute("SELECT user_title, moderated_title FROM place_suggestions WHERE id = %s", (suggestion_id,))
            s = cur.fetchone()
            if s:
                title = s['moderated_title'] or s['user_title'] or ''

        duplicates = []
        if title:
            cur.execute("""
                SELECT id, title, slug, address, main_photo_url
                FROM places
                WHERE NOT is_closed AND title ILIKE %s
                LIMIT 10
            """, (f'%{title}%',))
            duplicates = [dict(row) for row in cur.fetchall()]

        return jsonify({'success': True, 'duplicates': duplicates})
    except Exception as e:
        print(f"Ошибка при проверке дубликатов: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()


# ---------- API для категорий (админская версия) ----------
@admin_bp.route('/api/admin/categories')
@login_required
@admin_required
def get_admin_categories():
    """Получение списка категорий с дополнительной статистикой для модератора."""
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
            cat = dict(row)
            cat['places_count'] = int(cat['places_count']) if cat['places_count'] else 0
            cat['suggestions_count'] = int(cat['suggestions_count']) if cat['suggestions_count'] else 0
            categories.append(cat)
        return jsonify({'success': True, 'categories': categories})
    except Exception as e:
        print(f"Ошибка при получении категорий для модератора: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()


# ---------- API для сообщений об ошибках ----------
@admin_bp.route('/api/admin/reports')
@login_required
@admin_required
def get_admin_reports():
    """Получение списка сообщений об ошибках для модерации."""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        status = request.args.get('status', 'pending')
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        offset = (page - 1) * per_page

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
            WHERE 1=1
        """
        params = []

        if status != 'all':
            query += " AND pr.status = %s"
            params.append(status)

        query += " ORDER BY pr.created_at DESC LIMIT %s OFFSET %s"
        params.extend([per_page, offset])

        cur.execute(query, params)
        reports = []
        for row in cur.fetchall():
            r = dict(row)
            for date_field in ['created_at', 'updated_at']:
                if r.get(date_field):
                    r[date_field] = r[date_field].isoformat()
            reports.append(r)

        # Общее количество
        count_query = "SELECT COUNT(*) as total FROM place_reports pr WHERE 1=1"
        count_params = []
        if status != 'all':
            count_query += " AND pr.status = %s"
            count_params.append(status)
        cur.execute(count_query, count_params)
        total = cur.fetchone()['total']
        total_pages = (total + per_page - 1) // per_page

        # Статистика по статусам
        cur.execute("SELECT status, COUNT(*) as count FROM place_reports GROUP BY status")
        stats = {row['status']: row['count'] for row in cur.fetchall()}

        # Статистика по темам
        cur.execute("""
            SELECT subject, COUNT(*) as count
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


@admin_bp.route('/api/admin/reports/<int:report_id>')
@login_required
@admin_required
def get_report_detail(report_id):
    """Получение детальной информации о сообщении об ошибке."""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
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

        for date_field in ['created_at', 'updated_at']:
            if report_dict.get(date_field):
                report_dict[date_field] = report_dict[date_field].isoformat()

        json_fields = ['place_coords', 'place_subway', 'place_categories']
        for field in json_fields:
            if report_dict.get(field):
                try:
                    if isinstance(report_dict[field], str):
                        report_dict[field] = json.loads(report_dict[field])
                except:
                    report_dict[field] = []

        if report_dict.get('place_coords') and isinstance(report_dict['place_coords'], dict):
            coords = report_dict['place_coords']
            report_dict['place_lat'] = coords.get('lat')
            report_dict['place_lon'] = coords.get('lon')

        return jsonify({'success': True, 'report': report_dict})
    except Exception as e:
        print(f"Ошибка при получении деталей сообщения: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()


@admin_bp.route('/api/admin/reports/<int:report_id>/resolve', methods=['POST'])
@login_required
@admin_required
def resolve_report(report_id):
    """Отметка сообщения об ошибке как решённого (с возможным обновлением места)."""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        data = request.json
        resolution_comment = data.get('resolution_comment', '')
        update_place = data.get('update_place', False)
        place_updates = data.get('place_updates', {})

        cur.execute("SELECT * FROM place_reports WHERE id = %s AND status = 'pending'", (report_id,))
        report = cur.fetchone()
        if not report:
            return jsonify({'success': False, 'error': 'Сообщение не найдено или уже обработано'})

        report_dict = dict(report)
        place_id = report_dict['place_id']

        if update_place and place_updates:
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
            update_fields = []
            update_values = []

            for form_field, db_field in field_mapping.items():
                if form_field in place_updates:
                    update_fields.append(f"{db_field} = %s")
                    value = place_updates[form_field]
                    if form_field in ['coords', 'subway', 'photos']:
                        if value is not None:
                            update_values.append(json.dumps(value))
                        else:
                            if form_field == 'coords':
                                update_values.append(json.dumps({}))
                            else:
                                update_values.append(json.dumps([]))
                    elif form_field == 'is_closed':
                        update_values.append(bool(value))
                    else:
                        update_values.append(value)

            if 'categories' in place_updates:
                update_fields.append("categories = %s")
                update_values.append(json.dumps(place_updates['categories']))

            if update_fields:
                update_query = f"UPDATE places SET {', '.join(update_fields)}, updated_at = NOW() WHERE id = %s"
                update_values.append(place_id)
                cur.execute(update_query, tuple(update_values))

        cur.execute("""
            UPDATE place_reports
            SET status = 'resolved',
                resolved_by = %s,
                resolution_comment = %s,
                updated_at = NOW()
            WHERE id = %s
        """, (current_user.id, resolution_comment, report_id))

        conn.commit()
        return jsonify({
            'success': True,
            'message': 'Сообщение отмечено как решённое' + (' и место обновлено' if update_place else '')
        })
    except Exception as e:
        conn.rollback()
        print(f"Ошибка при обработке сообщения об ошибке: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()


@admin_bp.route('/api/admin/reports/<int:report_id>/update-place', methods=['POST'])
@login_required
@admin_required
def update_place_from_report(report_id):
    """Обновление места на основе сообщения об ошибке (без изменения статуса обращения)."""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        data = request.json
        updates = data.get('updates', {})

        cur.execute("SELECT place_id FROM place_reports WHERE id = %s", (report_id,))
        report = cur.fetchone()
        if not report:
            return jsonify({'success': False, 'error': 'Сообщение не найдено'})

        place_id = report['place_id']

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
                if form_field in ['coords', 'subway', 'photos', 'categories']:
                    if value is not None:
                        if isinstance(value, str):
                            update_values.append(value)
                        else:
                            update_values.append(json.dumps(value))
                    else:
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
        print(f"Ошибка при обновлении места: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()


# ---------- API для управления существующими местами ----------
@admin_bp.route('/api/admin/places')
@login_required
@admin_required
def get_admin_places():
    """Получение списка мест для админ-панели (с поиском и пагинацией)."""
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
            WHERE 1=1
        """
        params = []

        if search:
            query += " AND (title ILIKE %s OR address ILIKE %s)"
            params.extend([f'%{search}%', f'%{search}%'])

        query += " ORDER BY id ASC LIMIT %s OFFSET %s"
        params.extend([per_page, offset])

        cur.execute(query, params)
        places = []
        for row in cur.fetchall():
            p = dict(row)
            if p.get('updated_at'):
                p['updated_at'] = p['updated_at'].isoformat()
            places.append(p)

        count_query = "SELECT COUNT(*) as total FROM places WHERE 1=1"
        count_params = []
        if search:
            count_query += " AND (title ILIKE %s OR address ILIKE %s)"
            count_params.extend([f'%{search}%', f'%{search}%'])
        cur.execute(count_query, count_params)
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
                'has_prev': page > 1,
                'has_next': page < total_pages
            }
        })
    except Exception as e:
        print(f"Ошибка получения списка мест: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()


@admin_bp.route('/api/admin/place/<int:place_id>')
@login_required
@admin_required
def get_admin_place(place_id):
    """Получение полных данных места для редактирования."""
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

        for f in ['created_at', 'updated_at']:
            if place_dict.get(f):
                place_dict[f] = place_dict[f].isoformat()

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


@admin_bp.route('/api/admin/place/<int:place_id>/update', methods=['POST'])
@login_required
@admin_required
def update_admin_place(place_id):
    """Сохранение изменений места (редактирование админом)."""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        data = request.json
        updates = data.get('updates', {})

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

                if form_field in ['coords', 'subway', 'photos', 'categories']:
                    if value is not None:
                        if isinstance(value, str):
                            update_values.append(value)
                        else:
                            update_values.append(json.dumps(value))
                    else:
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